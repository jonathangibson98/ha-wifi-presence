"""Device tracker entities for WiFi Presence."""
from __future__ import annotations

from homeassistant.components.device_tracker import ScannerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_TRACKED, DOMAIN, SOURCE_BLUETOOTH, SOURCE_WIFI
from .coordinator import WifiScanCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: WifiScanCoordinator = entry.runtime_data
    async_add_entities(
        WifiPresenceDevice(coordinator, mac) for mac in entry.options.get(CONF_TRACKED, [])
    )


class WifiPresenceDevice(CoordinatorEntity[WifiScanCoordinator], ScannerEntity):
    """One tracked device.

    Home when ANY signal has seen it recently (WiFi, Bluetooth, or a linked
    entity). Not home only when all of them have gone quiet.
    """

    # Changes on every scan, so keep them out of the database.
    _unrecorded_attributes = frozenset(
        {"last_seen", "wifi_last_seen", "bluetooth_last_seen"}
    )

    def __init__(self, coordinator: WifiScanCoordinator, mac: str) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._attr_unique_id = f"{DOMAIN}_{mac}"

    @property
    def available(self) -> bool:
        # A failed scan shouldn't make the tracker "unavailable" (that breaks
        # person entities). Home/away is decided by the signals instead.
        return True

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
        return self.coordinator.status(self._mac)["connected"]

    @property
    def mac_address(self) -> str:
        return self._mac

    @property
    def ip_address(self) -> str | None:
        dev = self._device
        return dev.get("ip") if dev else None

    @property
    def hostname(self) -> str | None:
        dev = self._device
        return (dev.get("hostname") or None) if dev else None

    @property
    def extra_state_attributes(self) -> dict:
        status = self.coordinator.status(self._mac)
        attrs: dict = {"connected_via": status["sources"]}
        if status["last_seen"] is not None:
            attrs["last_seen"] = status["last_seen"].isoformat()
        dev = self._device
        if dev:
            for source in (SOURCE_WIFI, SOURCE_BLUETOOTH):
                seen_at = dev["seen"].get(source)
                if seen_at is not None:
                    attrs[f"{source}_last_seen"] = seen_at.isoformat()
        return attrs
