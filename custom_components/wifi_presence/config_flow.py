"""Config + options flow for WiFi Presence."""
from __future__ import annotations

import ipaddress
import re

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import selector

from .const import (
    CONF_BLUETOOTH,
    CONF_CONSIDER_HOME,
    CONF_ENTITIES,
    CONF_IRK,
    CONF_LINKS,
    CONF_MANUAL_MACS,
    CONF_SCAN_INTERVAL,
    CONF_SUBNET,
    CONF_TRACKED,
    DEFAULT_CONSIDER_HOME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SUBNET,
    DOMAIN,
)
from .helpers import normalize_ble_address, parse_irk

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
                    options={**user_input, CONF_TRACKED: [], CONF_LINKS: {}},
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
        self._link_mac: str | None = None

    def _device_labels(self, macs) -> dict[str, str]:
        """Friendly 'name - ip - mac' labels for a list of MACs."""
        coordinator = getattr(self.config_entry, "runtime_data", None)
        labels = {}
        for mac in macs:
            dev = coordinator.devices.get(mac) if coordinator else None
            if not dev:
                labels[mac] = mac
                continue
            name = dev.get("hostname") or "Unknown"
            ip = dev.get("ip")
            labels[mac] = f"{name} - {ip} - {mac}" if ip else f"{name} - {mac}"
        return labels

    # ------------------------------------------------------------------- menu

    async def async_step_init(self, user_input=None):
        if not self.config_entry.options.get(CONF_TRACKED):
            # Nothing to link yet, go straight to picking devices.
            return await self.async_step_settings()
        return self.async_show_menu(
            step_id="init", menu_options=["settings", "link"]
        )

    # --------------------------------------------------- devices + scan settings

    async def async_step_settings(self, user_input=None):
        errors = {}
        opts = self.config_entry.options
        coordinator = getattr(self.config_entry, "runtime_data", None)

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

            if not errors:
                # Keep the extra signals, but drop them for devices no longer tracked.
                links = {
                    mac: link
                    for mac, link in (opts.get(CONF_LINKS) or {}).items()
                    if mac in tracked
                }
                return self.async_create_entry(
                    data={
                        CONF_SUBNET: user_input[CONF_SUBNET],
                        CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
                        CONF_CONSIDER_HOME: user_input[CONF_CONSIDER_HOME],
                        CONF_TRACKED: sorted(tracked),
                        CONF_LINKS: links,
                    }
                )

        saved = list(opts.get(CONF_TRACKED, []))
        choices = {mac: mac for mac in saved}
        if coordinator:
            choices.update(self._device_labels(list(coordinator.devices)))

        schema = vol.Schema(
            {
                vol.Optional(CONF_TRACKED, default=saved): cv.multi_select(choices),
                vol.Optional(CONF_MANUAL_MACS, default=""): str,
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

    # ------------------------------------------- Bluetooth / linked entity links

    async def async_step_link(self, user_input=None):
        """Pick which tracked device to add extra signals to."""
        tracked = list(self.config_entry.options.get(CONF_TRACKED, []))
        if user_input is not None:
            self._link_mac = user_input[CONF_DEVICE]
            return await self.async_step_link_details()

        labels = self._device_labels(tracked)
        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[{"value": m, "label": labels[m]} for m in tracked],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(step_id="link", data_schema=schema)

    async def async_step_link_details(self, user_input=None):
        errors = {}
        opts = self.config_entry.options
        mac = self._link_mac
        current = (opts.get(CONF_LINKS) or {}).get(mac, {})

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
                    links[mac] = link
                else:
                    links.pop(mac, None)
                return self.async_create_entry(data={**opts, CONF_LINKS: links})

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_BLUETOOTH,
                    description={"suggested_value": current.get(CONF_BLUETOOTH, "")},
                ): str,
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
            description_placeholders={"device": self._device_labels([mac])[mac]},
        )
