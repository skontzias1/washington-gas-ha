"""Washington Gas integration."""

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_LEGACY
from .coordinator import WashingtonGasConfigEntry, WashingtonGasCoordinator
from .store import BillStore

PLATFORMS = [Platform.SENSOR]


async def async_migrate_entry(
    hass: HomeAssistant, entry: WashingtonGasConfigEntry
) -> bool:
    """Keep the statistic and entity IDs of version 1 (single account) entries."""
    if entry.version == 1:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_LEGACY: True}, version=2
        )
    return entry.version == 2


async def async_setup_entry(
    hass: HomeAssistant, entry: WashingtonGasConfigEntry
) -> bool:
    """Set up from a config entry."""
    coordinator = WashingtonGasCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: WashingtonGasConfigEntry
) -> bool:
    """Unload."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(
    hass: HomeAssistant, entry: WashingtonGasConfigEntry
) -> None:
    """Remove cached bills."""
    await BillStore(hass, entry.entry_id).async_remove()
