"""Anker Solix Bluetooth integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import HomeAssistant

from .coordinator import SolixCoordinator

PLATFORMS = [Platform.SENSOR]

type SolixConfigEntry = ConfigEntry[SolixCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: SolixConfigEntry) -> bool:
    """Set up telemetry for one Solix device."""
    coordinator = SolixCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, coordinator.async_stop)
    )
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SolixConfigEntry) -> bool:
    """Unload sensors and disconnect any active telemetry session."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_shutdown()
    return unload_ok


async def async_update_options(hass: HomeAssistant, entry: SolixConfigEntry) -> None:
    """Apply a changed polling interval."""
    await hass.config_entries.async_reload(entry.entry_id)
