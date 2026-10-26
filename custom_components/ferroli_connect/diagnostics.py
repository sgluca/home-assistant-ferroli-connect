"""Allowlist-only diagnostics; no config, IDs, topic names, credentials or payloads."""
async def async_get_config_entry_diagnostics(hass, entry):
    return entry.runtime_data.client.diagnostics()
