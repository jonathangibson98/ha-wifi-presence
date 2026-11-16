"""Scans the local network and tracks which devices are present."""
from __future__ import annotations

import asyncio
import errno
import ipaddress
import logging
import selectors
import socket
import time
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_SCAN_INTERVAL,
    CONF_SUBNET,
    CONF_TRACKED,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SUBNET,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)
ARP_FILE = "/proc/net/arp"
STORAGE_VERSION = 1
SAVE_DELAY = 60  # seconds; batches disk writes instead of writing every scan

# Timing for one scan. The kernel gives up on an ARP lookup after ~3 tries
# 1 second apart, so each wait has to be a bit longer than that.
FIRST_WAIT = 5.0  # after the full subnet sweep
RETRY_WAIT = 3.5  # after each extra try at a missing tracked device
RETRY_ROUNDS = 3  # extra tries for tracked devices that didn't answer

# Ports that make sleeping phones answer.
#  5353  = mDNS (iPhones, Androids, Macs, Chromecasts all listen)
#  62078 = Apple lockdown service (wakes an iPhone's WiFi even when locked)
#  9     = discard (harmless, just triggers ARP)
UDP_PROBE_PORTS = (5353, 9)
TCP_PROBE_PORTS = (62078,)

# Answers that prove a device is awake (port open, or port closed but it replied).
_ALIVE_ERRNOS = {0, errno.ECONNREFUSED, errno.EISCONN}


class WifiScanCoordinator(DataUpdateCoordinator[dict]):
    """Sweep the subnet, retry the devices we care about, then read the ARP table."""

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
        self._tracked: set[str] = {m.lower() for m in entry.options.get(CONF_TRACKED, [])}
        # mac -> {"ip": str, "hostname": str | None, "last_seen": datetime}
        self.devices: dict[str, dict] = {}
        self._store: Store[dict] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.devices"
        )

    # ------------------------------------------------------------------ storage

    async def async_load(self) -> None:
        """Load tracked devices' last IP + last seen so a restart doesn't mark them away."""
        try:
            data = await self._store.async_load() or {}
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Couldn't load saved WiFi Presence data, starting fresh")
            return
        for mac, saved in data.get("devices", {}).items():
            if mac not in self._tracked:
                continue
            last_seen = dt_util.parse_datetime(saved.get("last_seen") or "")
            if last_seen is None:
                continue
            self.devices[mac] = {
                "ip": saved.get("ip"),
                "hostname": saved.get("hostname"),
                "last_seen": last_seen,
            }

    def _data_to_save(self) -> dict:
        return {
            "devices": {
                mac: {
                    "ip": dev.get("ip"),
                    "hostname": dev.get("hostname"),
                    "last_seen": dev["last_seen"].isoformat(),
                }
                for mac, dev in self.devices.items()
                if mac in self._tracked
            }
        }

    async def async_save_now(self) -> None:
        await self._store.async_save(self._data_to_save())

    # ------------------------------------------------------------------ helpers

    def _read_arp(self) -> dict[str, str]:
        """Return {mac: ip} for every resolved entry in our subnet."""
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
            try:
                complete = int(flags, 16) & 0x2
            except ValueError:
                continue
            if not complete or mac == "00:00:00:00:00:00":
                continue
            try:
                if ipaddress.ip_address(ip) not in self._network:
                    continue
            except ValueError:
                continue
            found[mac.lower()] = ip
        return found

    @staticmethod
    def _udp_blast(ips: list[str], ports: tuple[int, ...]) -> None:
        """Fire one tiny UDP packet per ip/port. Each one forces an ARP lookup."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1048576)
        except OSError:
            pass
        try:
            for ip in ips:
                for port in ports:
                    try:
                        sock.sendto(b"\x00", (ip, port))
                    except OSError:
                        pass
        finally:
            sock.close()

    @staticmethod
    def _tcp_poke(ips: list[str], wait: float) -> set[str]:
        """Start TCP connects to wake phones, wait up to `wait` seconds.

        Returns the IPs that answered (open or refused both mean it's awake).
        Always takes the full `wait` so the ARP lookups have time to finish.
        """
        deadline = time.monotonic() + wait
        alive: set[str] = set()
        sel = selectors.DefaultSelector()
        try:
            for ip in ips:
                for port in TCP_PROBE_PORTS:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.setblocking(False)
                    try:
                        s.connect_ex((ip, port))
                        sel.register(s, selectors.EVENT_WRITE, ip)
                    except OSError:
                        s.close()
            while sel.get_map():
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                for key, _ in sel.select(timeout=left):
                    sock = key.fileobj
                    err = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                    if err in _ALIVE_ERRNOS:
                        alive.add(key.data)
                    sel.unregister(sock)
                    sock.close()
        finally:
            for key in list(sel.get_map().values()):
                try:
                    key.fileobj.close()
                except OSError:
                    pass
            sel.close()
        left = deadline - time.monotonic()
        if left > 0:
            time.sleep(left)
        return alive

    # --------------------------------------------------------------------- scan

    def _scan(self, tracked_ips: dict[str, str]) -> dict[str, str]:
        """Blocking scan. Returns {mac: ip} for everything seen this scan.

        1. Sweep the whole subnet (finds new devices / new IPs).
        2. At the same time, hit tracked devices' last IPs on phone-waking ports.
        3. Any tracked device still missing gets up to RETRY_ROUNDS more tries.
        Seen in ANY round = seen.
        """
        targets = sorted(set(tracked_ips.values()))
        self._udp_blast(self._hosts, (9,))
        self._udp_blast(targets, UDP_PROBE_PORTS)
        self._tcp_poke(targets, FIRST_WAIT)
        found = self._read_arp()

        for _ in range(RETRY_ROUNDS):
            missing = sorted(
                {ip for mac, ip in tracked_ips.items() if mac not in found and ip}
            )
            if not missing:
                break
            self._udp_blast(missing, UDP_PROBE_PORTS)
            self._tcp_poke(missing, RETRY_WAIT)
            found.update(self._read_arp())

        return found

    @staticmethod
    def _lookup(ip: str) -> str:
        try:
            return socket.gethostbyaddr(ip)[0].split(".")[0]
        except (OSError, socket.herror, socket.gaierror):
            return ""

    async def _async_update_data(self) -> dict:
        tracked_ips = {
            mac: dev["ip"]
            for mac, dev in self.devices.items()
            if mac in self._tracked and dev.get("ip")
        }
        try:
            found = await self.hass.async_add_executor_job(self._scan, tracked_ips)
        except Exception:  # noqa: BLE001 - a bad scan must never mark people away
            _LOGGER.exception("WiFi scan failed, keeping last known states")
            return self.devices

        now = dt_util.utcnow()
        new_macs = []
        for mac, ip in found.items():
            dev = self.devices.get(mac)
            if dev is None:
                dev = self.devices[mac] = {"ip": ip, "hostname": None, "last_seen": now}
            if dev.get("hostname") is None:
                new_macs.append(mac)
            dev["ip"] = ip
            dev["last_seen"] = now

        missed = [m for m in self._tracked if m not in found]
        if missed:
            _LOGGER.debug("Tracked devices that didn't answer this scan: %s", missed)

        if new_macs:
            names = await asyncio.gather(
                *(
                    self.hass.async_add_executor_job(self._lookup, self.devices[m]["ip"])
                    for m in new_macs
                )
            )
            for mac, name in zip(new_macs, names):
                # "" means looked up with no result; don't keep retrying every scan.
                self.devices[mac]["hostname"] = name or ""

        self._store.async_delay_save(self._data_to_save, SAVE_DELAY)
        return self.devices
