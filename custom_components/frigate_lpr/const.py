"""Constants for Frigate LPR Registry."""

DOMAIN = "frigate_lpr"
PLATFORMS = ["sensor", "select"]
CARD_RESOURCE_PATH = "/frigate_lpr/frigate-lpr-card.js"
CARD_URL = f"{CARD_RESOURCE_PATH}?v=1.12.1"
STATIC_URL_PATH = "/frigate_lpr"

CONF_TOPIC = "topic"
CONF_CAMERA = "camera"
CONF_FREQUENT_OBSERVATIONS = "frequent_observations"
CONF_FREQUENT_DAYS = "frequent_days"
CONF_MOTORAPI_ENABLED = "motorapi_enabled"
CONF_MOTORAPI_KEY = "motorapi_key"
CONF_SNAPSHOTS_ENABLED = "snapshots_enabled"
CONF_SNAPSHOT_ENTITY = "snapshot_entity"
CONF_SPEED_ENABLED = "speed_enabled"
CONF_EVENTS_TOPIC = "events_topic"
CONF_SPEED_LIMIT = "speed_limit"
CONF_SPEED_UNIT = "speed_unit"
CONF_NOTIFY_SERVICE_1 = "notify_service_1"
CONF_NOTIFY_SERVICE_2 = "notify_service_2"
CONF_NOTIFY_CRITICAL = "notify_critical"
CONF_NOTIFY_SPEEDING = "notify_speeding"

DEFAULT_TOPIC = "frigate/tracked_object_update"
DEFAULT_FREQUENT_OBSERVATIONS = 10
DEFAULT_FREQUENT_DAYS = 4
DEFAULT_MOTORAPI_ENABLED = False
DEFAULT_SNAPSHOTS_ENABLED = False
DEFAULT_SPEED_ENABLED = True
DEFAULT_EVENTS_TOPIC = "frigate/events"
DEFAULT_SPEED_LIMIT = 50
DEFAULT_SPEED_UNIT = "kmh"
DEFAULT_NOTIFY_CRITICAL = False
DEFAULT_NOTIFY_SPEEDING = False

SNAPSHOT_API_PATH = "/api/frigate_lpr/snapshot/{plate}"

MOTORAPI_URL = "https://v1.motorapi.dk/vehicles/{plate}"
MOTORAPI_SEARCH_URL = "https://v1.motorapi.dk/vehicles"

SIGNAL_UPDATE = f"{DOMAIN}_update"
SIGNAL_NEW_PLATE = f"{DOMAIN}_new_plate"

SERVICE_SET_PLATE = "set_plate"
SERVICE_REMOVE_PLATE_METADATA = "remove_plate_metadata"
SERVICE_LOOKUP_VEHICLE = "lookup_vehicle"
SERVICE_UPDATE_OBSERVATION = "update_observation"
SERVICE_REMOVE_OBSERVATION = "remove_observation"
SERVICE_REMOVE_SNAPSHOT = "remove_snapshot"
