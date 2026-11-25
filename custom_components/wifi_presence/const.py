"""Constants for WiFi Presence."""

DOMAIN = "wifi_presence"

CONF_SUBNET = "subnet"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_CONSIDER_HOME = "consider_home"
CONF_TRACKED = "tracked"
CONF_MANUAL_MACS = "manual_macs"
CONF_MANUAL_BLE = "manual_bluetooth"
CONF_REMOVE = "remove"

# Your own names for devices, by key: {key: "Kitchen tablet"}
CONF_NAMES = "names"

# Extra signals, stored per tracked device: {key: {bluetooth, irk, entities}}
CONF_LINKS = "links"
CONF_BLUETOOTH = "bluetooth"
CONF_IRK = "irk"
CONF_ENTITIES = "entities"

DEFAULT_SUBNET = "192.168.86.0/24"  # Google WiFi default
DEFAULT_SCAN_INTERVAL = 30
DEFAULT_CONSIDER_HOME = 600  # iPhones can go quiet for several minutes

# A tracked device is identified by a "key":
#   - a WiFi MAC like aa:bb:cc:dd:ee:ff (WiFi device, can also be linked to Bluetooth)
#   - "ble:aa:bb:cc:dd:ee:ff" (Bluetooth-only device)
BLE_KEY_PREFIX = "ble:"
MAX_BLE_CHOICES = 150

# The signals that can say "this device is home".
SOURCE_WIFI = "wifi"
SOURCE_BLUETOOTH = "bluetooth"
SOURCE_ENTITY = "entity"

# If a linked entity (like the Companion app tracker) clearly says the device is
# away, and nothing else has seen it, don't wait the full "stay home" time.
FAST_AWAY_SECONDS = 180

# Bluetooth adverts can arrive many times a second. Only push a state update
# for them this often (a device coming home is always pushed right away).
BLE_PUSH_THROTTLE = 30
