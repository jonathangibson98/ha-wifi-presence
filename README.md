<p align="center">
  <img src="https://raw.githubusercontent.com/jonathangibson98/ha-wifi-presence/main/custom_components/wifi_presence/brand/logo.png" alt="WiFi Presence" width="420">
</p>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=jonathangibson98&repository=ha-wifi-presence&category=integration">
    <img src="https://my.home-assistant.io/badges/hacs_repository.svg" alt="Open in HACS">
  </a>
</p>

# WiFi Presence

A Home Assistant integration that finds the devices on your WiFi and the devices Home Assistant can hear over Bluetooth, and turns the ones you pick into `device_tracker` entities. A device is **home** when it's seen and **not_home** when it's not.

Each device can use **just WiFi, just Bluetooth, or both**, so devices that only show up over Bluetooth (watches, tags, bands) are tracked too. Add **other trackers** (like the Companion app) as extra signals so one sleepy signal doesn't cause a false "away".

Built for **Google WiFi / Nest WiFi**, which has no local API and no client list. It also works on any other router.

## How it works

Every scan, the integration sends a tiny packet to each address in your subnet, which makes the OS ask "who has this IP?" (ARP). Every device on WiFi has to answer that, even phones that ignore pings. It then reads the ARP table to see who answered. No router login, no cloud, no extra software.

Devices you track get extra attention: they're poked on ports that wake sleeping phones (mDNS and Apple's 62078), and if they still don't answer they get up to 3 more tries in the same scan. Last-seen times survive restarts.

Bluetooth comes from Home Assistant's own Bluetooth integration (a local adapter or ESPHome / Shelly Bluetooth proxies). Adverts are heard as they happen, so Bluetooth devices update right away.

### Three kinds of tracked device

| You pick | It is tracked by | Good for |
|---|---|---|
| A **WiFi** device | WiFi scan | Phones, laptops, TVs, anything on your network |
| A **Bluetooth** device | Its Bluetooth address | Watches, tags, bands, anything that has no WiFi |
| A WiFi device **+ Bluetooth/other signals** | All of them together | Phones you want to be extra reliable |

### Combining signals

Each tracked device can use up to three signals:

| Signal | Counts as home when |
|---|---|
| WiFi | It answered a scan within "Stay home after last seen" |
| Bluetooth | Its Bluetooth advert was heard within "Stay home after last seen" |
| Linked entity | A linked tracker or binary sensor says `home` / `on` right now |

**Home if ANY signal says home. Away only when ALL of them have gone quiet.** Bluetooth adverts and linked entity changes update the tracker right away, so arriving is fast.

For leaving: if a linked tracker clearly says the device left (for example the Companion app says `not_home`) and WiFi and Bluetooth haven't seen it either, the tracker goes away after 3 minutes instead of waiting the full "stay home" time. If nothing is linked, only the "stay home" time is used.

The tracker's `connected_via` attribute shows which signals currently say home.

## Requirements

- Home Assistant 2024.12 or newer (2026.3+ for the icons and logos to show)
- Home Assistant must be on the same network as the devices (HAOS and Container with host networking both work)
- Bluetooth is optional. It needs the Home Assistant **Bluetooth** integration set up, with a local adapter or an ESPHome / Shelly Bluetooth proxy that can hear the device.

## Install with HACS

1. HACS → three-dot menu → **Custom repositories**.
2. Add `https://github.com/jonathangibson98/ha-wifi-presence`, category **Integration**.
3. Find **WiFi Presence** in HACS, download it, and **restart Home Assistant**.
4. Settings → Devices & Services → **Add Integration** → **WiFi Presence**.

### Manual install

Copy `custom_components/wifi_presence` into your `config/custom_components/` folder and restart.

## Setup

1. Keep the defaults if you use Google WiFi (`192.168.86.0/24`, scan every 30 seconds). Change the subnet if your router uses a different one.
2. Click **Configure** on the integration, then **Devices and scan settings**.
3. Tick the devices you want to track. The list has both kinds:
   - `WiFi - name - IP - MAC`
   - `Bluetooth - name - address (signal strength)`
4. Submit. Your `device_tracker` entities appear right away. Rename them in the UI.

