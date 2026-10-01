"""Constants for Frigate LPR Registry."""

DOMAIN = "frigate_lpr"
PLATFORMS = ["sensor", "select"]
CARD_RESOURCE_PATH = "/frigate_lpr/frigate-lpr-card.js"
CARD_URL = f"{CARD_RESOURCE_PATH}?v=1.7.0"
STATIC_URL_PATH = "/frigate_lpr"

CONF_TOPIC = "topic"
CONF_CAMERA = "camera"
CONF_FREQUENT_OBSERVATIONS = "frequent_observations"
CONF_FREQUENT_DAYS = "frequent_days"
CONF_MOTORAPI_ENABLED = "motorapi_enabled"
CONF_MOTORAPI_KEY = "motorapi_key"
CONF_SNAPSHOTS_ENABLED = "snapshots_enabled"
CONF_FRIGATE_URL = "frigate_url"
CONF_FRIGATE_TOKEN = "frigate_token"
CONF_VERIFY_SSL = "verify_ssl"

DEFAULT_TOPIC = "frigate/tracked_object_update"
DEFAULT_FREQUENT_OBSERVATIONS = 10
DEFAULT_FREQUENT_DAYS = 4
DEFAULT_MOTORAPI_ENABLED = False
DEFAULT_SNAPSHOTS_ENABLED = False
DEFAULT_VERIFY_SSL = True

SNAPSHOT_API_PATH = "/api/frigate_lpr/snapshot/{plate}"

MOTORAPI_URL = "https://v1.motorapi.dk/vehicles/{plate}"

SIGNAL_UPDATE = f"{DOMAIN}_update"
SIGNAL_NEW_PLATE = f"{DOMAIN}_new_plate"

SERVICE_SET_PLATE = "set_plate"
SERVICE_REMOVE_PLATE_METADATA = "remove_plate_metadata"
SERVICE_LOOKUP_VEHICLE = "lookup_vehicle"
