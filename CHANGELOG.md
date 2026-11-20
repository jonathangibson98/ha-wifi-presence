# Changelog

## 1.4.0
- **Name your devices.** New **Name a device** option in the menu. Pick any device (WiFi or Bluetooth, tracked or not) and give it your own name, like "Kitchen tablet". The name becomes the tracker's name and shows in every list, so you stop guessing which MAC is which. Leave the name empty to clear it. Names are kept even if you stop tracking a device.
- **Easier to tell devices apart.** Every list now shows more:
  - WiFi: name, IP and MAC, plus "random MAC" for a phone or tablet using a private address.
  - Bluetooth: name, address, the maker (like Apple or Samsung) when Bluetooth says, and signal strength. Hold the device next to your adapter or proxy and the strongest signal is usually it.
- Devices without a name of yours are listed first when you pick one to name.

## 1.3.0
- **WiFi, Bluetooth, or both, per device.** The device picker now lists every WiFi device the scan found AND every Bluetooth device Home Assistant can hear. Pick any of them. A device that only shows up over Bluetooth (a watch, tag, earbuds case, fitness band) is tracked on its own with no WiFi needed. A WiFi-only device works as before.
- **Both together.** Track a device's WiFi entry, then use "Add Bluetooth or other signals to a device" to add its Bluetooth. The Bluetooth device is now picked from a list of what Home Assistant hears instead of typed in (typing still works).
- Bluetooth-only trackers take their name from the device's Bluetooth name and report `source_type: bluetooth`.
- You can also add a Bluetooth device by address in the options, even if it isn't in range right now.
- Rotating phone addresses are left out of the Bluetooth list (they can't be tracked by address). Use the phone's WiFi entry with its IRK instead.
- Existing WiFi trackers keep their entity IDs and settings.

## 1.2.0
- **Bluetooth.** Each tracked device can now be linked to a Bluetooth address (watches, tags, anything with a fixed address) or an IRK (phones that rotate their Bluetooth address). Works with the Bluetooth adapter on your Home Assistant machine and with ESPHome or Shelly Bluetooth proxies.
- **Other signals.** Each tracked device can also be linked to other trackers or binary sensors, like the Companion app's `device_tracker`. If one of them says home, the device is home.
- **One combined answer.** A device is home when ANY signal has seen it recently, and away only when all of them have gone quiet. Phones that sleep through a WiFi scan stay home if Bluetooth or the Companion app still sees them.
- **Faster, still safe, away.** If a linked tracker clearly says the device left and nothing else has seen it, it goes away after 3 minutes instead of the full "stay home" time.
- **Instant home.** Bluetooth adverts and linked entity changes update the tracker right away instead of waiting for the next scan.
- New attributes: `connected_via` (which signals say home), `wifi_last_seen` and `bluetooth_last_seen`. The last-seen attributes are kept out of the recorder database.
- Options now open to a menu: devices and scan settings, or add extra signals to a device.
- Saved last-seen data is now stored per signal. Data saved by 1.1.0 is still read.

## 1.1.0
- **Way fewer false "away" flips.** Tracked devices that don't answer the first sweep now get up to 3 more tries in the same scan.
- Tracked devices are also poked directly on ports that wake sleeping phones (mDNS 5353 and Apple's 62078), not just one generic packet.
- Restarting Home Assistant no longer marks everyone away. Last IP and last-seen time are saved and loaded back.
- A failed scan keeps the last known state instead of making trackers unavailable.
- Default "Stay home after last seen" raised from 180 to 600 seconds for new setups.
- New `last_seen` attribute on each tracker.

## 1.0.0
- First release.
- Scans a subnet and reads the ARP table to see which devices are on your WiFi.
- Creates a `device_tracker` entity for each device you pick.
- Options screen to pick devices, add a MAC by hand, change the subnet, scan interval and "stay home" time.
- Includes brand icons and logos (light and dark) for Home Assistant 2026.3+.
