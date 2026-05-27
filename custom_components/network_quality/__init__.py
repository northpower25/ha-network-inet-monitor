"""The Network Quality integration."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
from datetime import UTC, date, datetime, time, timedelta

from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType
import voluptuous as vol

from .const import (
    ATTR_ENTRY_ID,
    ATTR_INCLUDE_RAW,
    ATTR_INSTANCE_ID,
    ATTR_OUTPUT_PATH,
    CONF_DASHBOARD_AUTO_EMITTED,
    DATA_COORDINATOR,
    DOMAIN,
    SERVICE_EXPORT_REPORT,
    SERVICE_INSTALL_DASHBOARD,
)
from .coordinator import NetworkQualityCoordinator

PLATFORMS: list[str] = ["sensor", "binary_sensor"]
_LOGGER = logging.getLogger(__name__)
_DASHBOARD_TEMPLATE_PATH = Path(__file__).parent / "dashboard" / "network_quality_dashboard.json"
_WWW_DIR = Path(__file__).parent / "www"
_ENTITY_DOMAIN_PREFIX = f"{DOMAIN}_"
_SUPPORTED_SENSOR_KEYS = {
    "internet_download",
    "internet_upload",
    "ping_public",
    "packet_loss",
    "jitter",
    "availability",
    "contract_ratio",
    "quality_score",
    "quality_class",
}
_SUPPORTED_BINARY_KEYS = {"internet_online"}
_PANEL_VERSION = "5"
_PANEL_FILENAME = "network-quality-panel.js"
_PANEL_URL_PATH = "network-quality-overview"
_PANEL_ELEMENT_NAME = "network-quality-panel"
_PANEL_ICON = "mdi:speedometer"


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Register sidebar panel and static assets for the integration dashboard."""
    if hass.data.get(f"{DOMAIN}_frontend_registered"):
        return

    module_url = f"/{DOMAIN}_local/{_PANEL_FILENAME}?v={_PANEL_VERSION}"

    try:
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    url_path=f"/{DOMAIN}_local",
                    path=str(_WWW_DIR),
                    cache_headers=False,
                )
            ]
        )
    except (ValueError, RuntimeError) as err:
        _LOGGER.debug(
            "Network Quality static frontend path registration failed or already exists: %s",
            err,
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.exception(
            "Unexpected error during Network Quality static path registration: %s",
            err,
        )

    try:
        from homeassistant.components.panel_custom import async_register_panel  # noqa: PLC0415
    except ImportError as err:
        _LOGGER.warning("panel_custom is unavailable, sidebar panel not registered: %s", err)
    else:
        try:
            await async_register_panel(
                hass,
                frontend_url_path=_PANEL_URL_PATH,
                webcomponent_name=_PANEL_ELEMENT_NAME,
                sidebar_title="Network Quality",
                sidebar_icon=_PANEL_ICON,
                module_url=module_url,
                embed_iframe=False,
                trust_external=False,
                require_admin=False,
            )
        except (ValueError, RuntimeError) as err:
            _LOGGER.debug(
                "Network Quality sidebar panel registration failed or already exists: %s",
                err,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception(
                "Unexpected error during Network Quality sidebar panel registration: %s",
                err,
            )

    hass.data[f"{DOMAIN}_frontend_registered"] = True


def _get_coordinator(
    hass: HomeAssistant,
    *,
    entry_id: str | None = None,
) -> NetworkQualityCoordinator | None:
    """Resolve a coordinator by entry id or default to the first configured instance."""
    domain_data = hass.data.get(DOMAIN, {})
    if entry_id:
        entry_data = domain_data.get(entry_id)
        if entry_data:
            return entry_data.get(DATA_COORDINATOR)
        return None

    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return None
    first = domain_data.get(entries[0].entry_id)
    if not first:
        return None
    return first.get(DATA_COORDINATOR)


def _parse_dashboard_date(value: str | None, *, end_of_day: bool = False) -> datetime | None:
    """Parse dashboard date filters."""
    if not value:
        return None
    try:
        parsed_date = date.fromisoformat(value)
    except ValueError as err:
        raise ValueError("Invalid date format: expected YYYY-MM-DD") from err
    return datetime.combine(
        parsed_date,
        time.max if end_of_day else time.min,
        tzinfo=UTC,
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/dashboard_data",
        vol.Optional("entry_id"): str,
        vol.Optional("start"): str,
        vol.Optional("end"): str,
        vol.Optional("interval", default="day"): vol.In(
            ["hour", "day", "week", "month", "quarter"]
        ),
    }
)
@websocket_api.async_response
async def websocket_dashboard_data(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, str],
) -> None:
    """Return aggregated dashboard analytics."""
    coordinator = _get_coordinator(hass, entry_id=msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Network Quality coordinator not found")
        return

    try:
        payload = coordinator.build_dashboard_payload(
            start=_parse_dashboard_date(msg.get("start")),
            end=_parse_dashboard_date(msg.get("end"), end_of_day=True),
            interval=msg.get("interval", "day"),
        )
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_date", str(err))
        return

    connection.send_result(msg["id"], payload)


async def _async_emit_dashboard_template(hass: HomeAssistant) -> None:
    """Emit the dashboard template event."""
    data = await hass.async_add_executor_job(_DASHBOARD_TEMPLATE_PATH.read_text, "utf-8")
    hass.bus.async_fire(f"{DOMAIN}_dashboard_ready", {"dashboard_json": data})


async def _async_install_dashboard(hass: HomeAssistant) -> bool:
    """Install dashboard views into the default Lovelace dashboard."""
    raw_data = await hass.async_add_executor_job(_DASHBOARD_TEMPLATE_PATH.read_text, "utf-8")

    try:
        dashboard_template = json.loads(raw_data)
    except json.JSONDecodeError:
        _LOGGER.exception("Failed to parse dashboard template JSON")
        return False

    lovelace_data = hass.data.get(LOVELACE_DATA)
    if lovelace_data is None:
        _LOGGER.warning("Lovelace data not available, dashboard install skipped")
        return False

    lovelace_dashboard = lovelace_data.dashboards.get(None)
    if lovelace_dashboard is None:
        _LOGGER.warning("Default Lovelace dashboard not available, dashboard install skipped")
        return False

    try:
        dashboard_config = await lovelace_dashboard.async_load(False)
    except HomeAssistantError:
        dashboard_config = {"views": []}

    config_views = dashboard_config.setdefault("views", [])
    if not isinstance(config_views, list):
        _LOGGER.warning("Default Lovelace dashboard has invalid views format")
        return False

    template_views = dashboard_template.get("views", [])
    if not isinstance(template_views, list):
        _LOGGER.warning("Dashboard template has invalid views format")
        return False

    existing_paths = {
        view.get("path") for view in config_views if isinstance(view, dict) and view.get("path")
    }
    new_views = [
        view
        for view in template_views
        if isinstance(view, dict) and view.get("path") not in existing_paths
    ]
    if not new_views:
        return True

    await lovelace_dashboard.async_save({**dashboard_config, "views": [*config_views, *new_views]})
    _LOGGER.info("Installed %d Network Quality dashboard view(s)", len(new_views))
    return True


async def _async_install_and_emit_dashboard(
    hass: HomeAssistant, entry: ConfigEntry | None = None
) -> bool:
    """Install dashboard views, emit template event and persist auto-install option."""
    if not await _async_install_dashboard(hass):
        return False

    await _async_emit_dashboard_template(hass)
    if entry and not entry.options.get(CONF_DASHBOARD_AUTO_EMITTED, False):
        hass.config_entries.async_update_entry(
            entry,
            options={**entry.options, CONF_DASHBOARD_AUTO_EMITTED: True},
        )
    return True


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up integration."""
    hass.data.setdefault(DOMAIN, {})
    await _async_register_frontend(hass)
    if not hass.data.get(f"{DOMAIN}_websocket_registered"):
        websocket_api.async_register_command(hass, websocket_dashboard_data)
        hass.data[f"{DOMAIN}_websocket_registered"] = True

    async def _async_export_report(call: ServiceCall) -> None:
        include_raw = call.data.get(ATTR_INCLUDE_RAW, False)
        output_path = call.data.get(ATTR_OUTPUT_PATH)
        target_entry_id = call.data.get(ATTR_INSTANCE_ID) or call.data.get(ATTR_ENTRY_ID)

        coordinator = _get_coordinator(hass, entry_id=target_entry_id)
        if coordinator is None:
            _LOGGER.warning("No config entry found for report export")
            return
        report_data = coordinator.build_report_payload(include_raw=include_raw)

        if output_path:
            path = Path(output_path)
            await hass.async_add_executor_job(
                path.write_text,
                coordinator.render_report_text(report_data),
                "utf-8",
            )
            _LOGGER.info("Network quality report exported to %s", path)
            return

        hass.bus.async_fire(f"{DOMAIN}_report_generated", report_data)

    async def _async_install_dashboard_service(call: ServiceCall) -> None:
        if not await _async_install_and_emit_dashboard(hass):
            raise HomeAssistantError("Could not install Network Quality dashboard")

    hass.services.async_register(
        DOMAIN,
        SERVICE_EXPORT_REPORT,
        _async_export_report,
        schema=vol.Schema(
            {
                vol.Optional(ATTR_OUTPUT_PATH): cv.string,
                vol.Optional(ATTR_INCLUDE_RAW, default=False): cv.boolean,
                vol.Optional(ATTR_INSTANCE_ID): cv.string,
                vol.Optional(ATTR_ENTRY_ID): cv.string,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_INSTALL_DASHBOARD,
        _async_install_dashboard_service,
        schema=vol.Schema({}),
    )

    return True


def _extract_stable_key(entity_domain: str, unique_id: str, entry_id: str) -> str | None:
    """Extract stable key from a legacy unique id."""
    legacy_prefix = f"{entry_id}_"
    if unique_id.startswith(legacy_prefix):
        candidate = unique_id.removeprefix(legacy_prefix)
    else:
        candidate = unique_id

    if entity_domain == "sensor" and candidate in _SUPPORTED_SENSOR_KEYS:
        return candidate
    if entity_domain == "binary_sensor" and candidate in _SUPPORTED_BINARY_KEYS:
        return candidate
    if entity_domain == "binary_sensor" and candidate.startswith("service_"):
        service_name = candidate.removeprefix("service_")
        if re.fullmatch(r"[a-z0-9_]+", service_name):
            return candidate
    return None


def _expected_entity_id(entity_domain: str, stable_key: str) -> str:
    """Build expected entity id from domain and stable key."""
    return f"{entity_domain}.{DOMAIN}_{stable_key}"


def _legacy_migration_target(match: re.Match[str]) -> str:
    """Build normalized entity id target from a legacy id regex match."""
    return f"{match.group(1)}.{_ENTITY_DOMAIN_PREFIX}{match.group(2)}"


async def _async_migrate_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Migrate legacy entity ids and unique ids to stable naming."""
    registry = er.async_get(hass)
    pattern = re.compile(
        rf"^(sensor|binary_sensor)\.{re.escape(DOMAIN)}_{re.escape(entry.entry_id)}_(.+)$"
    )
    for registry_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        entity_domain = registry_entry.entity_id.split(".", 1)[0]
        stable_key = _extract_stable_key(entity_domain, registry_entry.unique_id, entry.entry_id)
        update_payload: dict[str, str] = {}

        if stable_key and registry_entry.unique_id != stable_key:
            update_payload["new_unique_id"] = stable_key

        if stable_key:
            target_entity_id = _expected_entity_id(entity_domain, stable_key)
            if (
                registry_entry.entity_id != target_entity_id
                and registry.async_get(target_entity_id) is None
            ):
                update_payload["new_entity_id"] = target_entity_id

        legacy_entity_match = pattern.match(registry_entry.entity_id)
        if legacy_entity_match and "new_entity_id" not in update_payload:
            legacy_target = _legacy_migration_target(legacy_entity_match)
            if registry.async_get(legacy_target) is None:
                update_payload["new_entity_id"] = legacy_target

        if not update_payload:
            continue

        try:
            registry.async_update_entity(registry_entry.entity_id, **update_payload)
            _LOGGER.info("Migrated entity %s with changes %s", registry_entry.entity_id, update_payload)
        except ValueError:
            _LOGGER.warning("Could not migrate entity %s", registry_entry.entity_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = NetworkQualityCoordinator(hass, entry)
    await coordinator.async_initialize()
    await coordinator.async_config_entry_first_refresh()
    await _async_migrate_entities(hass, entry)

    hass.data[DOMAIN][entry.entry_id] = {DATA_COORDINATOR: coordinator}
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Run a second migration pass because entities registered during platform setup can still
    # initially appear with legacy-style IDs before they are normalized in the registry.
    await _async_migrate_entities(hass, entry)

    if not entry.options.get(CONF_DASHBOARD_AUTO_EMITTED, False):
        async def _async_try_dashboard_install() -> bool:
            if not await _async_install_and_emit_dashboard(hass, entry):
                _LOGGER.warning("Automatic dashboard installation failed")
                return False
            return True

        dashboard_installed = await _async_try_dashboard_install()
        if not dashboard_installed and not hass.is_running:

            async def _async_install_dashboard_on_started(event) -> None:
                del event
                if not await _async_try_dashboard_install():
                    _LOGGER.warning("Automatic dashboard installation retry failed after startup")

            hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED,
                _async_install_dashboard_on_started,
            )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    if not hass.config_entries.async_entries(DOMAIN):
        hass.services.async_remove(DOMAIN, SERVICE_EXPORT_REPORT)
        hass.services.async_remove(DOMAIN, SERVICE_INSTALL_DASHBOARD)
    return unload_ok
