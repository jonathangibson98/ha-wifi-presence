"""Scans the local network and tracks which devices are present."""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import time
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_SCAN_INTERVAL,
    CONF_SUBNET,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SUBNET,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)
ARP_FILE = "/proc/net/arp"


class WifiScanCoordinator(DataUpdateCoordinator[dict]):
    """Poke every IP in the subnet, then read the ARP table to see who answered."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=interval),
        )
        subnet = entry.options.get(CONF_SUBNET, DEFAULT_SUBNET)
        self._network = ipaddress.ip_network(subnet, strict=False)
        self._hosts = [str(ip) for ip in self._network.hosts()]
        # mac -> {"ip": str, "hostname": str | None, "last_seen": datetime}
        self.devices: dict[str, dict] = {}

    def _scan(self) -> dict[str, str]:
        """Blocking scan. Returns {mac: ip} for everything currently on the network."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1048576)
        except OSError:
            pass
        # Sending anything to an IP makes the OS ask "who has this IP?" (ARP).
        # Even phones that ignore pings answer ARP.
        for ip in self._hosts:
            try:
                sock.sendto(b"\x00", (ip, 9))
            except OSError:
                pass
        time.sleep(5)  # give devices time to answer
        sock.close()

        found: dict[str, str] = {}
        try:
            with open(ARP_FILE, encoding="utf-8") as f:
                lines = f.read().splitlines()[1:]
        except OSError as err:
            _LOGGER.error("Can't read %s: %s", ARP_FILE, err)
            return found
        for line in lines:
            parts = line.split()
            if len(parts) < 6:
                continue
            ip, _hw, flags, mac = parts[:4]
            if flags != "0x2" or mac == "00:00:00:00:00:00":
                continue
            try:
                if ipaddress.ip_address(ip) not in self._network:
                    continue
            except ValueError:
                continue
            found[mac.lower()] = ip
        return found

    @staticmethod
    def _lookup(ip: str) -> str:
        try:
            return socket.gethostbyaddr(ip)[0].split(".")[0]
        except (OSError, socket.herror, socket.gaierror):
            return ""

    async def _async_update_data(self) -> dict:
        found = await self.hass.async_add_executor_job(self._scan)
        now = dt_util.utcnow()
        new_macs = []
        for mac, ip in found.items():
            dev = self.devices.get(mac)
            if dev is None:
                dev = self.devices[mac] = {"ip": ip, "hostname": None, "last_seen": now}
                new_macs.append(mac)
            dev["ip"] = ip
            dev["last_seen"] = now

        if new_macs:
            names = await asyncio.gather(
                *(
                    self.hass.async_add_executor_job(self._lookup, self.devices[m]["ip"])
                    for m in new_macs
                )
            )
            for mac, name in zip(new_macs, names):
                self.devices[mac]["hostname"] = name or None
        return self.devices
