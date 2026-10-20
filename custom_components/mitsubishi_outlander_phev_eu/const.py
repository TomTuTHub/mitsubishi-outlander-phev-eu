"""Constants for Mitsubishi Connect EU integration."""

DOMAIN = "mitsubishi_outlander_phev_eu"
PLATFORMS = ["sensor", "binary_sensor", "device_tracker", "switch", "button", "lock", "climate"]

# EU API Configuration
EU_AUTH_URL = "https://idm.prod.goa-eu.mitsubishi-motors.com/oauth/token"
EU_KINTARO_BASE = "https://kintaro.prod.goa-eu.mitsubishi-motors.com/prod"

# OAuth credentials (from APK v1.3.1)
EU_CLIENT_ID = "JzMQyXDcM5RcmVxZbzlMbPnyVhJaWiNe"
EU_CLIENT_SECRET = "KKEqZ1ko83ALOEKTejjjfNPRKmAYJjJI15UEDH3lvHtqfJggys5qR7nKrQT2epvz"

# Kintaro SDK credentials (from APK)
KINTARO_PKG_NAME = "com.mitsubishi_motors.mitsubishimotors"
KINTARO_APP_CODE = "202501100700475534942"
KINTARO_HASH = "EF453267190EA26C4B0A3EBE65E3F391"
KINTARO_SECURITY_KEY = "dd61b55d76c27f43"
KINTARO_JWT_SIGN = "dh7RqD9qTgRwqlHaidv3hYLP0BicgkR9"

REGION_EU = "eu"
REGION_US = "us"
REGION_JP = "jp"  # legacy id of the first JP beta build == Variante 1
REGION_JP_1 = "jp_1"
REGION_JP_2 = "jp_2"
REGION_JP_3 = "jp_3"  # entfernt (v1.1.0b3); alte Eintraege laufen als jp_1

# Per-region Kintaro/IDM profiles (EU and JP share the same protocol).
# EU values are byte-identical to the constants above.
# JP values: static analysis of the JP APK v3.1.0 (interchange_services_jp_prod.json,
# AndroidManifest, country_config.json). "kt_cfg" = the ten integers of the
# Kintaro security_key_settings: kt_cfg[0:2] AES key slice, [2:4]+[4:6]+[6:8] init
# signature slices of the second MD5, [8]/[9] nonce offset (EU: 15,31,18,22,0,13,1,5,7,7).
KINTARO_PROFILES = {
    REGION_EU: {
        "auth_url": EU_AUTH_URL,
        "kintaro_base": EU_KINTARO_BASE,
        "client_id": EU_CLIENT_ID,
        "client_secret": EU_CLIENT_SECRET,
        "pkg_name": KINTARO_PKG_NAME,
        "app_code": KINTARO_APP_CODE,
        "hash": KINTARO_HASH,
        "security_key": KINTARO_SECURITY_KEY,
        "jwt_sign": KINTARO_JWT_SIGN,
        "knt_region": "DE",
        "locale": "de_DE",
        "language": "de",
        "timezone": "Europe/Berlin",
        "app_version": "1.3.1",
        "kt_cfg": (15, 31, 18, 22, 0, 13, 1, 5, 7, 7),
    },
}

