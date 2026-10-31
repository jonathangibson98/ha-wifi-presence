"""Config + options flow for WiFi Presence."""
from __future__ import annotations

import ipaddress
import re

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_CONSIDER_HOME,
    CONF_MANUAL_MACS,
    CONF_SCAN_INTERVAL,
    CONF_SUBNET,
    CONF_TRACKED,
    DEFAULT_CONSIDER_HOME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SUBNET,
    DOMAIN,
)

MAC_RE = re.compile(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$")


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
                    options={**user_input, CONF_TRACKED: []},
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
    async def async_step_init(self, user_input=None):
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
                return self.async_create_entry(
                    data={
                        CONF_SUBNET: user_input[CONF_SUBNET],
                        CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
                        CONF_CONSIDER_HOME: user_input[CONF_CONSIDER_HOME],
                        CONF_TRACKED: sorted(tracked),
                    }
                )

        saved = list(opts.get(CONF_TRACKED, []))
        choices = {mac: mac for mac in saved}
        if coordinator:
            for mac, dev in coordinator.devices.items():
                name = dev.get("hostname") or "Unknown"
                choices[mac] = f"{name} - {dev['ip']} - {mac}"

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
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
