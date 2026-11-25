"""Config + options flow for WiFi Presence."""
from __future__ import annotations

import ipaddress
import re

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import (
    CONF_BLUETOOTH,
    CONF_CONSIDER_HOME,
    CONF_ENTITIES,
    CONF_IRK,
    CONF_LINKS,
    CONF_MANUAL_BLE,
    CONF_MANUAL_MACS,
    CONF_NAMES,
    CONF_REMOVE,
    CONF_SCAN_INTERVAL,
    CONF_SUBNET,
    CONF_TRACKED,
    DEFAULT_CONSIDER_HOME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SUBNET,
    DOMAIN,
)
from .helpers import (
    ble_address,
    ble_key,
    bluetooth_manufacturers,
    is_ble_key,
    is_random_mac,
    normalize_ble_address,
    parse_irk,
)

MAC_RE = re.compile(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$")
CONF_DEVICE = "device"


class WifiPresenceConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                ipaddress.ip_network(user_input[CONF_SUBNET], strict=False)
            except ValueError:
                errors[CONF_SUBNET] = "invalid_subnet"
            else:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="WiFi Presence",
                    data={},
                    options={**user_input, CONF_TRACKED: [], CONF_LINKS: {}, CONF_NAMES: {}},
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_SUBNET, default=DEFAULT_SUBNET): str,
                vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
                    vol.Coerce(int), vol.Range(min=15, max=600)
                ),
                vol.Required(CONF_CONSIDER_HOME, default=DEFAULT_CONSIDER_HOME): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=3600)
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return WifiPresenceOptionsFlow()


