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
