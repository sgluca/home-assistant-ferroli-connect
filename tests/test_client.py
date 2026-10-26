import importlib
import json
from pathlib import Path
import struct
import sys
import types
import unittest
import asyncio
import io
import threading
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
package=types.ModuleType('ferroli_under_test')
package.__path__=[str(ROOT / 'custom_components/ferroli_connect')]
sys.modules['ferroli_under_test']=package
module=importlib.import_module('ferroli_under_test.client')

def frame(identity=None, value=210, flag=0x1000):
    raw=struct.pack('>HBBBqqB',3,19,1,100,0,0,12)
    if identity is not None:
        raw+=struct.pack('>HH',0x17,len(identity))+identity
    return raw+struct.pack('>HHh',flag,2,value)

ok=types.SimpleNamespace(is_failure=False)

class FakeMqtt:
    def __init__(self): self.published=[]
    def username_pw_set(self,*args): pass
    def tls_set_context(self,*args): pass
    def connect(self,*args,**kwargs): pass
    def subscribe(self,topics): return 0,1
    def loop_start(self):
        self.on_connect(self,None,None,ok,None)
        self.on_subscribe(self,None,1,[ok,ok],None)
    def disconnect(self): pass
    def loop_stop(self): pass
    def publish(self,topic,payload,qos,retain):
        self.published.append((topic,payload,qos,retain))
        return types.SimpleNamespace(rc=0,wait_for_publish=lambda timeout:None,is_published=lambda:True)

class FakeApi:
    def inventory(self):
        return [{'product_code':'PRIVATE-product','device_code':'PRIVATE-device','child_devices':[
            {'name':'PRIVATE-room1','sdid':'41424344'},
            {'name':'PRIVATE-room2','sdid':'45464748'}]}]
    def call(self,path,**kwargs):
        if path=='api/mqtt/app':
            return {'domain':'example.invalid','ssl_port':8883,'topic':{'1':{
                'DEV_REALT':'/state/{product_code}/{device_code}',
                'FROM_DEV':'/response/{product_code}/{device_code}/{app_client_id}'},
                '2':{'TO_DEV':'/request/{product_code}/{device_code}/{app_client_id}'}}}
        return {'user_slug':'PRIVATE-user','app_code':'PRIVATE-app','token':'PRIVATE-token'}

