import json
import struct
import types
import unittest

import test_client as fixtures

module = fixtures.module


class CommandTests(unittest.TestCase):
    setUp = fixtures.ClientTests.setUp
    tearDown = fixtures.ClientTests.tearDown

    def prepare_zone(self, mode=1):
        fields=[(0x0017,b'ABCD'),(0x1000,struct.pack('>h',210)),(0x1010,struct.pack('>h',210)),
                (0x100F,bytes([mode])),(0x100B,b'\x00'),(0x1002,struct.pack('>h',300)),
                (0x1003,struct.pack('>h',50)),(0x1012,b'\x00')]
        payload=struct.pack('>HBBBqqB',3,19,1,100,0,0,12)
        payload+=b''.join(struct.pack('>HH',flag,len(value))+value for flag,value in fields)
        self.client.receive(self.topic,payload)
        return self.client.identities[('dispositivo_1',b'ABCD')]

    def acknowledge_controls(self, wrong_zone=False):
        mqtt=self.client.client
        original=mqtt.publish
        def publish(topic,payload,qos,retain):
            info=original(topic,payload,qos,retain)
            if payload[:2]==b'\x00\x02':
                response=b'\x00\x03'+payload[2:]
                if wrong_zone: response=response[:-4]+b'EFGH'
                self.client.receive(self.topic,response)
            return info
        mqtt.publish=publish

    def test_manual_command_confirmed_only_from_device_data(self):
        uid=self.prepare_zone()
        self.acknowledge_controls()
        self.client.write_zone(uid,temperature=20,timeout=0)
        self.assertEqual(self.client.snapshot()['zones'][uid]['values']['temperatura_manuale'],20)
        self.assertEqual(self.client.diagnostics()['commands_confirmed'],1)
        writes=[p for p in self.client.client.published if p[1][:2]==b'\x00\x02']
        self.assertEqual(len(writes),1)
        self.assertEqual(writes[0][2:],(0,False))
        self.assertEqual(writes[0][1][-4:],b'ABCD')

    def test_automatic_temperature_is_temporary_override(self):
        uid=self.prepare_zone(mode=0)
        self.acknowledge_controls()
        self.client.write_zone(uid,temperature=22.5,timeout=0)
        values=self.client.snapshot()['zones'][uid]['values']
        self.assertEqual(values['modalita'],'automatico')
        self.assertTrue(values['override_attivo'])
        self.assertEqual(values['temperatura_temporanea'],22.5)
        self.assertEqual(values['temperatura_manuale'],21)

    def test_mode_change_and_return_to_schedule(self):
        uid=self.prepare_zone()
        self.acknowledge_controls()
        self.client.write_zone(uid,mode=0,timeout=0)
        values=self.client.snapshot()['zones'][uid]['values']
        self.assertEqual(values['modalita'],'automatico')
        self.assertFalse(values['override_attivo'])
        self.client.write_zone(uid,mode=4,timeout=0)
        self.assertEqual(self.client.snapshot()['zones'][uid]['values']['modalita'],'spento')

    def test_other_zone_cannot_confirm_command(self):
        uid=self.prepare_zone()
        self.acknowledge_controls(wrong_zone=True)
        with self.assertRaises(module.CloudError): self.client.write_zone(uid,temperature=20,timeout=0)
        self.assertEqual(self.client.snapshot()['zones'][uid]['values']['temperatura_manuale'],21)
        self.assertEqual(self.client.diagnostics()['commands_confirmed'],0)

    def test_mqtt_delivery_is_not_confirmation_and_no_automatic_retry(self):
        uid=self.prepare_zone()
        with self.assertRaises(module.CloudError): self.client.write_zone(uid,temperature=21,timeout=0)
        writes=[p for p in self.client.client.published if p[1][:2]==b'\x00\x02']
        self.assertEqual(len(writes),1)
        self.assertEqual(self.client.diagnostics()['commands_unconfirmed'],1)
        self.assertEqual(self.client.diagnostics()['commands_confirmed'],0)

    def test_invalid_inputs_do_not_publish_controls(self):
        uid=self.prepare_zone()
        for args in [{'temperature':float('nan')},{'temperature':31},{'temperature':4.5},
                     {'temperature':20.1},{'temperature':True},{'mode':2},{'mode':True}]:
            with self.subTest(args=args),self.assertRaises(module.CloudError):
                self.client.write_zone(uid,timeout=0,**args)
        self.assertFalse(any(p[1][:2]==b'\x00\x02' for p in self.client.client.published))

    def test_missing_limits_fahrenheit_stale_mode_or_boiler_uid_rejected(self):
        uid=self.prepare_zone()
        zone=self.client.zones[uid]
        zone['value_times'].pop('limite_minimo')
        with self.assertRaises(module.CloudError): self.client.write_zone(uid,temperature=20,timeout=0)
        zone['values']['unita_temperatura']=1
        with self.assertRaises(module.CloudError): self.client.write_zone(uid,temperature=20,timeout=0)
        zone['value_times']['modalita']=0
        with self.assertRaises(module.CloudError): self.client.write_zone(uid,mode=1,timeout=0)
        boiler_uid=next(iter(self.client.boilers))
        with self.assertRaises(module.CloudError): self.client.write_zone(boiler_uid,mode=1,timeout=0)

    def test_explicit_manual_mode_and_temperature_can_be_atomic(self):
        uid=self.prepare_zone(mode=4)
        self.acknowledge_controls()
        self.client.write_zone(uid,mode=1,temperature=20,timeout=0)
        values=self.client.snapshot()['zones'][uid]['values']
        self.assertEqual(values['modalita'],'manuale')
        self.assertEqual(values['temperatura_manuale'],20)
        self.assertNotIn('PRIVATE',json.dumps(self.client.diagnostics()))
