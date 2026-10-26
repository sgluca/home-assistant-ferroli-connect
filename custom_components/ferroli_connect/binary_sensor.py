"""Per-zone binary state, only where present in telemetry."""
from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity

from .entity import FerroliEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    entities = []
    for uid in coordinator.data['zones']:
        entities.append(FerroliBinary(coordinator, uid, 'batteria_scarica', 'Batteria scarica',
                                     BinarySensorDeviceClass.BATTERY))
        entities.append(FerroliBinary(coordinator, uid, 'riscaldamento_attivo', 'Richiesta riscaldamento',
                                     BinarySensorDeviceClass.HEAT))
    for uid in coordinator.data['boilers']:
        entities.append(FerroliBoilerBinary(coordinator, uid, 'rele_caldaia', 'Contatto relè caldaia chiuso', None))
        entities.append(FerroliBoilerBinary(coordinator, uid, 'caldaia_accesa', 'Caldaia accesa (app)', None))
        entities.append(FerroliBoilerBinary(coordinator, uid, 'opentherm_connesso', 'OpenTherm connesso',
                                           BinarySensorDeviceClass.CONNECTIVITY))
    async_add_entities(entities)


class FerroliBinary(FerroliEntity, BinarySensorEntity):
    def __init__(self, coordinator, uid, key, name, device_class):
        super().__init__(coordinator, uid, key, name)
        self._attr_device_class = device_class

    @property
    def is_on(self):
        return self.value


class FerroliBoilerBinary(FerroliBinary):
    collection = 'boilers'
    model = 'Connect — caldaia'
