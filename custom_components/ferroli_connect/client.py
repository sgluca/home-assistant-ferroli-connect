"""Cloud transport. All methods run outside the HA event loop."""
from __future__ import annotations

import hashlib
import json
import re
import ssl
import threading
import time
import math
from copy import deepcopy
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler

import paho.mqtt.client as mqtt

from .protocol import build_read_query, build_zone_control, decode_cloud_points, decode_frame, topic_from
from .const import STALE_SECONDS, valid_temperature_limits

BASE = 'https://eu-api.topband-cloud.com/'


class CloudError(Exception):
    """Safe error with no response body or URL."""


class AuthError(CloudError):
    """Authentication expired or rejected."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Api:
    def __init__(self, token=None):
        self.token = token
        # Construction may happen on Home Assistant's event loop. Certificate
        # loading and opener creation must wait until call(), run in an executor.
        self.opener = None

    def call(self, path, *, form=None, params=None, authenticated=True):
        if self.opener is None:
            self.opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), NoRedirect())
        allowed = path.startswith('api/') or path.startswith('apps/topiot_ferroli_temperature_controller/thermostat_points/')
        if not allowed or '..' in path or '://' in path:
            raise CloudError('Invalid API path')
        headers = {'APPSLUG': APP_SLUG, 'Accept': 'application/json'}
        if authenticated:
            if not self.token:
                raise AuthError('Authentication required')
            headers['Authorization'] = 'JWT ' + self.token
        body = None
        if form is not None:
            body = urlencode(form).encode()
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        url = BASE + path + ('?' + urlencode(params) if params else '')
        try:
            with self.opener.open(Request(url, data=body, headers=headers), timeout=20) as res:
                raw = res.read(4_000_001)
                if len(raw) > 4_000_000:
                    raise CloudError('Oversized API response')
                result = json.loads(raw)
        except HTTPError as exc:
            status = exc.code
            exc.close()
            if status in (401, 403):
                raise AuthError('Authentication rejected') from None
            raise CloudError(f'HTTP {status}') from None
        except (URLError, TimeoutError, OSError):
            raise CloudError('HTTPS connection failed') from None
        except (ValueError, UnicodeError):
            raise CloudError('Invalid JSON response') from None
        if not isinstance(result, dict):
            raise CloudError('Unexpected API response')
        return result

    def login(self, username, password):
        self.token = required(self.call('api/token', form={'username': username, 'password': password},
                                        authenticated=False), 'token')
        return self.account_hash()

    def account_hash(self):
        slug = required(self.call('api/current_user'), 'slug')
        return hashlib.sha256(slug.encode()).hexdigest()

    def inventory(self):
        slug = required(self.call('api/current_user'), 'slug')
        devices = []
        for page in range(1, 101):
            result = self.call('api/users/' + quote(slug, safe='') + '/devices',
                               params={'app_slug': APP_SLUG, 'page_size': 100, 'page': page})
            rows = result.get('results')
            if not isinstance(rows, list) or not all(isinstance(d, dict) for d in rows):
                raise CloudError('Invalid inventory')
            devices.extend(rows)
            if not result.get('next'):
                return devices
            if not rows:
                raise CloudError('Invalid pagination')
        raise CloudError('Inventory pagination limit')


def required(data, key):
    value = data.get(key)
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        raise CloudError('Missing required field')
    return value


class Client:
    def __init__(self, token, notify, *, read_reply_timeout=8):
        self.api = Api(token)
        self.notify = notify
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)
        self.command_lock = threading.Lock()
        self.command_targets = {}
        self.cloud_targets = {}
        self.cloud_reads = 0
        self.cloud_errors = 0
        self.cloud_stale = 0
        self.read_reply_timeout = read_reply_timeout
        self.read_target_uids = {}
        self.pending_reads = {}
        self.commands_sent = 0
        self.commands_confirmed = 0
        self.commands_unconfirmed = 0
        self.zones = {}
        self.boilers = {}
        self.boiler_ids = {}
        self.read_targets = []
        self.last_poll = None
        self.message_sequence = 0
        self.queries_sent = 0
        self.publish_errors = 0
        self.identities = {}
        self.labels = {}
        self.topics = {}
        self.client = None
        self.connected = False
        self.last_error = None
        self.received = 0
        self.invalid = 0
        self.unassigned = 0
        self._generation = 0
        self._last_refresh = time.monotonic()

    def snapshot(self):
        with self.lock:
            return {'connected': self.connected, 'zones': deepcopy(self.zones), 'boilers': deepcopy(self.boilers)}

    def diagnostics(self):
        with self.lock:
            return {'connected': self.connected, 'received': self.received, 'invalid_frames': self.invalid,
                    'unassigned_frames': self.unassigned, 'zone_count': len(self.zones),
                    'boiler_count': len(self.boilers), 'read_queries_sent': self.queries_sent,
                    'commands_sent': self.commands_sent, 'commands_confirmed': self.commands_confirmed,
                    'commands_unconfirmed': self.commands_unconfirmed,
                    'cloud_reads': self.cloud_reads, 'cloud_read_errors': self.cloud_errors,
                    'cloud_stale_snapshots': self.cloud_stale,
                    'read_publish_errors': self.publish_errors,
                    'last_read_age_seconds': round(time.monotonic()-self.last_poll) if self.last_poll is not None else None,
                    'last_error': self.last_error,
                    'zones': [{'alias': f'zone_{i}', 'received': z['received'],
                               'sources': sorted(set(z['field_sources'].values())),
                               'available_fields': sorted(z['field_sources']),
                               'read_requests': z.get('read_requests', 0),
                               'read_replies': z.get('read_replies', 0),
                               'read_timeouts': z.get('read_timeouts', 0),
                               'last_cloud_result': z.get('last_cloud_result', 'not_attempted'),
                               'age_seconds': round(time.monotonic()-z['seen']) if z['seen'] else None}
                              for i, z in enumerate(self.zones.values(), 1)],
                    'boilers': [{'alias': f'boiler_{i}', 'received': b['received'],
                                 'age_seconds': round(time.monotonic()-b['seen']) if b['seen'] else None}
                                for i, b in enumerate(self.boilers.values(), 1)]}

    def refresh_token(self):
        if time.monotonic() - self._last_refresh < 1800:
            return None
        result = self.api.call('api/token/refashion', form={'token': self.api.token}, authenticated=False)
        self.api.token = required(result, 'token')
        self._last_refresh = time.monotonic()
        return self.api.token

    def stop(self):
        self._generation += 1
        client, self.client = self.client, None
        if client is not None:
            client.disconnect()
            client.loop_stop()
        with self.lock:
            self.connected = False
            self.pending_reads.clear()
            self.condition.notify_all()

    def start(self):
        self.stop()
        generation = self._generation
        devices = self.api.inventory()
        config = self.api.call('api/mqtt/app', params={'app_slug': APP_SLUG})
        credentials = self.api.call('api/mqtt/token', params={'app_slug': APP_SLUG})
        zones, identities, labels, topics = {}, {}, {}, {}
        boilers, boiler_ids, read_targets = {}, {}, []
        command_targets = {}
        cloud_targets = {}
        read_target_uids = {}
        user, app = required(credentials, 'user_slug'), required(credentials, 'app_code')
        client_id = f'{time.time_ns()//1_000_000}_{user}$of${app}'
        topic_config = config.get('topic')
        if not isinstance(topic_config, dict):
            raise CloudError('Invalid MQTT configuration')
        incoming, outgoing = topic_config.get('1'), topic_config.get('2')
        if not isinstance(incoming, dict) or not isinstance(outgoing, dict):
            raise CloudError('Invalid MQTT configuration')
        for number, device in enumerate(devices, 1):
            gateway = f'dispositivo_{number}'
            product, code = required(device, 'product_code'), required(device, 'device_code')
            values = {'product_code': product, 'device_code': code, 'app_client_id': client_id,
                      'app_code': app, 'user_slug': user}
            try:
                request_topic = topic_from(outgoing.get('TO_DEV'), values)
            except ValueError:
                raise CloudError('Missing or invalid read-request topic') from None
            boiler_uid = hashlib.sha256((product + ':' + code + ':boiler').encode()).hexdigest()
            boiler_ids[gateway] = boiler_uid
            boilers[boiler_uid] = {'name': 'Caldaia' if len(devices) == 1 else f'Caldaia {number}',
                                   'seen': 0.0, 'received': 0, 'values': {}, 'value_times': {}}
            children = device.get('child_devices')
            if not isinstance(children, list):
                raise CloudError('Missing zones')
            for index, child in enumerate(children, 1):
                if not isinstance(child, dict):
                    raise CloudError('Invalid zone')
                sdid = child.get('sdid')
                if not isinstance(sdid, str) or not re.fullmatch('[0-9a-fA-F]{8}', sdid):
                    raise CloudError('Invalid zone identity')
                private_key = (gateway, bytes.fromhex(sdid))
                if private_key in identities:
                    raise CloudError('Duplicate zone identities')
                uid = hashlib.sha256((product + ':' + code + ':' + sdid.lower()).encode()).hexdigest()
                alias = f'zona_{index}'
                labels[private_key] = alias
                identities[(gateway, alias)] = uid
                # Keep duplicate detection keys independent from public snapshot keys.
                identities[private_key] = uid
                name = child.get('name')
                name = ''.join(c for c in name if c.isprintable())[:100] if isinstance(name, str) else ''
                zones[uid] = {'name': name or f'Zona {index}', 'seen': 0.0, 'received': 0,
                              'values': {}, 'value_times': {}, 'mqtt_value_times': {}, 'mqtt_values': {}, 'field_sources': {}}
                read_targets.append((request_topic, bytes.fromhex(sdid)))
                read_target_uids[(request_topic, bytes.fromhex(sdid))] = uid
                command_targets[uid] = (request_topic, bytes.fromhex(sdid))
                cloud_targets[uid] = ('apps/topiot_ferroli_temperature_controller/thermostat_points/'
                                      +quote(code,safe='')+'/'+quote(sdid,safe=''))
            read_targets.append((request_topic, None))
            read_target_uids[(request_topic, None)] = boiler_uid
            for key in ('DEV_REALT', 'FROM_DEV'):
                try:
                    topics[topic_from(incoming.get(key), values)] = gateway
                except ValueError:
                    raise CloudError('Invalid MQTT topic') from None
        if not zones or not topics:
            raise CloudError('No usable zones')
        domain, port = required(config, 'domain'), config.get('ssl_port')
        if not re.fullmatch('[a-zA-Z0-9.-]+', domain) or type(port) is not int or not 1 <= port <= 65535:
            raise CloudError('Invalid MQTT endpoint')
        ready = threading.Event()
        failure = []
        pending = set()
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id,
                             clean_session=True, reconnect_on_failure=False)
        client.username_pw_set(f'{user}$of${app}', required(credentials, 'token'))
        client.tls_set_context(ssl.create_default_context())
        with self.lock:
            for uid, zone in zones.items():
                old = self.zones.get(uid)
                if old:
                    zone.update(seen=old['seen'], received=old['received'], values=old['values'],
                                value_times=old['value_times'], mqtt_value_times=old['mqtt_value_times'],
                                mqtt_values=old['mqtt_values'], field_sources=old['field_sources'])
                    for key in ('read_requests','read_replies','read_timeouts','last_cloud_result','last_query_response'):
                        if key in old:
                            zone[key] = old[key]
            self.zones, self.identities, self.labels, self.topics = zones, identities, labels, topics
            for uid, boiler in boilers.items():
                if uid in self.boilers:
                    old = self.boilers[uid]
                    boiler.update(seen=old['seen'], received=old['received'], values=old['values'],
                                  value_times=old['value_times'])
            self.boilers, self.boiler_ids, self.read_targets = boilers, boiler_ids, read_targets
            self.command_targets = command_targets
            self.cloud_targets = cloud_targets
            self.read_target_uids = read_target_uids
            self.last_poll = None
            self.last_error = None

        def on_connect(c, userdata, flags, reason, properties):
            if generation != self._generation:
                return
            if reason.is_failure:
                failure.append('mqtt_auth')
                ready.set()
                return
            result, mid = c.subscribe([(topic, 1) for topic in topics])
            if result != mqtt.MQTT_ERR_SUCCESS:
                failure.append('mqtt_subscribe')
                ready.set()
            else:
                pending.add(mid)

        def on_subscribe(c, userdata, mid, codes, properties):
            if generation != self._generation:
                return
            pending.discard(mid)
            if not codes or any(code.is_failure for code in codes):
                failure.append('mqtt_subscription_rejected')
            with self.lock:
                self.connected = not failure
            ready.set()
            self.notify()

        def on_disconnect(c, userdata, flags, reason, properties):
            if generation != self._generation:
                return
            with self.lock:
                self.connected = False
                self.last_error = 'mqtt_disconnected'
                self.condition.notify_all()
            failure.append('mqtt_disconnected')
            ready.set()
            self.notify()

        def on_message(c, userdata, message):
            if generation != self._generation:
                return
            self.receive(message.topic, message.payload, bool(message.retain))

        client.on_connect, client.on_subscribe = on_connect, on_subscribe
        client.on_disconnect, client.on_message = on_disconnect, on_message
        self.client = client
        try:
            client.connect(domain, port, keepalive=60)
            client.loop_start()
            if not ready.wait(25) or failure or pending:
                raise CloudError('MQTT connection or subscription failed')
            self.poll_readings()
        except Exception as exc:
            self.stop()
            if isinstance(exc, CloudError):
                raise
            raise CloudError('MQTT TLS connection failed') from None

    def poll_readings(self):
        """Executor-only. Fixed read-only queries after SUBACK and every 120 s."""
        now = time.monotonic()
        with self.lock:
            if not self.connected or (self.last_poll is not None and now-self.last_poll < 120):
                return
            self.last_poll = now  # Failed sends are also throttled; never retry every tick.
            targets, client, generation = list(self.read_targets), self.client, self._generation
        for topic, thermostat_id in targets:
            if generation != self._generation:
                return
            uid = self.read_target_uids[(topic, thermostat_id)]
            collection = self.zones if thermostat_id is not None else self.boilers
            sent_at = time.monotonic()
            sequence = self.next_sequence()
            payload = build_read_query(thermostat_id, sequence)
            with self.lock:
                self.pending_reads[uid] = (sequence, sent_at)
            try:
                info = client.publish(topic, payload=payload, qos=1, retain=False)
                if info.rc != mqtt.MQTT_ERR_SUCCESS:
                    raise CloudError('Read request publish rejected')
                info.wait_for_publish(timeout=5)
                if not info.is_published():
                    raise CloudError('Read request delivery timeout')
            except Exception:
                with self.lock:
                    self.publish_errors += 1
                    self.last_error = 'read_request_failed'
                    self.pending_reads.pop(uid, None)
                continue  # One failed target must not prevent reading the other zone.
            with self.lock:
                self.queries_sent += 1
                collection[uid]['read_requests'] = collection[uid].get('read_requests', 0)+1
            # The app requests one selected zone at a time. Do not publish the
            # whole multi-zone batch back-to-back after broker acknowledgements.
            with self.condition:
                replied = self.condition.wait_for(
                    lambda: collection[uid].get('last_query_response', 0) >= sent_at
                    or not self.connected or generation != self._generation,
                    timeout=self.read_reply_timeout)
                if not replied:
                    collection[uid]['read_timeouts'] = collection[uid].get('read_timeouts', 0)+1
                self.pending_reads.pop(uid, None)
            if not self.connected or generation != self._generation:
                return
        self.read_cloud_snapshots()

    def read_cloud_snapshots(self):
        """Read each zone's points, just as the app does. Never refresh old cache."""
        for uid, path in list(self.cloud_targets.items()):
            try:
                points = self.api.call(path)
                timestamp_ms, values = decode_cloud_points(points)
                age = time.time()-timestamp_ms/1000
                if timestamp_ms < 946684800000 or age < -30 or age >= STALE_SECONDS:
                    with self.lock:
                        self.cloud_stale += 1
                        if uid in self.zones:
                            self.zones[uid]['last_cloud_result'] = 'stale_or_invalid_timestamp'
                    continue
                observed_at = time.monotonic()-max(0, age)
                with self.lock:
                    zone = self.zones.get(uid)
                    if zone is None:
                        continue
                    self.cloud_reads += 1
                    zone['last_cloud_result'] = 'ok' if values else 'no_recognized_fields'
                    for key, value in values.items():
                        if observed_at > zone['value_times'].get(key, float('-inf')):
                            zone['values'][key] = value
                            zone['value_times'][key] = observed_at
                            zone['field_sources'][key] = 'cloud_snapshot'
            except AuthError:
                raise
            except (CloudError, ValueError, TypeError) as exc:
                with self.lock:
                    self.cloud_errors += 1
                    if uid in self.zones:
                        status = re.fullmatch(r'HTTP ([0-9]{3})',str(exc))
                        self.zones[uid]['last_cloud_result'] = (
                            'http_'+status[1] if status else
                            'missing_snapshot_timestamp' if str(exc)=='Missing cloud snapshot timestamp' else
                            'request_or_format_error')
        self.notify()

    def next_sequence(self):
        with self.lock:
            self.message_sequence = (self.message_sequence+1) % 256
            return self.message_sequence

    def write_zone(self, uid, *, temperature=None, mode=None, timeout=20):
        """Executor-only. Send once, then require fresh zone-specific telemetry."""
        with self.command_lock:
            with self.lock:
                zone = self.zones.get(uid)
                if not self.connected or zone is None or uid not in self.command_targets:
                    raise CloudError('Zona non collegata')
                now = time.monotonic()
                def fresh(key):
                    return key in zone['values'] and key in zone['value_times'] and now-zone['value_times'][key] < STALE_SECONDS
                if not fresh('modalita'):
                    raise CloudError('Attendi la lettura aggiornata della modalità')
                if mode is not None and (type(mode) is not int or mode not in (0, 1, 4)):
                    raise CloudError('Modalità non supportata')
                expected = {}
                current = zone['values']['modalita']
                target_mode = mode if mode is not None else {'automatico': 0, 'manuale': 1, 'spento': 4}.get(current)
                temporary = False
                if mode is not None:
                    expected['modalita'] = {0: 'automatico', 1: 'manuale', 4: 'spento'}[mode]
                    if mode == 0 and temperature is None:
                        expected['override_attivo'] = False
                if temperature is not None:
                    if not fresh('unita_temperatura') or zone['values']['unita_temperatura'] != 0:
                        raise CloudError('Scrittura disponibile solo con unità Celsius confermata')
                    if not fresh('limite_minimo') or not fresh('limite_massimo'):
                        raise CloudError('Attendi i limiti di temperatura del termostato')
                    low, high = zone['values']['limite_minimo'], zone['values']['limite_massimo']
                    if not valid_temperature_limits(low, high):
                        raise CloudError('Limiti di temperatura non validi: attendi una lettura aggiornata')
                    if (type(temperature) not in (int, float) or not math.isfinite(temperature)
                        or not low <= temperature <= high or abs(temperature*2-round(temperature*2)) > 0.00001):
                        raise CloudError('Temperatura fuori dai limiti o dal passo di 0,5 °C')
                    if target_mode not in (0, 1):
                        raise CloudError('Seleziona Manuale o Automatico prima di impostare la temperatura')
                    temporary = target_mode == 0
                    expected['temperatura_temporanea' if temporary else 'temperatura_manuale'] = float(temperature)
                    if temporary:
                        expected['override_attivo'] = True
                if not expected:
                    raise CloudError('Nessuna modifica richiesta')
                topic, thermostat_id = self.command_targets[uid]
                client, generation = self.client, self._generation
            payload = build_zone_control(thermostat_id, self.next_sequence(), mode=mode,
                                         temperature=temperature, temporary=temporary)
            sent_at = time.monotonic()
            try:
                # QoS 0 prevents replay of a control after a reconnect. The
                # application-level response, not PUBACK, establishes success.
                info = client.publish(topic, payload=payload, qos=0, retain=False)
                if info.rc != mqtt.MQTT_ERR_SUCCESS:
                    raise CloudError('Invio comando non riuscito')
                info.wait_for_publish(timeout=5)
                if not info.is_published():
                    raise CloudError('Consegna comando non confermata')
                with self.lock:
                    self.commands_sent += 1
                # Separate verification query; never resend the control itself.
                query = build_read_query(thermostat_id, self.next_sequence())
                query_info = client.publish(topic, payload=query, qos=1, retain=False)
                if query_info.rc == mqtt.MQTT_ERR_SUCCESS:
                    with self.lock:
                        self.queries_sent += 1
            except Exception:
                with self.lock:
                    self.commands_unconfirmed += 1
                raise CloudError('Invio non confermato: verifica lo stato nell’app prima di riprovare') from None

            def confirmed():
                state = self.zones.get(uid)
                return bool(state and all(state['mqtt_values'].get(key) == value
                            and state['mqtt_value_times'].get(key, 0) >= sent_at for key, value in expected.items()))
            with self.condition:
                self.condition.wait_for(lambda: confirmed() or not self.connected or generation != self._generation,
                                        timeout=timeout)
                if self.connected and generation == self._generation and confirmed():
                    self.commands_confirmed += 1
                    return
                self.commands_unconfirmed += 1
            raise CloudError('Il dispositivo non ha confermato la modifica: verifica nell’app, potrebbe essere stata applicata')

    def receive(self, topic, payload, retained=False):
        gateway = self.topics.get(topic)
        if gateway is None:
            return
        with self.lock:
            self.received += 1
            if len(payload) > 65536:
                self.invalid += 1
                return
            try:
                decoded = decode_frame(payload, self.labels, gateway, inventory=True)
            except ValueError:
                self.invalid += 1
                return
            # Do not interpret echoed QUERY placeholders as live measurements.
            if decoded['tipo'] not in (3, 0x1004):
                self.unassigned += 1
                return
            uid = self.identities.get((gateway, decoded.get('zona')))
            boiler_uid = self.boiler_ids.get(gateway) if decoded.get('caldaia') else None
            if uid is None and boiler_uid is None:
                self.unassigned += 1
                return
            zone = self.zones[uid] if uid is not None else self.boilers[boiler_uid]
            zone['received'] += 1
            # Retained frames may predate the current state. Never replace a
            # newer live value or mark an entity available on this evidence.
            if retained:
                return
            zone['seen'] = time.monotonic()
            pending = self.pending_reads.get(uid if uid is not None else boiler_uid)
            if decoded['tipo'] == 3 and pending and decoded['message_id'] == pending[0]:
                zone['last_query_response'] = zone['seen']
                zone['read_replies'] = zone.get('read_replies', 0)+1
            for field in decoded['campi']:
                if 'nome' in field and 'valore' in field:
                    if boiler_uid is not None and field['nome'] not in {
                        'rele_caldaia', 'caldaia_accesa', 'collegamento_caldaia', 'opentherm_connesso'}:
                        continue
                    zone['values'][field['nome']] = field['valore']
                    zone['value_times'][field['nome']] = time.monotonic()
                    if uid is not None:
                        zone['mqtt_value_times'][field['nome']] = zone['value_times'][field['nome']]
                        zone['mqtt_values'][field['nome']] = field['valore']
                        zone['field_sources'][field['nome']] = 'mqtt'
            self.condition.notify_all()
        self.notify()

# Public application identifier from Android initServer; not a user secret.
APP_SLUG = 'd970e7bd-35f6-46ee-8943-c32c77bc67aa'
