"""Constants for Frigate LPR Registry."""

DOMAIN = "frigate_lpr"
PLATFORMS = ["sensor", "select"]
DASHBOARD_URL_PATH = "frigate-lpr"

CONF_TOPIC = "topic"
CONF_CAMERA = "camera"
CONF_FREQUENT_OBSERVATIONS = "frequent_observations"
CONF_FREQUENT_DAYS = "frequent_days"

DEFAULT_TOPIC = "frigate/tracked_object_update"
DEFAULT_FREQUENT_OBSERVATIONS = 10
DEFAULT_FREQUENT_DAYS = 4

SIGNAL_UPDATE = f"{DOMAIN}_update"
SIGNAL_NEW_PLATE = f"{DOMAIN}_new_plate"

SERVICE_SET_PLATE = "set_plate"
SERVICE_REMOVE_PLATE_METADATA = "remove_plate_metadata"
