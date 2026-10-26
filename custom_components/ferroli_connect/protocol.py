"""Topband packet decoder validated against Connect 1.5.2 and live zone telemetry."""
import re
import struct
import time
import math

ProbeError = ValueError

def topic_from(template, values):
    if not isinstance(template, str) or not template:
        raise ProbeError('Modello topic MQTT assente.')
    for key, value in values.items():
        if not isinstance(value, str) or not value or any(c in value for c in '/+#{}\x00'):
            raise ProbeError('Identificativo MQTT non valido.')
        template = template.replace('{' + key + '}', value)
    if any(c in template for c in '{}+#\x00') or len(template.encode()) > 65535:
        raise ProbeError('Topic MQTT inatteso: richiesti topic specifici senza wildcard.')
    return template

TEMPERATURES = {0x1000: 'temperatura_ambiente', 0x1001: 'setpoint',
                0x1002: 'limite_massimo', 0x1003: 'limite_minimo', 0x1013: 'temperatura_temporanea',
                0x1004: 'comfort', 0x1005: 'economy', 0x1006: 'antigelo',
                0x1010: 'temperatura_manuale', 0x2000: 'temperatura_mandata',
                0x2002: 'temperatura_sanitario', 0x2003: 'setpoint_sanitario'}

BOOLEANS = {0x0013: 'batteria_scarica', 0x1009: 'riscaldamento_attivo',
            0x1012: 'override_attivo',
            0x100A: 'rele_termostato', 0x2010: 'opentherm_connesso', 0x201A: 'fiamma'}

MODES = {0: 'automatico', 1: 'manuale', 2: 'assenza', 3: 'party', 4: 'spento', 5: 'sanitario'}

# Request values are placeholders, as in MessageDataBuilder.query() in the app.
# No control/delete packet builder or arbitrary outgoing field API is exposed.
ZONE_READ_FIELDS = ((0x0013, 1), (0x1000, 2), (0x1001, 2), (0x1004, 2),
                    (0x1005, 2), (0x1006, 2), (0x1009, 1), (0x100B, 1),
                    (0x100F, 1), (0x1010, 2), (0x1002, 2), (0x1003, 2),
                    (0x1012, 1), (0x1013, 2))
BOILER_READ_FIELDS = ((0x2011, 1), (0x200F, 1), (0x2010, 1))
BOILER_MARKER = bytes.fromhex('5555aaaa')

CLOUD_ZONE_FIELDS = {
    'flagBatteryState': (0x0013, 1), 'roomCurrentTemp': (0x1000, 2),
    'roomTargetTemp': (0x1001, 2), 'roomTargetTempMax': (0x1002, 2),
    'roomTargetTempMin': (0x1003, 2), 'roomComfortTemp': (0x1004, 2),
    'roomEconTemp': (0x1005, 2), 'roomFrostTemp': (0x1006, 2),
    'roomHeatStatus': (0x1009, 1), 'roomTempUnit': (0x100B, 1),
    'roomWorkMode': (0x100F, 1), 'roomManualTemp': (0x1010, 2),
    'roomOverrideState': (0x1012, 1), 'roomOverrideTemp': (0x1013, 2)}


def decode_cloud_points(points):
    """Hex-encoded values used by TemperatureMessage in the official app."""
    raw_timestamp = points.get('utcMilliseconds')
    if not isinstance(raw_timestamp, str) or not re.fullmatch('[0-9a-fA-F]{1,16}', raw_timestamp):
        raise ValueError('Missing cloud snapshot timestamp')
    timestamp_ms = int(raw_timestamp, 16)
    fields = []
    for key, (flag, size) in CLOUD_ZONE_FIELDS.items():
        raw = points.get(key)
        if not isinstance(raw, str) or not re.fullmatch('[0-9a-fA-F]{'+str(size*2)+'}', raw):
            continue
        fields.append(struct.pack('>HH', flag, size)+bytes.fromhex(raw))
    header = struct.pack('>HBBBqqB', 3, 19, 0, 100, 0, 0, 12)
    decoded = decode_frame(header+b''.join(fields))
    return timestamp_ms, {f['nome']: f['valore'] for f in decoded['campi'] if 'nome' in f}


def build_read_query(thermostat_id, message_id, *, now_ms=None, offset_hours=None):
    """Build only packet type 1 (query). None addresses the boiler marker."""
    if thermostat_id is not None and (not isinstance(thermostat_id, bytes) or len(thermostat_id) != 4):
        raise ValueError('Invalid thermostat identity')
    if type(message_id) is not int or not 0 <= message_id <= 255:
        raise ValueError('Invalid message sequence')
    now_ms = int(time.time()*1000) if now_ms is None else now_ms
    offset_hours = -time.timezone//3600 if offset_hours is None else offset_hours
    if type(now_ms) is not int or not 0 <= now_ms < 2**63 or not -12 <= offset_hours <= 14:
        raise ValueError('Invalid query timestamp')
    fields = ZONE_READ_FIELDS if thermostat_id is not None else BOILER_READ_FIELDS
    header = struct.pack('>HBBBqqB', 1, 19, message_id, 1, 0, now_ms, offset_hours+12)
    data = b''.join(struct.pack('>HH', flag, size) + bytes(size) for flag, size in fields)
    marker_flag, marker = (0x0017, thermostat_id) if thermostat_id is not None else (0x2024, BOILER_MARKER)
    return header + data + struct.pack('>HH', marker_flag, 4) + marker


