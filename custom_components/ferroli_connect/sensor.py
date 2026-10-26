"""Per-zone temperature and operating mode sensors."""
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfTemperature

from .entity import FerroliEntity

TEMPERATURES = {'temperatura_ambiente': 'Temperatura ambiente', 'setpoint': 'Setpoint',
                'temperatura_manuale': 'Temperatura manuale', 'comfort': 'Comfort',
                'economy': 'Economy', 'antigelo': 'Antigelo'}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    entities = []
    for uid in coordinator.data['zones']:
        entities.extend(FerroliTemperature(coordinator, uid, key, name) for key, name in TEMPERATURES.items())
        entities.append(FerroliMode(coordinator, uid, 'modalita', 'Modalità'))
    async_add_entities(entities)


class FerroliTemperature(FerroliEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def available(self):
        return super().available and self.zone['values'].get('unita_temperatura', 0) == 0

    @property
    def native_value(self):
        return self.value


class FerroliMode(FerroliEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ['automatico', 'manuale', 'assenza', 'party', 'spento', 'sanitario', 'sconosciuta']

    @property
    def native_value(self):
        return self.value