class WifiPresenceOptionsFlow(OptionsFlow):
    def __init__(self) -> None:
        self._link_key: str | None = None
        self._name_key: str | None = None

    @property
    def _coordinator(self):
        return getattr(self.config_entry, "runtime_data", None)

    # ----------------------------------------------------- telling devices apart

    def _context(self) -> tuple[dict, dict]:
        """(Bluetooth devices heard now by address, their manufacturers)."""
        coordinator = self._coordinator
        if not coordinator:
            return {}, {}
        ble = {item["address"]: item for item in coordinator.discovered_bluetooth()}
        return ble, bluetooth_manufacturers(self.hass)

    def _label(self, key: str, ctx: tuple[dict, dict]) -> str:
        """One line that helps you tell devices apart.

        Your own name first, then what the network or Bluetooth calls it. WiFi lines
        show the IP and MAC (and 'random MAC' for a phone's private address). Bluetooth
        lines show the maker and signal strength: hold the device close and the
        strongest signal is usually it.
        """
        ble, mans = ctx
        coordinator = self._coordinator
        names = self.config_entry.options.get(CONF_NAMES) or {}
        dev = coordinator.devices.get(key) if coordinator else None
        if is_ble_key(key):
            address = ble_address(key)
            item = ble.get(address) or {}
            name = names.get(key) or (dev or {}).get("hostname") or item.get("name") or "Unknown"
            bits = []
            if mans.get(address):
                bits.append(mans[address])
            if item.get("rssi") is not None:
                bits.append(f"{item['rssi']} dBm")
            extra = f" ({', '.join(bits)})" if bits else ""
            return f"Bluetooth - {name} - {address}{extra}"
        name = names.get(key) or (dev or {}).get("hostname") or "Unknown"
        ip = (dev or {}).get("ip")
        label = " - ".join(["WiFi", name] + ([ip] if ip else []) + [key])
        return label + (" (random MAC)" if is_random_mac(key) else "")

    def _all_choices(self, ctx: tuple[dict, dict]) -> dict[str, str]:
        """Every device we know of: tracked ones, WiFi devices found, Bluetooth devices heard."""
        coordinator = self._coordinator
        keys = list(dict.fromkeys(self.config_entry.options.get(CONF_TRACKED, [])))
        if coordinator:
            keys += [k for k in coordinator.devices if not is_ble_key(k) and k not in keys]
        keys += [ble_key(a) for a in ctx[0] if ble_key(a) not in keys]
        return {key: self._label(key, ctx) for key in keys}

    # ------------------------------------------------------------------- menu

    async def async_step_init(self, user_input=None):
        menu = ["settings", "name"]
        if self.config_entry.options.get(CONF_TRACKED):
            menu += ["link", "remove"]
        return self.async_show_menu(step_id="init", menu_options=menu)

    # --------------------------------------------------- devices + scan settings

    async def async_step_settings(self, user_input=None):
        errors = {}
        opts = self.config_entry.options

        if user_input is not None:
            try:
                ipaddress.ip_network(user_input[CONF_SUBNET], strict=False)
            except ValueError:
                errors[CONF_SUBNET] = "invalid_subnet"

            tracked = set(user_input.get(CONF_TRACKED, []))
            for raw in re.split(r"[,\s]+", user_input.get(CONF_MANUAL_MACS, "").strip()):
                if not raw:
                    continue
                mac = raw.lower().replace("-", ":")
                if MAC_RE.match(mac):
                    tracked.add(mac)
                else:
                    errors[CONF_MANUAL_MACS] = "invalid_mac"
            for raw in re.split(r"[,\s]+", user_input.get(CONF_MANUAL_BLE, "").strip()):
                if not raw:
                    continue
                address = normalize_ble_address(raw)
                if address:
                    tracked.add(ble_key(address))
                else:
                    errors[CONF_MANUAL_BLE] = "invalid_bluetooth"

            if not errors:
                self._forget_entities(set(opts.get(CONF_TRACKED, [])) - tracked)
                # Keep the extra signals, but drop them for devices no longer tracked.
                links = {
                    key: link
                    for key, link in (opts.get(CONF_LINKS) or {}).items()
                    if key in tracked
                }
                return self.async_create_entry(
                    data={
                        CONF_SUBNET: user_input[CONF_SUBNET],
                        CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
                        CONF_CONSIDER_HOME: user_input[CONF_CONSIDER_HOME],
                        CONF_TRACKED: sorted(tracked),
                        CONF_LINKS: links,
                        # Names are kept even for devices you stop tracking.
                        CONF_NAMES: dict(opts.get(CONF_NAMES) or {}),
                    }
                )

        saved = list(opts.get(CONF_TRACKED, []))
        choices = self._all_choices(self._context())

        schema = vol.Schema(
            {
                vol.Optional(CONF_TRACKED, default=saved): cv.multi_select(choices),
                vol.Optional(CONF_MANUAL_MACS, default=""): str,
                vol.Optional(CONF_MANUAL_BLE, default=""): str,
                vol.Required(
                    CONF_SUBNET, default=opts.get(CONF_SUBNET, DEFAULT_SUBNET)
                ): str,
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=15, max=600)),
                vol.Required(
                    CONF_CONSIDER_HOME,
                    default=opts.get(CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=3600)),
            }
        )
        return self.async_show_form(step_id="settings", data_schema=schema, errors=errors)

    # ------------------------------------------------------ remove devices

    def _forget_entities(self, keys) -> None:
        """Delete the tracker entities of devices that are no longer tracked.

        Without this, an untracked device leaves a dead entity behind in Home Assistant.
        """
        registry = er.async_get(self.hass)
        for key in keys:
            entity_id = registry.async_get_entity_id("device_tracker", DOMAIN, f"{DOMAIN}_{key}")
            if entity_id:
                registry.async_remove(entity_id)

    async def async_step_remove(self, user_input=None):
        """Pick tracked devices you don't use any more and remove them for good."""
        opts = self.config_entry.options
        tracked = list(dict.fromkeys(opts.get(CONF_TRACKED, [])))
        if not tracked:
            return self.async_abort(reason="nothing_to_remove")

        if user_input is not None:
            gone = {k for k in user_input.get(CONF_REMOVE, []) if k in tracked}
            keep = [k for k in tracked if k not in gone]
            self._forget_entities(gone)
            return self.async_create_entry(
                data={
                    **opts,
                    CONF_TRACKED: keep,
                    CONF_LINKS: {k: v for k, v in (opts.get(CONF_LINKS) or {}).items() if k in keep},
                    CONF_NAMES: {k: v for k, v in (opts.get(CONF_NAMES) or {}).items() if k in keep},
                }
            )

        ctx = self._context()
        schema = vol.Schema(
            {
                vol.Required(CONF_REMOVE): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[{"value": k, "label": self._label(k, ctx)} for k in tracked],
                        multiple=True,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                )
            }
        )
        return self.async_show_form(step_id="remove", data_schema=schema)

    # ------------------------------------------------------- name a device

    async def async_step_name(self, user_input=None):
        """Pick a device to give your own name (or to change or clear its name)."""
        choices = self._all_choices(self._context())
        if not choices:
            return self.async_abort(reason="no_devices")
        if user_input is not None:
            self._name_key = user_input[CONF_DEVICE]
            return await self.async_step_name_details()

        names = self.config_entry.options.get(CONF_NAMES) or {}
        # Devices without a name of yours come first.
        ordered = sorted(choices, key=lambda k: bool(names.get(k)))
        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[{"value": k, "label": choices[k]} for k in ordered],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(step_id="name", data_schema=schema)

    async def async_step_name_details(self, user_input=None):
        opts = self.config_entry.options
        key = self._name_key
        names = dict(opts.get(CONF_NAMES) or {})

        if user_input is not None:
            name = (user_input.get(CONF_NAME) or "").strip()[:60]
            if name:
                names[key] = name
            else:
                names.pop(key, None)
            return self.async_create_entry(data={**opts, CONF_NAMES: names})

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_NAME, description={"suggested_value": names.get(key, "")}
                ): str
            }
        )
        return self.async_show_form(
            step_id="name_details",
            data_schema=schema,
            description_placeholders={"device": self._label(key, self._context())},
        )

    # ------------------------------------------- Bluetooth / linked entity links

    async def async_step_link(self, user_input=None):
        """Pick which tracked device to add extra signals to."""
        tracked = list(self.config_entry.options.get(CONF_TRACKED, []))
        if user_input is not None:
            self._link_key = user_input[CONF_DEVICE]
            return await self.async_step_link_details()

        ctx = self._context()
        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[{"value": k, "label": self._label(k, ctx)} for k in tracked],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(step_id="link", data_schema=schema)

    async def async_step_link_details(self, user_input=None):
        errors = {}
        opts = self.config_entry.options
        key = self._link_key
        current = (opts.get(CONF_LINKS) or {}).get(key, {})

        if user_input is not None:
            address = (user_input.get(CONF_BLUETOOTH) or "").strip()
            irk = (user_input.get(CONF_IRK) or "").strip()
            entities = user_input.get(CONF_ENTITIES) or []

            if address and not normalize_ble_address(address):
                errors[CONF_BLUETOOTH] = "invalid_bluetooth"
            if irk and parse_irk(irk) is None:
                errors[CONF_IRK] = "invalid_irk"

            if not errors:
                links = dict(opts.get(CONF_LINKS) or {})
                link = {}
                if address:
                    link[CONF_BLUETOOTH] = normalize_ble_address(address)
                if irk:
                    link[CONF_IRK] = irk
                if entities:
                    link[CONF_ENTITIES] = list(entities)
                if link:
                    links[key] = link
                else:
                    links.pop(key, None)
                return self.async_create_entry(data={**opts, CONF_LINKS: links})

        # Bluetooth devices heard right now, so the address can be picked.
        ctx = self._context()
        ble, mans = ctx
        names = opts.get(CONF_NAMES) or {}
        ble_options = []
        for address, item in ble.items():
            name = names.get(ble_key(address)) or item["name"] or "Unknown"
            maker = f" ({mans[address]})" if mans.get(address) else ""
            ble_options.append({"value": address, "label": f"{name}{maker} - {address}"})
        saved_address = current.get(CONF_BLUETOOTH)
        if saved_address and all(o["value"] != saved_address for o in ble_options):
            ble_options.append({"value": saved_address, "label": saved_address})
        if ble_options:
            ble_field = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=ble_options,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        else:
            ble_field = selector.TextSelector()

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_BLUETOOTH,
                    description={"suggested_value": current.get(CONF_BLUETOOTH, "")},
                ): ble_field,
                vol.Optional(
                    CONF_IRK,
                    description={"suggested_value": current.get(CONF_IRK, "")},
                ): str,
                vol.Optional(
                    CONF_ENTITIES,
                    description={"suggested_value": current.get(CONF_ENTITIES, [])},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["device_tracker", "binary_sensor"], multiple=True
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="link_details",
            data_schema=schema,
            errors=errors,
            description_placeholders={"device": self._label(key, ctx)},
        )
