"""One controllable thermostat per zone; existing sensors remain available."""
from functools import partial
import time

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACAction, HVACMode
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError

from .client import CloudError
from .const import STALE_SECONDS, valid_temperature_limits
from .entity import FerroliEntity

MODE_TO_CODE = {HVACMode.OFF: 4, HVACMode.HEAT: 1, HVACMode.AUTO: 0}
REPORTED_MODES = {'spento': HVACMode.OFF, 'manuale': HVACMode.HEAT, 'automatico': HVACMode.AUTO}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(FerroliClimate(coordinator, uid) for uid in coordinator.data['zones'])


class FerroliClimate(FerroliEntity, ClimateEntity):
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.AUTO]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5
    _attr_supported_features = (ClimateEntityFeature.TARGET_TEMPERATURE
                                | ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF)

    def __init__(self, coordinator, uid):
        super().__init__(coordinator, uid, 'temperatura_ambiente', 'Termostato')
        self._attr_unique_id = f'{uid}_climate'

    def fresh_value(self, key):
        zone = self.zone
        if not zone or time.monotonic()-zone['value_times'].get(key, float('-inf')) >= STALE_SECONDS:
            return None
        return zone['values'].get(key)

    @property
    def available(self):
        return (super().available and self.fresh_value('modalita') is not None
                and self.fresh_value('unita_temperatura') == 0)

    @property
    def current_temperature(self):
        return self.fresh_value('temperatura_ambiente')

    @property
    def target_temperature(self):
        mode = self.fresh_value('modalita')
        if mode == 'manuale':
            return self.fresh_value('temperatura_manuale')
        if mode == 'automatico' and self.fresh_value('override_attivo') is True:
            return self.fresh_value('temperatura_temporanea')
        return self.fresh_value('setpoint')

    @property
    def hvac_mode(self):
        return REPORTED_MODES.get(self.fresh_value('modalita'))

    @property
    def hvac_action(self):
        if self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        heating = self.fresh_value('riscaldamento_attivo')
        if self.hvac_mode is None or heating is None:
            return None
        return HVACAction.HEATING if heating else HVACAction.IDLE

    @property
    def min_temp(self):
        low, high = self.temperature_limits
        return low if valid_temperature_limits(low, high) else 5.0

    @property
    def max_temp(self):
        low, high = self.temperature_limits
        return high if valid_temperature_limits(low, high) else 35.0

    @property
    def temperature_limits(self):
        return self.fresh_value('limite_minimo'), self.fresh_value('limite_massimo')

    @property
    def extra_state_attributes(self):
        return {'modalita_ferroli': self.fresh_value('modalita'),
                'modifica_temporanea': self.fresh_value('override_attivo')}

    async def send(self, **command):
        if not self.available:
            raise HomeAssistantError('Attendi i dati aggiornati del termostato')
        try:
            await self.hass.async_add_executor_job(partial(self.coordinator.client.write_zone, self.uid, **command))
        except CloudError as exc:
            raise HomeAssistantError(str(exc)) from None
        # Values are only those received from the device; there is no optimistic state.
        self.coordinator.push_update()

    async def async_set_hvac_mode(self, hvac_mode):
        if hvac_mode not in MODE_TO_CODE:
            raise HomeAssistantError('Modalità non supportata')
        await self.send(mode=MODE_TO_CODE[hvac_mode])

    async def async_set_temperature(self, **kwargs):
        if ATTR_TEMPERATURE not in kwargs:
            raise HomeAssistantError('Specifica la temperatura desiderata')
        command = {'temperature': kwargs[ATTR_TEMPERATURE]}
        if 'hvac_mode' in kwargs:
            if kwargs['hvac_mode'] not in (HVACMode.HEAT, HVACMode.AUTO):
                raise HomeAssistantError('La temperatura richiede Manuale o Automatico')
            command['mode'] = MODE_TO_CODE[kwargs['hvac_mode']]
        await self.send(**command)

    async def async_turn_on(self):
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self):
        await self.async_set_hvac_mode(HVACMode.OFF)