class ClientTests(unittest.TestCase):
    def setUp(self):
        self.client=module.Client('PRIVATE-http-token',lambda:None)
        self.client.api=FakeApi()
        with patch.object(module.mqtt,'Client',return_value=FakeMqtt()):
            self.client.start()
        self.topic=next(iter(self.client.topics))

    def tearDown(self): self.client.stop()

    def test_live_zones_and_diagnostics_privacy(self):
        self.client.receive(self.topic,frame(b'EFGH',214))
        self.client.receive(self.topic,frame(b'ABCD',210))
        self.client.receive(self.topic,frame(b'ABCD',200,0x1010))
        zones=list(self.client.snapshot()['zones'].values())
        self.assertEqual(zones[0]['values']['temperatura_ambiente'],21)
        self.assertEqual(zones[1]['values']['temperatura_ambiente'],21.4)
        self.assertNotIn('temperatura_manuale',zones[1]['values'])
        diagnostics=json.dumps(self.client.diagnostics())
        self.assertNotIn('PRIVATE',diagnostics)
        self.assertNotIn('41424344',diagnostics)
        self.assertNotIn('ABCD',diagnostics)

    def test_unknown_missing_truncated_frames_do_not_update_zone(self):
        for payload in [frame(b'WXYZ'),frame(),frame(b'ABCD')[:-1]]:
            self.client.receive(self.topic,payload)
        self.assertEqual(self.client.diagnostics()['unassigned_frames'],2)
        self.assertEqual(self.client.diagnostics()['invalid_frames'],1)
        self.assertTrue(all(not z['values'] for z in self.client.snapshot()['zones'].values()))

    def test_retained_does_not_replace_live_reading(self):
        self.client.receive(self.topic,frame(b'ABCD',210))
        self.client.receive(self.topic,frame(b'ABCD',999),retained=True)
        zone=list(self.client.snapshot()['zones'].values())[0]
        self.assertEqual(zone['values']['temperatura_ambiente'],21)

    def test_partial_update_does_not_refresh_other_values(self):
        with patch.object(module.time,'monotonic',return_value=10):
            self.client.receive(self.topic,frame(b'ABCD',210))
        with patch.object(module.time,'monotonic',return_value=900):
            self.client.receive(self.topic,frame(b'ABCD',200,0x1010))
        zone=list(self.client.snapshot()['zones'].values())[0]
        self.assertEqual(zone['value_times']['temperatura_ambiente'],10)
        self.assertEqual(zone['value_times']['temperatura_manuale'],900)

    def test_stable_uid_when_cloud_order_changes(self):
        before=set(self.client.snapshot()['zones'])
        api=FakeApi()
        original=api.inventory
        api.inventory=lambda:[{**original()[0],'child_devices':list(reversed(original()[0]['child_devices']))}]
        self.client.api=api
        with patch.object(module.mqtt,'Client',return_value=FakeMqtt()): self.client.start()
        self.assertEqual(before,set(self.client.snapshot()['zones']))

    def test_duplicate_sdid_rejected(self):
        api=FakeApi()
        original=api.inventory
        api.inventory=lambda:[{**original()[0],'child_devices':[original()[0]['child_devices'][0]]*2}]
        self.client.api=api
        with self.assertRaises(module.CloudError): self.client.start()

    def test_start_queries_both_zones_and_boiler_after_subscription(self):
        published=self.client.client.published
        self.assertEqual(len(published),3)
        ids=[]
        for topic,payload,qos,retain in published:
            self.assertEqual(payload[:2],b'\x00\x01')
            self.assertEqual(qos,1)
            self.assertFalse(retain)
            self.assertTrue(topic.startswith('/request/'))
            ids.append(payload[-4:])
        self.assertEqual(ids,[b'ABCD',b'EFGH',bytes.fromhex('5555aaaa')])

    def test_poll_interval_and_reconnection(self):
        sent=self.client.diagnostics()['read_queries_sent']
        # Fixed representable clock values avoid platform-specific float rounding
        # at exactly 120 seconds on Linux vs Windows monotonic clocks.
        self.client.last_poll=100.0
        last=100.0
        with patch.object(module.time,'monotonic',return_value=last+119): self.client.poll_readings()
        self.assertEqual(self.client.diagnostics()['read_queries_sent'],sent)
        with patch.object(module.time,'monotonic',return_value=last+120): self.client.poll_readings()
        self.assertEqual(self.client.diagnostics()['read_queries_sent'],sent+3)
        self.client.stop()
        self.client.poll_readings()
        self.assertEqual(self.client.diagnostics()['read_queries_sent'],sent+3)
        with patch.object(module.mqtt,'Client',return_value=FakeMqtt()): self.client.start()
        self.assertEqual(self.client.diagnostics()['read_queries_sent'],sent+6)

    def test_failed_publish_is_throttled_and_not_counted_as_state(self):
        self.client.last_poll=None
        self.client.client.publish=lambda *a,**kw:types.SimpleNamespace(rc=1)
        with self.assertRaises(module.CloudError): self.client.poll_readings()
        self.assertEqual(self.client.diagnostics()['read_publish_errors'],1)
        self.client.poll_readings()
        self.assertEqual(self.client.diagnostics()['read_publish_errors'],1)
        self.assertTrue(all(not z['seen'] for z in self.client.snapshot()['zones'].values()))

    def test_boiler_packets_do_not_change_zone_state(self):
        payload=struct.pack('>HBBBqqB',4100,19,1,100,0,0,12)
        payload+=struct.pack('>HHB',0x2011,1,16)
        payload+=struct.pack('>HHB',0x200F,1,0)
        payload+=struct.pack('>HH',0x2024,4)+bytes.fromhex('5555aaaa')
        self.client.receive(self.topic,payload)
        snapshot=self.client.snapshot()
        boiler=next(iter(snapshot['boilers'].values()))
        self.assertTrue(boiler['values']['rele_caldaia'])
        self.assertEqual(boiler['values']['collegamento_caldaia'],'on_off')
        self.assertTrue(all(not z['values'] for z in snapshot['zones'].values()))
        self.assertNotIn('5555aaaa',json.dumps(self.client.diagnostics()))

    def test_ambiguous_packet_not_attributed_to_boiler(self):
        payload=frame(b'ABCD')+struct.pack('>HH',0x2024,4)+bytes.fromhex('5555aaaa')
        self.client.receive(self.topic,payload)
        self.assertTrue(all(not b['values'] for b in self.client.snapshot()['boilers'].values()))

    def test_echoed_read_query_is_not_a_zero_temperature_response(self):
        self.client.receive(self.topic,module.build_read_query(b'ABCD',1))
        self.assertTrue(all(not z['values'] for z in self.client.snapshot()['zones'].values()))
        self.assertEqual(self.client.diagnostics()['unassigned_frames'],1)


