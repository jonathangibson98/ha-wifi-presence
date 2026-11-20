"""Small parsing helpers for Bluetooth addresses, keys and IRKs."""
from __future__ import annotations

import base64
import binascii
import re

from .const import BLE_KEY_PREFIX

_BLE_RE = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")


def normalize_ble_address(raw: str) -> str | None:
    """Return an upper case AA:BB:CC:DD:EE:FF address, or None if it isn't one."""
    address = raw.strip().upper().replace("-", ":")
    return address if _BLE_RE.match(address) else None


def ble_key(address: str) -> str:
    """Tracked-device key for a Bluetooth-only device."""
    return BLE_KEY_PREFIX + address.lower()


def is_ble_key(key: str) -> bool:
    return key.startswith(BLE_KEY_PREFIX)


def ble_address(key: str) -> str:
    """AA:BB:CC:DD:EE:FF address from a Bluetooth-only key."""
    return key[len(BLE_KEY_PREFIX):].upper()


def is_random_mac(mac: str) -> bool:
    """True for a WiFi 'private' (randomized) MAC: phones make these up per network."""
    try:
        return bool(int(mac[1], 16) & 0x2)
    except (ValueError, IndexError):
        return False


def bluetooth_manufacturers(hass) -> dict[str, str]:
    """{ADDRESS: manufacturer} for Bluetooth devices heard right now, to help tell them apart.

    Empty when Bluetooth isn't set up or doesn't say.
    """
    if "bluetooth" not in hass.config.components:
        return {}
    try:
        from homeassistant.components import bluetooth

        out = {}
        for info in bluetooth.async_discovered_service_info(hass, False):
            maker = getattr(info, "manufacturer", None)
            if maker:
                out[info.address.upper()] = str(maker)
        return out
    except Exception:  # noqa: BLE001 - this is only a hint
        return {}


def parse_irk(raw: str) -> bytes | None:
    """Turn an IRK into 16 bytes. Same formats as HA's Private BLE Device.

    Accepts 32 hex characters (colons, dashes and spaces are ignored), or the
    base64 form that ends in "=". An optional "irk:" prefix is ignored.
    """
    value = raw.strip()
    if value.lower().startswith("irk:"):
        value = value[4:].strip()
    try:
        if value.endswith("="):
            data = bytes(reversed(base64.b64decode(value, validate=True)))
        else:
            cleaned = value.replace(":", "").replace("-", "").replace(" ", "")
            data = binascii.unhexlify(cleaned)
    except (binascii.Error, ValueError):
        return None
    return data if len(data) == 16 else None


def is_resolvable_private(address: str) -> bool:
    """True if a Bluetooth address looks like a rotating private address."""
    try:
        return int(address[:2], 16) & 0xC0 == 0x40
    except ValueError:
        return False
