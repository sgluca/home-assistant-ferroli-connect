"""Cloud transport. All methods run outside the HA event loop."""
from __future__ import annotations

import hashlib
import json
import re
import ssl
import threading
import time
from copy import deepcopy
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler

import paho.mqtt.client as mqtt

from .protocol import decode_frame, topic_from

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
        if not path.startswith('api/') or '..' in path or '://' in path:
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
    def __init__(self, token, notify):
        self.api = Api(token)
        self.notify = notify
        self.lock = threading.Lock()
        self.zones = {}
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
            return {'connected': self.connected, 'zones': deepcopy(self.zones)}

    def diagnostics(self):
        with self.lock:
            return {'connected': self.connected, 'received': self.received, 'invalid_frames': self.invalid,
                    'unassigned_frames': self.unassigned, 'zone_count': len(self.zones),
                    'last_error': self.last_error,
                    'zones': [{'alias': f'zone_{i}', 'received': z['received'],
                               'age_seconds': round(time.monotonic()-z['seen']) if z['seen'] else None}
                              for i, z in enumerate(self.zones.values(), 1)]}

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

    def start(self):
        self.stop()
        generation = self._generation
        devices = self.api.inventory()
        config = self.api.call('api/mqtt/app', params={'app_slug': APP_SLUG})
        credentials = self.api.call('api/mqtt/token', params={'app_slug': APP_SLUG})
        zones, identities, labels, topics = {}, {}, {}, {}
        user, app = required(credentials, 'user_slug'), required(credentials, 'app_code')
        client_id = f'{time.time_ns()//1_000_000}_{user}$of${app}'
        incoming = config.get('topic', {}).get('1', {})
        if not isinstance(incoming, dict):
            raise CloudError('Invalid MQTT configuration')
        for number, device in enumerate(devices, 1):
            gateway = f'dispositivo_{number}'
            product, code = required(device, 'product_code'), required(device, 'device_code')
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
                              'values': {}, 'value_times': {}}
            values = {'product_code': product, 'device_code': code, 'app_client_id': client_id,
                      'app_code': app, 'user_slug': user}
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
                                value_times=old['value_times'])
            self.zones, self.identities, self.labels, self.topics = zones, identities, labels, topics
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
        except Exception as exc:
            self.stop()
            if isinstance(exc, CloudError):
                raise
            raise CloudError('MQTT TLS connection failed') from None

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
            uid = self.identities.get((gateway, decoded.get('zona')))
            if uid is None:
                self.unassigned += 1
                return
            zone = self.zones[uid]
            zone['received'] += 1
            # Retained frames may predate the current state. Never replace a
            # newer live value or mark an entity available on this evidence.
            if retained:
                return
            zone['seen'] = time.monotonic()
            for field in decoded['campi']:
                if 'nome' in field and 'valore' in field:
                    zone['values'][field['nome']] = field['valore']
                    zone['value_times'][field['nome']] = time.monotonic()
        self.notify()

# Public application identifier from Android initServer; not a user secret.
APP_SLUG = 'd970e7bd-35f6-46ee-8943-c32c77bc67aa'
