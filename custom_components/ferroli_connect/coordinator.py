"""Push state with a periodic connection and freshness check."""
import logging
import time
from datetime import timedelta

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.event import async_track_time_interval

from .client import AuthError, Client, CloudError
from .const import DOMAIN

LOGGER = logging.getLogger(__name__)


class FerroliCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(hass, LOGGER, name=DOMAIN, config_entry=entry)
        self.entry = entry
        self.closed = False
        self.next_attempt = 0.0
        self.client = Client(entry.data['token'], self.thread_update)
        # Push updates reset the coordinator's normal polling timer. A fixed
        # timer guarantees token renewal and staleness checks even during traffic.
        self.cancel_timer = async_track_time_interval(hass, self.tick, timedelta(seconds=30))

    async def tick(self, now):
        if not self.closed:
            await self.async_request_refresh()

    def thread_update(self):
        self.hass.loop.call_soon_threadsafe(self.push_update)

    def push_update(self):
        if not self.closed:
            self.async_set_updated_data(self.client.snapshot())

    async def _async_update_data(self):
        try:
            refreshed = await self.hass.async_add_executor_job(self.client.refresh_token)
            if refreshed:
                self.hass.config_entries.async_update_entry(self.entry, data={**self.entry.data, 'token': refreshed})
            if not self.client.snapshot()['connected']:
                if time.monotonic() < self.next_attempt:
                    raise UpdateFailed('In attesa del prossimo tentativo')
                self.next_attempt = time.monotonic() + 120
                await self.hass.async_add_executor_job(self.client.start)
            await self.hass.async_add_executor_job(self.client.poll_readings)
            return self.client.snapshot()
        except AuthError:
            raise ConfigEntryAuthFailed('Sessione scaduta: accedi nuovamente a Ferroli Connect') from None
        except CloudError as exc:
            raise UpdateFailed(str(exc)) from None

    async def async_close(self):
        await self.async_shutdown()

    async def async_shutdown(self, event=None):
        if self.closed:
            return
        self.closed = True
        self.cancel_timer()
        await self.hass.async_add_executor_job(self.client.stop)
        await super().async_shutdown()