class ReadQueryTests(unittest.TestCase):
    def test_query_header_and_only_read_placeholders(self):
        p=module.build_read_query(b'ABCD',255,now_ms=123456789,offset_hours=1)
        self.assertEqual(struct.unpack_from('>HBBBqqB',p),(1,19,255,1,0,123456789,13))
        offset=22
        parsed=[]
        while offset<len(p):
            flag,size=struct.unpack_from('>HH',p,offset)
            value=p[offset+4:offset+4+size]
            if flag==0x17: self.assertEqual(value,b'ABCD')
            else: self.assertEqual(value,bytes(size))
            parsed.append(flag)
            offset+=4+size
        self.assertIn(0x1000,parsed)
        self.assertIn(0x1001,parsed)
        self.assertEqual(offset,len(p))

    def test_query_cannot_be_built_with_invalid_target_or_sequence(self):
        for target,sequence in [(b'A',1),('ABCD',1),(b'ABCD',256),(b'ABCD',-1),(b'ABCD',True)]:
            with self.assertRaises(ValueError): module.build_read_query(target,sequence)

    def test_boiler_unknown_relay_value_is_not_assumed_off(self):
        protocol=importlib.import_module('ferroli_under_test.protocol')
        for raw,expected in [(1,True),(16,True),(2,False),(0,None),(255,None)]:
            p=struct.pack('>HBBBqqB',3,19,1,100,0,0,12)+struct.pack('>HHB',0x2011,1,raw)
            data=protocol.decode_frame(p)
            fields=[f['valore'] for f in data['campi'] if f.get('nome')=='rele_caldaia']
            self.assertEqual(fields,[] if expected is None else [expected])


class ConstructorRegressionTests(unittest.TestCase):
    def test_constructing_api_and_client_in_event_loop_does_not_load_certs(self):
        async def create():
            module.Api('fixture')
            module.Client('fixture',lambda:None)
        with patch.object(module.ssl,'create_default_context',side_effect=AssertionError('Blocking SSL construction')):
            asyncio.run(create())

    def test_certificates_loaded_in_worker_on_first_request_only(self):
        event_thread=threading.get_ident()
        threads=[]
        def create_context():
            threads.append(threading.get_ident())
            return object()
        class Opener:
            def open(self,*args,**kwargs): return io.BytesIO(b'{"slug":"fixture"}')
        async def requests():
            api=module.Api('fixture')
            await asyncio.to_thread(api.call,'api/current_user')
            await asyncio.to_thread(api.call,'api/current_user')
        with patch.object(module.ssl,'create_default_context',side_effect=create_context), \
             patch.object(module,'build_opener',return_value=Opener()):
            asyncio.run(requests())
        self.assertEqual(len(threads),1)
        self.assertNotEqual(threads[0],event_thread)

if __name__=='__main__': unittest.main()
