import time
import unittest

import test_client as fixtures

module=fixtures.module


class CloudPointTests(unittest.TestCase):
    setUp=fixtures.ClientTests.setUp
    tearDown=fixtures.ClientTests.tearDown

    def test_separate_cloud_points_fill_both_zones(self):
        paths=list(self.client.cloud_targets.values())
        now=format(int(time.time()*1000),'x')
        def call(path,**kwargs):
            return {'utcMilliseconds':now,'roomCurrentTemp':'00d2' if path==paths[0] else '00d6',
                    'roomManualTemp':'00d2','roomWorkMode':'01','roomTempUnit':'00',
                    'roomTargetTempMax':'012c','roomTargetTempMin':'0032'}
        self.client.api.call=call
        self.client.read_cloud_snapshots()
        zones=list(self.client.snapshot()['zones'].values())
        self.assertEqual(zones[0]['values']['temperatura_ambiente'],21)
        self.assertEqual(zones[1]['values']['temperatura_ambiente'],21.4)
        self.assertEqual(zones[0]['field_sources']['modalita'],'cloud_snapshot')
        self.assertFalse(zones[0]['mqtt_values'])

    def test_stale_cache_cannot_make_entities_fresh(self):
        self.client.api.call=lambda *a,**kw:{'utcMilliseconds':format(int((time.time()-601)*1000),'x'),
                                           'roomCurrentTemp':'00d2','roomWorkMode':'01'}
        self.client.read_cloud_snapshots()
        self.assertEqual(self.client.diagnostics()['cloud_stale_snapshots'],2)
        self.assertTrue(all(not z['values'] for z in self.client.snapshot()['zones'].values()))

    def test_missing_fields_are_not_assumed_zero(self):
        self.client.api.call=lambda *a,**kw:{'utcMilliseconds':format(int(time.time()*1000),'x'),
                                           'roomWorkMode':'01','roomCurrentTemp':'invalid'}
        self.client.read_cloud_snapshots()
        for zone in self.client.snapshot()['zones'].values():
            self.assertEqual(zone['values'],{'modalita':'manuale'})

    def test_old_cache_does_not_replace_new_mqtt(self):
        self.client.receive(self.topic,fixtures.frame(b'ABCD',215))
        self.client.api.call=lambda *a,**kw:{'utcMilliseconds':format(int((time.time()-10)*1000),'x'),
                                           'roomCurrentTemp':'00d2'}
        self.client.read_cloud_snapshots()
        uid=self.client.identities[('dispositivo_1',b'ABCD')]
        self.assertEqual(self.client.snapshot()['zones'][uid]['values']['temperatura_ambiente'],21.5)

    def test_one_zone_error_does_not_block_the_other(self):
        first=next(iter(self.client.cloud_targets.values()))
        def call(path,**kwargs):
            if path==first: raise module.CloudError('fixture failure')
            return {'utcMilliseconds':format(int(time.time()*1000),'x'),'roomWorkMode':'01'}
        self.client.api.call=call
        self.client.read_cloud_snapshots()
        self.assertEqual(self.client.diagnostics()['cloud_reads'],1)
        self.assertEqual(len([z for z in self.client.snapshot()['zones'].values() if z['values']]),1)
