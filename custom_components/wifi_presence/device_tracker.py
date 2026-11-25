"""Device tracker entities for WiFi Presence."""
from __future__ import annotations

from homeassistant.components.device_tracker import ScannerEntity, SourceType
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_NAMES, CONF_TRACKED, DOMAIN, SOURCE_BLUETOOTH, SOURCE_WIFI
from .coordinator import WifiScanCoordinator
from .helpers import ble_address, is_ble_key


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: WifiScanCoordinator = entry.runtime_data
    _remove_orphans(hass, entry)
    async_add_entities(
        WifiPresenceDevice(coordinator, key) for key in entry.options.get(CONF_TRACKED, [])
    )


def _remove_orphans(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete tracker entities left behind by devices you stopped tracking."""
    wanted = {f"{DOMAIN}_{key}".lower() for key in entry.options.get(CONF_TRACKED, [])}
    registry = er.async_get(hass)
    for item in er.async_entries_for_config_entry(registry, entry.entry_id):
        if item.domain == "device_tracker" and item.platform == DOMAIN and (item.unique_id or "").lower() not in wanted:
            registry.async_remove(item.entity_id)


class WifiPresenceDevice(CoordinatorEntity[WifiScanCoordinator], ScannerEntity):
    """One tracked device: WiFi only, Bluetooth only, or both.

    Home when ANY signal has seen it recently (WiFi, Bluetooth, or a linked
    entity). Not home only when all of them have gone quiet.
    """

    # Changes on every scan, so keep them out of the database.
    _unrecorded_attributes = frozenset(
        {"last_seen", "wifi_last_seen", "bluetooth_last_seen"}
    )

    def __init__(self, coordinator: WifiScanCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._ble_only = is_ble_key(key)
        # WiFi devices keep their old unique id (wifi_presence_<mac>), so nothing
        # changes for trackers that already exist.
        self._attr_unique_id = f"{DOMAIN}_{key}"

    @property
    def available(self) -> bool:
        # A failed scan shouldn't make the tracker "unavailable" (that breaks
        # person entities). Home/away is decided by the signals instead.
        return True

    @property
    def _device(self) -> dict | None:
        return self.coordinator.devices.get(self._key)

    @property
    def name(self) -> str:
        # The name you gave the device wins, then the name the network or
        # Bluetooth reports.
        names = self.coordinator.config_entry.options.get(CONF_NAMES) or {}
        if names.get(self._key):
            return names[self._key]
        dev = self._device
        if dev and dev.get("hostname"):
            return dev["hostname"]
        if self._ble_only:
            return f"Bluetooth {ble_address(self._key)}"
        return f"WiFi {self._key}"

    @property
    def source_type(self) -> SourceType:
        return SourceType.BLUETOOTH if self._ble_only else SourceType.ROUTER

    @property
    def is_connected(self) -> bool:
        return self.coordinator.status(self._key)["connected"]

    @property
    def mac_address(self) -> str:
        return ble_address(self._key).lower() if self._ble_only else self._key

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
        status = self.coordinator.status(self._key)
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