Not listed? Wait a minute and reopen Configure (WiFi devices need to be on the network, Bluetooth devices in range of an adapter or proxy). You can also type a WiFi MAC or a Bluetooth address to add a device that isn't online right now.

Phones that rotate their Bluetooth address aren't in the Bluetooth list, because an address that keeps changing can't be tracked. Track the phone's WiFi entry and give it an IRK (below).

### Remove devices you don't use

Click **Configure** → **Remove devices you don't use**, tick the ones you want gone and submit. They stop being tracked and their entities are deleted from Home Assistant, together with their names and extra signals. Unticking a device in **Devices and scan settings** does the same. Anything still on your network can be added back later.

### Use WiFi and Bluetooth together for one device (optional)

Track the device's WiFi entry, save, then click **Configure** → **Add Bluetooth or other signals to a device**, pick the device, and fill in any of these:

- **Bluetooth device**: pick it from the list of what Home Assistant hears, or type an address like `AA:BB:CC:DD:EE:FF`. For things with a fixed address, like a smartwatch, band or tag.
- **Bluetooth IRK**: for phones. iPhones and most Androids rotate their Bluetooth address every few minutes. An IRK lets the integration recognise the phone no matter which address it uses. It takes the same formats as Home Assistant's **Private BLE Device** integration (32 hex characters, or the base64 form ending in `=`). Follow that integration's docs to get your phone's IRK.
- **Other trackers or sensors**: pick things like the Companion app's `device_tracker`, or a `binary_sensor` that is `on` when the person is home. Don't pick this integration's own trackers (they're ignored if you do).

A bonus: an IRK keeps working even if the phone's WiFi MAC changes.

## Options

| Option | What it does | Default |
|---|---|---|
| Network to scan | Subnet in CIDR form | `192.168.86.0/24` |
| Scan every | Seconds between WiFi scans | `30` |
| Stay home after last seen | Seconds a device stays "home" after WiFi or Bluetooth last saw it | `600` |
| Add WiFi device by MAC | Track a WiFi device that isn't online right now | empty |
| Add Bluetooth device by address | Track a Bluetooth device that isn't in range right now | empty |

## Phones: turn off Private Wi-Fi Address

iPhones and many Androids use a random MAC per network, and it can change. A changed MAC looks like a new device. For your home WiFi:

- **iPhone:** Settings → Wi-Fi → (i) next to your network → turn **Private Wi-Fi Address** off.
- **Android:** Wi-Fi settings → your network → Privacy → **Use device MAC**.

## Tips and limits

- Phones in deep sleep can still miss WiFi scans. Adding Bluetooth (IRK) or the Companion app tracker is the best fix. You can also raise **Stay home after last seen** (600–900 works well for iPhones).
- Bluetooth only covers where your adapter or proxies can hear. A Bluetooth-only device that leaves range goes away after the "stay home" time, so a small adapter range means more false "away". Add a proxy near the door or where the device lives.
- Many Bluetooth devices only advertise now and then, so give Bluetooth-only devices a longer "stay home" time if they flap.
- iPhone: set **Private Wi-Fi Address** to **Off**, not "Fixed" or "Rotating". Rotating changes the MAC and the tracker loses the phone.
- To see misses, turn on debug logging for `custom_components.wifi_presence`.
- In Google Home, reserve an IP for each tracked device to keep the list tidy.
- Only devices in the scanned subnet are seen over WiFi. Guest and IoT networks are separate subnets.
- This shows if a device is around, not where it is. Use the Companion app for GPS.

## Troubleshooting

- **No devices listed:** check the subnet, then check the log for `wifi_presence`.
- **No Bluetooth devices listed:** check that the Bluetooth integration is set up and an adapter or proxy is in range.
- **Everything shows away:** Home Assistant may be in an isolated container without host networking.
- **Bluetooth never shows up in `connected_via`:** check that the Bluetooth integration is set up and that a Home Assistant Bluetooth adapter or proxy is near the device. For an IRK, check it's for the right phone.
- **Icons missing:** needs Home Assistant 2026.3+. Restart and hard-refresh the browser.

## License

MIT