# --- Japan / Thailand: zwei Varianten fuer den Beta-Test (V3 entfaellt: scheiterte im Test) -----------------------
# Belegt (aus JP-APK 3.1.0, in allen Varianten gleich): Hosts, client_id/secret,
# app_code, jwt_sign, pkg_name, hash, security_key, App-Version, Locale/Sprache.
# Unbelegt sind nur zwei Dinge, die die Varianten abdecken:
#  (a) Zuordnung der 10 kt_cfg-Zahlen: AES-Slice [0:2] (Differenz 16 -> eindeutig),
#      Nonce-Offset [8]/[9] (identisch -> eindeutig). Offen ist nur, wie die drei
#      Init-Signatur-Paare [2:4],[4:6],[6:8] zu lesen sind. EU nutzt (Start, Ende),
#      aber JP (1,28) ergaebe 27 Zeichen statt 4 -> Variante 3 liest sie als
#      (Start, Laenge) statt (Start, Ende).
#  (b) Header knt-region: die App sendet sicher knt-region-code="jp"; ob zusaetzlich
#      knt-region="JP" mitgeht (EU: "DE"), ist nur vermutet -> Variante 2 laesst
#      knt-region weg.
# Die Zeitzone (Asia/Tokyo) bleibt in allen Varianten gleich: sie beeinflusst weder
# Init-Signatur noch Verschluesselung, und der Tester sitzt in dieser Zone.
# V1 = aktueller Stand (Basisannahme), V2 = nur Header anders.
_JP_BASE = {
    "auth_url": "https://idm.prod.goa.mitsubishi-motors.com/oauth/token",
    "kintaro_base": "https://kintaro.prod.goa.mitsubishi-motors.com/prod",
    "client_id": "Rn6WysiaR7xDrz39If3d3foQsuHLAjiw",
    "client_secret": "mZ6nfF2gsdpY8cqBJYKAQt0tKNexOBItEvNLkHclF2Sn3Egf3FwtYnCdSldLT8XE",
    "app_code": "202411201314294614109",
    "jwt_sign": "w0kJJQTMZgxFboq4sduXIsOcJwRaTjUI",
    # aus JP-APK 3.1.0 (AndroidManifest-Paket, interchange_services_jp_prod.json)
    "pkg_name": "com.mitsubishi_motors.mitsubishimotors",
    "hash": "EF453267190EA26C4B0A3EBE65E3F391",  # kintaro_hash, identisch zu EU
    # aus JP-APK 3.1.0: security_key_settings, gleiche Entschluesselung wie EU
    "security_key": "ba001f70172d159e",
    "kt_cfg": (13, 29, 1, 28, 8, 13, 7, 10, 3, 3),
    # aus JP-APK 3.1.0: country_config.json (JP und TH: regionCode "jp", isoLocale "ja-JP")
    "knt_region": "JP",
    "region_code": "jp",
    "user_country": "JP",
    "locale": "ja-JP",
    "language": "ja",
    "app_version": "3.1.0",
    # Die App sendet die Geraete-Zeitzone (TimeZone.getDefault); Asia/Tokyo ist eine Annahme
    "timezone": "Asia/Tokyo",
}

KINTARO_PROFILES[REGION_JP_1] = {**_JP_BASE, "variant": 1}
KINTARO_PROFILES[REGION_JP_2] = {**_JP_BASE, "variant": 2, "omit_headers": ("knt-region",)}
KINTARO_PROFILES[REGION_JP] = KINTARO_PROFILES[REGION_JP_1]  # alter Eintrag "jp" = Variante 1

# Kintaro API endpoints (from decompiled APK InterfaceC2646a.java)
# --- Init / Auth ---
EP_INIT = "/service/checkVersion"
EP_GENERATE_NONCE = "/remote/generateServerNonce/v1"
EP_VERIFY_PIN = "/vehicle/verifyPIN/v1"

# --- Vehicle Info (GET) ---
EP_VEHICLE_LIST = "/vehicle/getVehicleList/v1"
EP_USER_PROFILE = "/user/getProfile/v1"
EP_FIRMWARE_STATUS = "/vehicle/getFirmwareStatus/v1"
EP_FIRMWARE_UPGRADE_STATUS = "/vehicle/getFirmwareUpgradeStatus/v1"
EP_AVAILABLE_SERVICE = "/remote/getAvailableService/v1"

# --- Vehicle Status (GET) ---
EP_VSR = "/status/getVSR/v1"
EP_CHARGE_DETAILS = "/status/getChargeDetails/v1"
EP_CLIMATE_DETAILS = "/status/getClimateDetails/v1"
EP_ENGINE_DETAILS = "/status/getEngineDetails/v1"
EP_CHARGING_BASE_COST = "/status/getChargingBaseCost/v1"
EP_CHARGING_HISTORY = "/status/getChargingHistory/v1"
EP_MILEAGE_HISTORY = "/status/getMileageHistory/v1"

# --- Alerts (GET) ---
EP_GEOFENCE_ALERT = "/vehicle/getGeofenceAlert/v1"
EP_SPEED_ALERT = "/vehicle/getSpeedAlert/v1"
EP_CURFEW_ALERT = "/vehicle/getCurfewAlert/v1"
EP_NOTIFICATION_SETTING = "/vehicle/getNotificationSetting/v1"
EP_EMERGENCY_CONTACTS = "/vehicle/getEmergencyContacts/v1"

