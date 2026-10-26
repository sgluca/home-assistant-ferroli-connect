"""Topband packet decoder validated against Connect 1.5.2 and live zone telemetry."""
import re
import struct

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
                0x1004: 'comfort', 0x1005: 'economy', 0x1006: 'antigelo',
                0x1010: 'temperatura_manuale', 0x2000: 'temperatura_mandata',
                0x2002: 'temperatura_sanitario', 0x2003: 'setpoint_sanitario'}

BOOLEANS = {0x0013: 'batteria_scarica', 0x1009: 'riscaldamento_attivo',
            0x100A: 'rele_termostato', 0x2010: 'opentherm_connesso', 0x201A: 'fiamma'}

MODES = {0: 'automatico', 1: 'manuale', 2: 'assenza', 3: 'party', 4: 'spento', 5: 'sanitario'}

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
        result.append(item)
    decoded = {'tipo': struct.unpack_from('>H', payload)[0], 'versione': payload[4], 'campi': result}
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
