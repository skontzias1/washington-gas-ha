"""Diagnostics without login, account or bill amounts."""

from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import WashingtonGasConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: WashingtonGasConfigEntry
) -> dict[str, Any]:
    """Return diagnostics."""
    coordinator = entry.runtime_data
    return {
        "entry_version": entry.version,
        "options": dict(entry.options),
        "last_update_success": coordinator.last_update_success,
        "last_error": type(coordinator.last_exception).__name__
        if coordinator.last_exception
        else None,
        # No dates: the first bill reveals when service started.
        "bills_per_account": [len(bills) for bills in coordinator.data.values()],
    }
