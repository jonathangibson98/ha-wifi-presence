"""WiFi Presence: tracks devices on your WiFi, plus Bluetooth and linked entities."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import WifiScanCoordinator

PLATFORMS = [Platform.DEVICE_TRACKER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = WifiScanCoordinator(hass, entry)
    await coordinator.async_load()
    # Start Bluetooth and linked-entity listening before the first scan so a
    # device that's already visible is counted right away.
    coordinator.async_start()
    entry.async_on_unload(coordinator.async_stop)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator: WifiScanCoordinator = entry.runtime_data
    await coordinator.async_save_now()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
