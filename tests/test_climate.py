"""Adapter behavior with a minimal model of the HA 2026.10 entity interface."""
import asyncio
import importlib
from enum import IntFlag, StrEnum
import sys
import time
import types
import unittest
from unittest.mock import patch

import test_client as fixtures


def load_climate():
    class HVACMode(StrEnum):
        OFF='off'
        HEAT='heat'
        AUTO='auto'
    class HVACAction(StrEnum):
        OFF='off'
        HEATING='heating'
        IDLE='idle'
    class Features(IntFlag):
        TARGET_TEMPERATURE=1
        TURN_ON=2
        TURN_OFF=4
    class CoordinatorEntity:
        def __init__(self, coordinator):
            self.coordinator=coordinator
            self.hass=coordinator.hass
        @property
        def available(self): return True
    modules={name:types.ModuleType(name) for name in [
        'homeassistant','homeassistant.components','homeassistant.components.climate',
        'homeassistant.const','homeassistant.exceptions','homeassistant.helpers',
        'homeassistant.helpers.entity','homeassistant.helpers.update_coordinator']}
    api=modules['homeassistant.components.climate']
    api.ClimateEntity=type('ClimateEntity',(),{})
    api.ClimateEntityFeature=Features
    api.HVACMode,api.HVACAction=HVACMode,HVACAction
    modules['homeassistant.const'].ATTR_TEMPERATURE='temperature'
    modules['homeassistant.const'].UnitOfTemperature=types.SimpleNamespace(CELSIUS='°C')
    modules['homeassistant.exceptions'].HomeAssistantError=RuntimeError
    modules['homeassistant.helpers.entity'].DeviceInfo=lambda **kwargs:kwargs
    modules['homeassistant.helpers.update_coordinator'].CoordinatorEntity=CoordinatorEntity
    with patch.dict(sys.modules,modules):
        return importlib.import_module('ferroli_under_test.climate')


class ClimateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.api=load_climate()

    def setUp(self):
        self.calls=[]
        class Hass:
            async def async_add_executor_job(hass, function): return function()
        self.zone={'name':'fixture zone','values':{'modalita':'manuale','unita_temperatura':0,
                    'temperatura_ambiente':21.4,'temperatura_manuale':21,'setpoint':19,
                    'limite_minimo':5,'limite_massimo':30,'riscaldamento_attivo':False},
                   'value_times':{},'seen':time.monotonic()}
        self.zone['value_times']={k:time.monotonic() for k in self.zone['values']}
        self.coordinator=types.SimpleNamespace(hass=Hass(),data={'connected':True,'zones':{'uid':self.zone}},
            client=types.SimpleNamespace(write_zone=lambda uid,**kw:self.calls.append((uid,kw))),
            push_update=lambda:None)
        self.entity=self.api.FerroliClimate(self.coordinator,'uid')

    def test_state_matches_manual_and_automatic_semantics(self):
        self.assertTrue(self.entity.available)
        self.assertEqual(self.entity.current_temperature,21.4)
        self.assertEqual(self.entity.target_temperature,21)
        self.zone['values']['modalita']='automatico'
        self.assertEqual(self.entity.target_temperature,19)
        self.zone['values'].update(override_attivo=True,temperatura_temporanea=22)
        self.zone['value_times'].update(override_attivo=time.monotonic(),temperatura_temporanea=time.monotonic())
        self.assertEqual(self.entity.target_temperature,22)

    def test_commands_dispatch_to_correct_zone_without_optimistic_values(self):
        asyncio.run(self.entity.async_set_temperature(temperature=22))
        self.assertEqual(self.calls,[('uid',{'temperature':22})])
        self.assertEqual(self.entity.target_temperature,21)
        asyncio.run(self.entity.async_turn_off())
        self.assertEqual(self.calls[-1],('uid',{'mode':4}))

    def test_stale_mode_and_fahrenheit_disable_entity(self):
        self.zone['value_times']['modalita']=time.monotonic()-601
        self.assertFalse(self.entity.available)
        self.zone['value_times']['modalita']=time.monotonic()
        self.zone['values']['unita_temperatura']=1
        self.assertFalse(self.entity.available)

    def test_write_error_is_shown_and_does_not_change_state(self):
        def fail(*a,**kw): raise fixtures.module.CloudError('fixture no confirmation')
        self.coordinator.client.write_zone=fail
        with self.assertRaisesRegex(RuntimeError,'fixture no confirmation'):
            asyncio.run(self.entity.async_set_temperature(temperature=22))
        self.assertEqual(self.entity.target_temperature,21)

    def test_invalid_limits_cannot_clamp_dashboard_to_zero(self):
        for low, high in [(0, 0), (30, 5), (float('nan'), 30), (5, float('inf'))]:
            with self.subTest(low=low, high=high):
                self.zone['values'].update(limite_minimo=low, limite_massimo=high)
                self.assertEqual(self.entity.min_temp, 5)
                self.assertEqual(self.entity.max_temp, 35)
                self.assertEqual(self.entity.target_temperature, 21)
