"""Device tracker entities for WiFi Presence."""
from __future__ import annotations

from homeassistant.components.device_tracker import ScannerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import CONF_CONSIDER_HOME, CONF_TRACKED, DEFAULT_CONSIDER_HOME, DOMAIN
from .coordinator import WifiScanCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: WifiScanCoordinator = entry.runtime_data
    consider_home = entry.options.get(CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME)
    async_add_entities(
        WifiPresenceDevice(coordinator, mac, consider_home)
        for mac in entry.options.get(CONF_TRACKED, [])
    )


class WifiPresenceDevice(CoordinatorEntity[WifiScanCoordinator], ScannerEntity):
    """One tracked device (home when it's on the WiFi, not_home when it's not)."""

    def __init__(self, coordinator: WifiScanCoordinator, mac: str, consider_home: int) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._consider_home = consider_home
        self._attr_unique_id = f"{DOMAIN}_{mac}"

    @property
    def _device(self) -> dict | None:
        return self.coordinator.devices.get(self._mac)

    @property
    def name(self) -> str:
        dev = self._device
        if dev and dev.get("hostname"):
            return dev["hostname"]
        return f"WiFi {self._mac}"

    @property
    def is_connected(self) -> bool:
        dev = self._device
        if not dev:
            return False
        age = (dt_util.utcnow() - dev["last_seen"]).total_seconds()
        return age <= self._consider_home

    @property
    def mac_address(self) -> str:
        return self._mac

    @property
    def ip_address(self) -> str | None:
        dev = self._device
        return dev["ip"] if dev else None

    @property
    def hostname(self) -> str | None:
        dev = self._device
        return dev.get("hostname") if dev else None
