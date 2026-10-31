<p align="center">
  <img src="https://raw.githubusercontent.com/jonathangibson98/ha-wifi-presence/main/custom_components/wifi_presence/brand/logo.png" alt="WiFi Presence" width="420">
</p>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=jonathangibson98&repository=ha-wifi-presence&category=integration">
    <img src="https://my.home-assistant.io/badges/hacs_repository.svg" alt="Open in HACS">
  </a>
</p>

# WiFi Presence

A Home Assistant integration that finds the devices on your WiFi and turns the ones you pick into `device_tracker` entities. A device is **home** when it's on your network and **not_home** when it's not.

Built for **Google WiFi / Nest WiFi**, which has no local API and no client list. It also works on any other router.

## How it works

Every scan, the integration sends a tiny packet to each address in your subnet, which makes the OS ask "who has this IP?" (ARP). Every device on WiFi has to answer that, even phones that ignore pings. It then reads the ARP table to see who answered. No router login, no cloud, no extra software.

## Requirements

- Home Assistant 2024.12 or newer (2026.3+ for the icons and logos to show)
- Home Assistant must be on the same network as the devices (HAOS and Container with host networking both work)

## Install with HACS

1. HACS → three-dot menu → **Custom repositories**.
2. Add `https://github.com/jonathangibson98/ha-wifi-presence`, category **Integration**.
3. Find **WiFi Presence** in HACS, download it, and **restart Home Assistant**.
4. Settings → Devices & Services → **Add Integration** → **WiFi Presence**.

### Manual install

Copy `custom_components/wifi_presence` into your `config/custom_components/` folder and restart.

## Setup

1. Keep the defaults if you use Google WiFi (`192.168.86.0/24`, scan every 30 seconds). Change the subnet if your router uses a different one.
2. Click **Configure** on the integration.
3. Tick the devices you want to track. Each one shows its name, IP and MAC. Not listed? Connect it to WiFi, wait a minute, and reopen Configure. You can also type its MAC address.
4. Submit. Your `device_tracker` entities appear right away. Rename them in the UI.

## Options

| Option | What it does | Default |
|---|---|---|
| Network to scan | Subnet in CIDR form | `192.168.86.0/24` |
| Scan every | Seconds between scans | `30` |
| Stay home after last seen | Seconds a device stays "home" after it stops answering | `180` |
| Add by MAC | Track a device that isn't online right now | empty |

## Phones: turn off Private Wi-Fi Address

iPhones and many Androids use a random MAC per network, and it can change. A changed MAC looks like a new device. For your home WiFi:

- **iPhone:** Settings → Wi-Fi → (i) next to your network → turn **Private Wi-Fi Address** off.
- **Android:** Wi-Fi settings → your network → Privacy → **Use device MAC**.

## Tips and limits

- Phones in deep sleep can miss a scan. If a device flaps, raise **Stay home after last seen**.
- In Google Home, reserve an IP for each tracked device to keep the list tidy.
- Only devices in the scanned subnet are seen. Guest and IoT networks are separate subnets.
- This shows if a device is on your WiFi, not where it is. Use the Companion app for GPS.

## Troubleshooting

- **No devices listed:** check the subnet, then check the log for `wifi_presence`.
- **Everything shows away:** Home Assistant may be in an isolated container without host networking.
- **Icons missing:** needs Home Assistant 2026.3+. Restart and hard-refresh the browser.

## License

MIT
