"""Constants for the Network Quality integration."""

DOMAIN = "network_quality"

CONF_ISP = "isp"
CONF_ROUTER_TYPE = "router_type"
CONF_DOWNLOAD_MIN = "download_min"
CONF_DOWNLOAD_NORMAL = "download_normal"
CONF_DOWNLOAD_MAX = "download_max"
CONF_UPLOAD_MIN = "upload_min"
CONF_UPLOAD_NORMAL = "upload_normal"
CONF_UPLOAD_MAX = "upload_max"

CONF_REGION = "region"
CONF_SPEEDTEST_INTERVAL = "speedtest_interval"
CONF_PING_INTERVAL = "ping_interval"
CONF_STATUS_INTERVAL = "status_interval"
CONF_EXTERNAL_OPT_IN = "external_opt_in"
CONF_TEST_TARGETS = "test_targets"
CONF_SERVICE_STATUSES = "service_statuses"
CONF_AGENT_URL = "agent_url"

DEFAULT_SPEEDTEST_INTERVAL = 900
DEFAULT_PING_INTERVAL = 60
DEFAULT_STATUS_INTERVAL = 300
DEFAULT_EXTERNAL_OPT_IN = False
DEFAULT_REGION = ""
DEFAULT_AGENT_URL = ""

DEFAULT_TEST_TARGETS = [
    "1.1.1.1",
    "8.8.8.8",
    "9.9.9.9",
    "https://example.com",
]

AVAILABLE_SERVICE_CATALOG = [
    "amazon",
    "google",
    "microsoft",
    "netflix",
    "spotify",
    "discord",
    "whatsapp",
    "openai",
    "claude",
    "github",
    "youtube",
]

DATA_COORDINATOR = "coordinator"

SERVICE_EXPORT_REPORT = "export_report"
SERVICE_INSTALL_DASHBOARD = "install_dashboard"

ATTR_OUTPUT_PATH = "output_path"
ATTR_INCLUDE_RAW = "include_raw"

UPDATE_TIMEOUT_SECONDS = 10
