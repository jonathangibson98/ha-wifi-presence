"""Scans the network and combines WiFi, Bluetooth and linked entities per device."""
from __future__ import annotations

import asyncio
import errno
import ipaddress
import logging
import selectors
import socket
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_HOME, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    BLE_PUSH_THROTTLE,
    CONF_BLUETOOTH,
    CONF_CONSIDER_HOME,
    CONF_ENTITIES,
    CONF_IRK,
    CONF_LINKS,
    CONF_SCAN_INTERVAL,
    CONF_SUBNET,
    CONF_TRACKED,
    DEFAULT_CONSIDER_HOME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SUBNET,
    DOMAIN,
    FAST_AWAY_SECONDS,
    MAX_BLE_CHOICES,
    SOURCE_BLUETOOTH,
    SOURCE_ENTITY,
    SOURCE_WIFI,
)
from .helpers import (
    ble_address,
    is_ble_key,
    is_resolvable_private,
    normalize_ble_address,
    parse_irk,
)

_LOGGER = logging.getLogger(__name__)
ARP_FILE = "/proc/net/arp"
STORAGE_VERSION = 1
SAVE_DELAY = 60  # seconds; batches disk writes instead of writing every scan
RPA_CACHE_MAX = 4096

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
    """Sweep the subnet, listen for Bluetooth, watch linked entities, combine them.

    A tracked device ("key") is either a WiFi MAC or a Bluetooth-only device
    ("ble:<address>"). It is home when ANY of its signals has seen it recently:
      - wifi:      answered the network scan within "stay home" seconds
      - bluetooth: its Bluetooth advert was heard within "stay home" seconds
      - entity:    a linked entity (Companion app tracker, etc.) says home right now
    """

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
        self._consider_home: int = entry.options.get(CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME)

        # key -> {"ip": str | None, "hostname": str | None,
        #         "seen": {"wifi": datetime, "bluetooth": datetime}}
        self.devices: dict[str, dict] = {}
        self._store: Store[dict] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.devices"
        )

        # Extra signals, read from the options.
        self._ble_static: dict[str, str] = {}  # BLE address -> tracked key
        self._ble_irks: dict[str, bytes] = {}  # tracked key -> IRK bytes
        self._ble_ciphers: list[tuple[str, Any]] = []
        self._resolve_fn: Any = None
        self._rpa_cache: dict[str, str | None] = {}
        self._link_entities: dict[str, list[str]] = {}
        self._last_push: dict[str, Any] = {}
        self._unsubs: list[Any] = []
        self._load_links(hass, entry)

    def _load_links(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        # Bluetooth-only devices are heard by their own address.
        for key in self._tracked:
            if is_ble_key(key):
                self._ble_static[ble_address(key)] = key

        registry = er.async_get(hass)
        for raw_key, link in (entry.options.get(CONF_LINKS) or {}).items():
            key = raw_key.lower()
            if key not in self._tracked:
                continue
            address = normalize_ble_address(link.get(CONF_BLUETOOTH) or "")
            if address:
                self._ble_static[address] = key
            irk = parse_irk(link.get(CONF_IRK) or "")
            if irk:
                self._ble_irks[key] = irk
            entities = []
            for entity_id in link.get(CONF_ENTITIES) or []:
                reg = registry.async_get(entity_id)
                # Never link our own trackers back into ourselves.
                if reg is not None and reg.platform == DOMAIN:
                    continue
                entities.append(entity_id)
            if entities:
                self._link_entities[key] = entities

    # ------------------------------------------------------------------ lifecycle

    @callback
    def async_start(self) -> None:
        """Start listening for Bluetooth adverts and linked entity changes."""
        self._start_entity_tracking()
        self._start_bluetooth()

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    def _start_entity_tracking(self) -> None:
        entity_ids = sorted({e for ids in self._link_entities.values() for e in ids})
        if not entity_ids:
            return
        self._unsubs.append(
            async_track_state_change_event(
                self.hass, entity_ids, self._async_linked_entity_changed
            )
        )

    @callback
    def _async_linked_entity_changed(self, event: Event) -> None:
        self.async_update_listeners()

    def _start_bluetooth(self) -> None:
        if not self._ble_static and not self._ble_irks:
            return
        if "bluetooth" not in self.hass.config.components:
            _LOGGER.warning(
                "A device uses Bluetooth but the Bluetooth integration isn't "
                "set up, so Bluetooth is skipped"
            )
            return
        try:
            from homeassistant.components import bluetooth
            from homeassistant.components.bluetooth import (
                BluetoothCallbackMatcher,
                BluetoothScanningMode,
            )
        except ImportError:
            _LOGGER.warning("Bluetooth isn't available, so Bluetooth is skipped")
            return

        if self._ble_irks:
            try:
                from bluetooth_data_tools import (
                    get_cipher_for_irk,
                    resolve_private_address,
                )
            except ImportError:
                _LOGGER.warning("IRK matching isn't available, so IRKs are skipped")
            else:
                self._resolve_fn = resolve_private_address
                self._ble_ciphers = [
                    (key, get_cipher_for_irk(irk)) for key, irk in self._ble_irks.items()
                ]

        try:
            if self._ble_ciphers:
                # Private addresses change, so we have to look at every advert.
                matchers = [BluetoothCallbackMatcher(connectable=False)]
            else:
                matchers = [
                    BluetoothCallbackMatcher(address=address, connectable=False)
                    for address in self._ble_static
                ]
            for matcher in matchers:
                self._unsubs.append(
                    bluetooth.async_register_callback(
                        self.hass,
                        self._async_ble_advert,
                        matcher,
                        BluetoothScanningMode.PASSIVE,
                    )
                )
            # Pick up devices Bluetooth already heard before we started.
            now = time.monotonic()
            for info in bluetooth.async_discovered_service_info(self.hass, False):
                key = self._match_ble(info.address)
                if key is None:
                    continue
                age = max(0.0, now - info.time)
                if age <= self._consider_home:
                    self._record_ble(key, age, notify=False, name=info.name)
        except Exception:  # noqa: BLE001 - Bluetooth trouble must never break WiFi
            _LOGGER.exception("Couldn't start Bluetooth tracking, using WiFi only")

    # ------------------------------------------------------------------ bluetooth

    def discovered_bluetooth(self) -> list[dict]:
        """Bluetooth devices heard right now, for the options screen.

        Rotating private addresses are left out: they can't be tracked by
        address (use an IRK on the phone's WiFi device instead).
        """
        if "bluetooth" not in self.hass.config.components:
            return []
        try:
            from homeassistant.components import bluetooth

            infos = list(bluetooth.async_discovered_service_info(self.hass, False))
        except Exception:  # noqa: BLE001
            return []
        found: dict[str, dict] = {}
        for info in infos:
            address = info.address.upper()
            if is_resolvable_private(address):
                continue
            name = info.name or ""
            if name.upper() == address:
                name = ""
            found[address] = {"address": address, "name": name, "rssi": info.rssi}
        out = sorted(
            found.values(),
            key=lambda d: (not d["name"], -(d["rssi"] if d["rssi"] is not None else -127)),
        )
        return out[:MAX_BLE_CHOICES]

    def _match_ble(self, address: str) -> str | None:
        """Which tracked device (if any) does this Bluetooth address belong to."""
        key = self._ble_static.get(address)
        if key is not None:
            return key
        if not self._ble_ciphers or self._resolve_fn is None:
            return None
        if address in self._rpa_cache:
            return self._rpa_cache[address]
        result = None
        if is_resolvable_private(address):
            for tracked_key, cipher in self._ble_ciphers:
                if self._resolve_fn(cipher, address):
                    result = tracked_key
                    break
        if len(self._rpa_cache) >= RPA_CACHE_MAX:
            self._rpa_cache.clear()
        self._rpa_cache[address] = result
        return result

    @callback
    def _async_ble_advert(self, service_info: Any, change: Any) -> None:
        key = self._match_ble(service_info.address)
        if key is not None:
            self._record_ble(key, name=service_info.name)

    @callback
    def _record_ble(
        self, key: str, age: float = 0.0, notify: bool = True, name: str | None = None
    ) -> None:
        now = dt_util.utcnow()
        seen_at = now - timedelta(seconds=age)
        was_home = self.status(key)["connected"]
        dev = self.devices.setdefault(key, {"ip": None, "hostname": None, "seen": {}})
        # Bluetooth-only devices take their name from Bluetooth.
        if (
            is_ble_key(key)
            and not dev.get("hostname")
            and name
            and name.upper() != ble_address(key)
        ):
            dev["hostname"] = name
        previous = dev["seen"].get(SOURCE_BLUETOOTH)
        if previous is None or seen_at > previous:
            dev["seen"][SOURCE_BLUETOOTH] = seen_at
        if not notify:
            return
        last_push = self._last_push.get(key)
        if (
            not was_home
            or last_push is None
            or (now - last_push).total_seconds() >= BLE_PUSH_THROTTLE
        ):
            self._last_push[key] = now
            # Not async_set_updated_data: that would restart the scan timer on
            # every advert and the WiFi scan would never run.
            self.async_update_listeners()

    # ------------------------------------------------------------ combined state

    def _entity_votes(self, key: str) -> tuple[bool, bool]:
        """(any linked entity says home, any linked entity clearly says away)."""
        home = away = False
        for entity_id in self._link_entities.get(key, []):
            state = self.hass.states.get(entity_id)
            if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                continue
            if state.state in (STATE_HOME, STATE_ON):
                home = True
            else:
                away = True
        return home, away

    def status(self, key: str) -> dict:
        """Combine every signal into one answer for a tracked device.

        Returns {"connected": bool, "sources": [str], "last_seen": datetime | None}.
        Home if ANY signal is fresh. Away only when ALL of them have gone quiet.
        """
        window = self._consider_home
        entity_home, entity_away = self._entity_votes(key)
        if entity_away and not entity_home:
            # The phone itself says it left, so we can stop waiting sooner.
            window = min(window, FAST_AWAY_SECONDS)

        now = dt_util.utcnow()
        sources: list[str] = []
        last_seen = None
        dev = self.devices.get(key)
        for source, seen_at in (dev["seen"] if dev else {}).items():
            if last_seen is None or seen_at > last_seen:
                last_seen = seen_at
            if (now - seen_at).total_seconds() <= window:
                sources.append(source)
        if entity_home:
            sources.append(SOURCE_ENTITY)
        return {
            "connected": bool(sources),
            "sources": sorted(sources),
            "last_seen": last_seen,
        }

    # ------------------------------------------------------------------ storage

    async def async_load(self) -> None:
        """Load tracked devices' last IP + last seen so a restart doesn't mark them away."""
        try:
            data = await self._store.async_load() or {}
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Couldn't load saved WiFi Presence data, starting fresh")
            return
        for key, saved in data.get("devices", {}).items():
            if key not in self._tracked:
                continue
            seen: dict = {}
            for source, value in (saved.get("seen") or {}).items():
                parsed = dt_util.parse_datetime(value or "")
                if parsed is not None:
                    seen[source] = parsed
            # Older versions saved a single last_seen, which was always WiFi.
            legacy = dt_util.parse_datetime(saved.get("last_seen") or "")
            if legacy is not None and SOURCE_WIFI not in seen:
                seen[SOURCE_WIFI] = legacy
            if not seen:
                continue
            self.devices[key] = {
                "ip": saved.get("ip"),
                "hostname": saved.get("hostname"),
                "seen": seen,
            }

    def _data_to_save(self) -> dict:
        return {
            "devices": {
                key: {
                    "ip": dev.get("ip"),
                    "hostname": dev.get("hostname"),
                    "seen": {s: ts.isoformat() for s, ts in dev["seen"].items()},
                }
                for key, dev in self.devices.items()
                if key in self._tracked and dev.get("seen")
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
        # Only WiFi devices have an IP to poke. Bluetooth-only devices are skipped.
        tracked_ips = {
            key: dev["ip"]
            for key, dev in self.devices.items()
            if key in self._tracked and not is_ble_key(key) and dev.get("ip")
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
                dev = self.devices[mac] = {"ip": ip, "hostname": None, "seen": {}}
            if dev.get("hostname") is None:
                new_macs.append(mac)
            dev["ip"] = ip
            dev["seen"][SOURCE_WIFI] = now

        for key in self._tracked:
            if key in found or is_ble_key(key):
                continue
            state = self.status(key)
            if state["connected"]:
                _LOGGER.debug(
                    "%s didn't answer the WiFi scan but is still home via %s",
                    key,
                    state["sources"],
                )
            else:
                _LOGGER.debug("%s didn't answer the WiFi scan and is away", key)

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