# --- Photo (GET) ---
EP_PHOTO_HISTORY_LIST = "/vehicle/getPhotoHistoryList/v1"
EP_PHOTO_HISTORY_DETAILS = "/vehicle/getPhotoHistoryDetails/v1"

# --- Remote Commands (POST) ---
EP_REFRESH_VSR = "/status/refreshVSR/v1"
EP_VEHICLE_LOCATION = "/remote/getVehicleLocation/v1"
EP_BATCH_REQUEST_STATUS = "/remote/getBatchRequestStatus/v1"
EP_START_CLIMATE = "/remote/startClimate/v1"
EP_STOP_CLIMATE = "/remote/stopClimate/v1"
EP_START_CHARGE = "/remote/startCharge/v1"
EP_STOP_CHARGE = "/remote/stopCharge/v1"
EP_LOCK_DOOR = "/remote/lockDoor/v1"
EP_UNLOCK_DOOR = "/remote/unlockDoor/v1"
EP_START_HORN = "/remote/startHorn/v1"
EP_START_LIGHT = "/remote/startLight/v1"
EP_START_ENGINE = "/remote/startEngine/v1"
EP_STOP_ENGINE = "/remote/stopEngine/v1"
EP_TAKE_PHOTO = "/remote/takePhoto/v1"
EP_SEND_POI = "/remote/sendPOI/v1"
EP_TRACKING_LOCATION = "/vehicle/trackingLocation/v1"

EP_UPDATE_CHARGING_BASE_COST = "/status/updateChargingBaseCost/v1"

# Config entry keys
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_PIN = "pin"
CONF_UPDATE_INTERVAL = "update_interval"

# Default values
DEFAULT_UPDATE_INTERVAL = 15  # minutes
MIN_UPDATE_INTERVAL = 5       # minutes

# Region selection (stored in the config entry; entries without it are EU)
CONF_REGION = "region"
# US (api_us.py) bleibt im Repo, ist aber nicht waehlbar: von niemandem bestaetigt.
REGIONS = [REGION_EU, REGION_JP_1, REGION_JP_2]
DEFAULT_REGION = REGION_EU

# US API (experimental). Values from the MIT-licensed public client
# https://github.com/pcartwright81/mitsubishi_connect_client
US_BASE_URL = "https://us-m.aerpf.com"
US_REMOTE_PORT = 15443
US_API_KEY = "3f5547161b5d4bdbbb2bf8b26c69d1de"
US_BASIC_AUTH = "Basic ZTU4NjUzY2QtMzkxOS00MjYxLWE1N2UtNWYyZjdjMjAwMGRhOmFtcENsaWVudFRydXN0ZWRTZWNyZXQ="

# Quelle (Status-Endpoint) je Entity-Key: faellt die Quelle technisch aus
# (Timeout/Netz/HTTP-Fehler), ist die Entity unavailable statt einen Scheinwert zu zeigen.
ENTITY_SOURCE = {
    **{k: "vsr" for k in (
        "ev_range", "total_range", "fuel_range", "odometer", "speed", "battery_12v",
        "tire_fl_pressure", "tire_fr_pressure", "tire_rl_pressure", "tire_rr_pressure",
        "doors_locked", "door_fl_open", "door_fr_open", "door_rl_open", "door_rr_open",
        "door_hood_open", "door_trunk_open", "window_fl_open", "window_fr_open",
        "window_rl_open", "window_rr_open", "window_sunroof_open", "headlights_on",
        "brake_warning", "engine_oil_warning", "mil_warning", "abs_warning", "airbag_warning")},
    **{k: "charge" for k in (
        "battery_level", "is_charging", "is_plugged_in", "charging_ready",
        "charge_disabled", "charging_remaining_time")},
    "target_temperature": "climate", "ac_on": "climate",
    "engine_on": "engine",
    "charging_base_cost": "cost",
    "firmware_version": "firmware",
    "last_trip_distance": "mileage", "last_trip_duration": "mileage",
    "last_charge_energy": "charging_history", "last_charge_duration": "charging_history",
}
