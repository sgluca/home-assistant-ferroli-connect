"""UI setup; save the session token, never the password."""
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from .client import Api, AuthError, CloudError
from .const import DOMAIN, NAME

SCHEMA = vol.Schema({vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str})


def authenticate(user_input):
    api = Api()
    account = api.login(user_input[CONF_USERNAME], user_input[CONF_PASSWORD])
    return account, api.token


class FerroliConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                account, token = await self.hass.async_add_executor_job(authenticate, user_input)
            except AuthError:
                errors['base'] = 'invalid_auth'
            except CloudError:
                errors['base'] = 'cannot_connect'
            else:
                await self.async_set_unique_id(account)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=NAME, data={'token': token})
        return self.async_show_form(step_id='user', data_schema=SCHEMA, errors=errors)

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                account, token = await self.hass.async_add_executor_job(authenticate, user_input)
            except AuthError:
                errors['base'] = 'invalid_auth'
            except CloudError:
                errors['base'] = 'cannot_connect'
            else:
                entry = self._get_reauth_entry()
                if account != entry.unique_id:
                    errors['base'] = 'wrong_account'
                else:
                    return self.async_update_reload_and_abort(entry, data_updates={'token': token})
        return self.async_show_form(step_id='reauth_confirm', data_schema=SCHEMA, errors=errors)
