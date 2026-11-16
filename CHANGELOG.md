# Changelog

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
