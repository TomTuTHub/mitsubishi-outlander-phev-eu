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