def build_zone_control(thermostat_id, message_id, *, mode=None, temperature=None, temporary=False):
    """Only zone mode, manual temperature or temporary override; no boiler controls."""
    if not isinstance(thermostat_id, bytes) or len(thermostat_id) != 4:
        raise ValueError('Invalid thermostat identity')
    fields = []
    if mode is not None:
        if type(mode) is not int or mode not in (0, 1, 4):
            raise ValueError('Unsupported mode')
        fields.append((0x100F, bytes([mode])))
        if mode == 0 and temperature is None:
            fields.append((0x1012, b'\x00'))  # Explicit Auto returns to the program.
    if temperature is not None:
        if type(temperature) not in (float, int) or not math.isfinite(temperature):
            raise ValueError('Invalid temperature')
        scaled = round(temperature*10)
        if not -32768 <= scaled <= 32767 or abs(scaled-temperature*10) > 0.00001:
            raise ValueError('Unsupported temperature precision')
        if temporary:
            if mode not in (None, 0):
                raise ValueError('Temporary temperature requires automatic mode')
            fields.extend(((0x1012, b'\x01'), (0x1013, struct.pack('>h', scaled))))
        else:
            if mode not in (None, 1):
                raise ValueError('Manual temperature requires manual mode')
            fields.append((0x1010, struct.pack('>h', scaled)))
    if not fields:
        raise ValueError('Empty command')
    # Reuse the verified header encoder, changing only the packet type to CONTROL.
    header = bytearray(build_read_query(thermostat_id, message_id)[:22])
    header[:2] = struct.pack('>H', 2)
    data = b''.join(struct.pack('>HH', flag, len(value))+value for flag, value in fields)
    return bytes(header)+data+struct.pack('>HH', 0x0017, 4)+thermostat_id

def decode_frame(payload, zone_labels=None, gateway='dispositivo_1', *, inventory=False):
    """TLV Topband: intestazione variabile, tipo/lunghezza a 16 bit big endian."""
    if len(payload) < 22:
        raise ValueError('Intestazione incompleta')
    offset = 3 + payload[2]
    if offset < 22 or offset > len(payload):
        raise ValueError('Lunghezza intestazione non valida')
    fields = []
    while offset < len(payload):
        if offset + 4 > len(payload):
            raise ValueError('Campo troncato')
        flag, size = struct.unpack_from('>HH', payload, offset)
        offset += 4
        if size > len(payload) - offset:
            raise ValueError('Valore troncato')
        fields.append((flag, payload[offset:offset+size]))
        offset += size
    # Si completa prima la validazione per evitare di registrare frame parziali.
    result = []
    for flag, raw in fields:
        item = {'campo': f'0x{flag:04X}', 'byte': len(raw)}
        if flag in TEMPERATURES and len(raw) == 2:
            item.update(nome=TEMPERATURES[flag], valore=int.from_bytes(raw, 'big', signed=True)/10)
        elif flag in BOOLEANS and len(raw) == 1 and raw[0] in (0, 1):
            item.update(nome=BOOLEANS[flag], valore=bool(raw[0]))
        elif flag == 0x100B and len(raw) == 1:
            item.update(nome='unita_temperatura', valore=raw[0])
        elif flag == 0x100F and len(raw) == 1:
            item.update(nome='modalita', valore=MODES.get(raw[0], 'sconosciuta'))
        elif flag == 0x2011 and len(raw) == 1 and raw[0] in (1, 2, 16):
            item.update(nome='rele_caldaia', valore=raw[0] in (1, 16))
            # SwitchBoilerActivity.setSwitchImg: code 1 = OFF, code 2 = ON.
            # Preserve the previous raw-contact sensor without inverting automations.
            result.append({'campo': f'0x{flag:04X}', 'byte': 1,
                           'nome': 'caldaia_accesa', 'valore': raw[0] == 2})
        elif flag == 0x200F and len(raw) == 1 and raw[0] in (0, 1):
            item.update(nome='collegamento_caldaia', valore='opentherm' if raw[0] else 'on_off')
        result.append(item)
    decoded = {'tipo': struct.unpack_from('>H', payload)[0], 'message_id': payload[3],
               'versione': payload[4], 'campi': result}
    boiler_markers = [raw for flag, raw in fields if flag == 0x2024]
    decoded['caldaia'] = (bool(boiler_markers) and all(len(raw) == 4 for raw in boiler_markers)
                          and not any(flag == 0x0017 for flag, _ in fields))
    if zone_labels is not None:
        # L'ID può comparire dopo i valori. Non dedurre la zona da temperatura,
        # ordine dei pacchetti o dall'ultima zona ricevuta.
        ids = {raw for flag, raw in fields if flag == 0x0017 and len(raw) == 4}
        malformed = any(flag == 0x0017 and len(raw) != 4 for flag, raw in fields)
        if len(ids) == 1 and not malformed:
            key = (gateway, next(iter(ids)))
            if key not in zone_labels:
                prefix = 'non_censita_' if inventory else 'zona_'
                number = 1 + sum(g == gateway and label.startswith(prefix)
                                 for (g, _), label in zone_labels.items())
                zone_labels[key] = f'{prefix}{number}'
            decoded['zona'] = zone_labels[key]
            if inventory:
                decoded['corrispondenza_cloud'] = re.fullmatch(r'zona_[1-9][0-9]*', decoded['zona']) is not None
        else:
            decoded['zona'] = 'ambigua' if len(ids) > 1 else 'non_identificata'
    return decoded
