"""A distinct HA device for every cloud zone."""
import time

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, STALE_SECONDS


class FerroliEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, uid, key, name):
        super().__init__(coordinator)
        self.uid, self.key = uid, key
        self._attr_unique_id = f'{uid}_{key}'
        self._attr_name = name
        zone = coordinator.data['zones'][uid]
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, uid)},
                                           name=zone['name'], manufacturer='Ferroli',
                                           model='Connect — zona')

    @property
    def zone(self):
        return (self.coordinator.data or {}).get('zones', {}).get(self.uid)

    @property
    def available(self):
        zone = self.zone
        return bool(super().available and zone and self.coordinator.data.get('connected')
                    and zone['value_times'].get(self.key)
                    and time.monotonic()-zone['value_times'][self.key] < STALE_SECONDS
                    and self.key in zone['values'])

    @property
    def value(self):
        return self.zone['values'].get(self.key) if self.zone else None
