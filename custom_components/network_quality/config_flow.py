"""Config flow for Network Quality integration."""

from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import urlparse

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowResult
import voluptuous as vol

from .const import (
    AVAILABLE_SERVICE_CATALOG,
    CONF_AGENT_URL,
    CONF_DASHBOARD_AUTO_EMITTED,
    CONF_DOWNLOAD_MAX,
    CONF_DOWNLOAD_MIN,
    CONF_DOWNLOAD_NORMAL,
    CONF_DOWNLOAD_TEST_INTERVAL,
    CONF_EXTERNAL_OPT_IN,
    CONF_ISP,
    CONF_PING_INTERVAL,
    CONF_REGION,
    CONF_ROUTER_TYPE,
    CONF_SERVICE_STATUSES,
    CONF_SPEEDTEST_INTERVAL,
    CONF_STATUS_INTERVAL,
    CONF_TEST_TARGETS,
    CONF_TRACEROUTE_INTERVAL,
    CONF_UPLOAD_TEST_INTERVAL,
    CONF_UPLOAD_MAX,
    CONF_UPLOAD_MIN,
    CONF_UPLOAD_NORMAL,
    DEFAULT_AGENT_URL,
    DEFAULT_DOWNLOAD_TEST_INTERVAL,
    DEFAULT_EXTERNAL_OPT_IN,
    DEFAULT_PING_INTERVAL,
    DEFAULT_REGION,
    DEFAULT_SPEEDTEST_INTERVAL,
    DEFAULT_STATUS_INTERVAL,
    DEFAULT_TEST_TARGETS,
    DEFAULT_TRACEROUTE_INTERVAL,
    DEFAULT_UPLOAD_TEST_INTERVAL,
    DOMAIN,
)

ROUTER_TYPES = ["fritzbox", "openwrt", "unifi", "other"]


def _parse_targets(targets_input: str) -> list[str]:
    """Parse a comma- or newline-separated list of test targets.

    Both separators are accepted so that existing configs stored with
    newline-separated values (from before the comma format was introduced)
    continue to work correctly.
    """
    normalized = targets_input.replace(",", "\n")
    return [t.strip() for t in normalized.splitlines() if t.strip()]


_HOSTNAME_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)*"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$"
)


def _is_valid_target(target: str) -> bool:
    """Return True if target is a valid IPv4/IPv6 address, hostname, or http(s) URL."""
    try:
        ipaddress.ip_address(target)
        return True
    except ValueError:
        pass
    parsed = urlparse(target)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return True
    return bool(_HOSTNAME_RE.match(target))


def _validate_targets(targets: list[str]) -> dict[str, str]:
    """Return an error dict if any target is not a valid IP, hostname, or URL."""
    invalid = [t for t in targets if not _is_valid_target(t)]
    if invalid:
        return {CONF_TEST_TARGETS: "invalid_test_targets"}
    return {}


def _build_selected_services(user_input: dict[str, Any]) -> list[str]:
    return [
        service
        for service in AVAILABLE_SERVICE_CATALOG
        if user_input.get(f"service_{service}", False)
    ]


def _validate_ranges(user_input: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    if user_input[CONF_DOWNLOAD_MIN] > user_input[CONF_DOWNLOAD_NORMAL]:
        errors[CONF_DOWNLOAD_NORMAL] = "download_range"
    elif user_input[CONF_DOWNLOAD_NORMAL] > user_input[CONF_DOWNLOAD_MAX]:
        errors[CONF_DOWNLOAD_MAX] = "download_range"
    elif user_input[CONF_UPLOAD_MIN] > user_input[CONF_UPLOAD_NORMAL]:
        errors[CONF_UPLOAD_NORMAL] = "upload_range"
    elif user_input[CONF_UPLOAD_NORMAL] > user_input[CONF_UPLOAD_MAX]:
        errors[CONF_UPLOAD_MAX] = "upload_range"
    return errors


def _normalize_common_options(user_input: dict[str, Any]) -> dict[str, Any]:
    targets = _parse_targets(user_input[CONF_TEST_TARGETS])
    services = _build_selected_services(user_input)
    return {
        CONF_REGION: user_input[CONF_REGION].strip(),
        CONF_SPEEDTEST_INTERVAL: user_input[CONF_SPEEDTEST_INTERVAL],
        CONF_PING_INTERVAL: user_input[CONF_PING_INTERVAL],
        CONF_TRACEROUTE_INTERVAL: user_input[CONF_TRACEROUTE_INTERVAL],
        CONF_DOWNLOAD_TEST_INTERVAL: user_input[CONF_DOWNLOAD_TEST_INTERVAL],
        CONF_UPLOAD_TEST_INTERVAL: user_input[CONF_UPLOAD_TEST_INTERVAL],
        CONF_STATUS_INTERVAL: user_input[CONF_STATUS_INTERVAL],
        CONF_EXTERNAL_OPT_IN: user_input[CONF_EXTERNAL_OPT_IN],
        CONF_TEST_TARGETS: targets or DEFAULT_TEST_TARGETS,
        CONF_SERVICE_STATUSES: services or AVAILABLE_SERVICE_CATALOG,
        CONF_AGENT_URL: user_input[CONF_AGENT_URL].strip(),
        CONF_DASHBOARD_AUTO_EMITTED: user_input.get(CONF_DASHBOARD_AUTO_EMITTED, False),
    }


def _build_schema(
    *,
    data_defaults: dict[str, Any],
    options_defaults: dict[str, Any],
    default_region: str,
) -> vol.Schema:
    selected = set(options_defaults.get(CONF_SERVICE_STATUSES, AVAILABLE_SERVICE_CATALOG))
    schema: dict[Any, Any] = {
        vol.Required(CONF_NAME, default=data_defaults.get(CONF_NAME, "Network Quality")): str,
        vol.Required(CONF_ISP, default=data_defaults.get(CONF_ISP, "")): str,
        vol.Required(
            CONF_ROUTER_TYPE,
            default=data_defaults.get(CONF_ROUTER_TYPE, ROUTER_TYPES[0]),
        ): vol.In(ROUTER_TYPES),
        vol.Required(
            CONF_DOWNLOAD_MIN,
            default=data_defaults.get(CONF_DOWNLOAD_MIN, 0.0),
        ): vol.Coerce(float),
        vol.Required(
            CONF_DOWNLOAD_NORMAL,
            default=data_defaults.get(CONF_DOWNLOAD_NORMAL, 0.0),
        ): vol.Coerce(float),
        vol.Required(
            CONF_DOWNLOAD_MAX,
            default=data_defaults.get(CONF_DOWNLOAD_MAX, 0.0),
        ): vol.Coerce(float),
        vol.Required(
            CONF_UPLOAD_MIN,
            default=data_defaults.get(CONF_UPLOAD_MIN, 0.0),
        ): vol.Coerce(float),
        vol.Required(
            CONF_UPLOAD_NORMAL,
            default=data_defaults.get(CONF_UPLOAD_NORMAL, 0.0),
        ): vol.Coerce(float),
        vol.Required(
            CONF_UPLOAD_MAX,
            default=data_defaults.get(CONF_UPLOAD_MAX, 0.0),
        ): vol.Coerce(float),
        vol.Optional(
            CONF_REGION,
            default=options_defaults.get(CONF_REGION, default_region),
        ): str,
        vol.Required(
            CONF_SPEEDTEST_INTERVAL,
            default=options_defaults.get(CONF_SPEEDTEST_INTERVAL, DEFAULT_SPEEDTEST_INTERVAL),
        ): vol.All(vol.Coerce(int), vol.Range(min=60, max=86400)),
        vol.Required(
            CONF_PING_INTERVAL,
            default=options_defaults.get(CONF_PING_INTERVAL, DEFAULT_PING_INTERVAL),
        ): vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),
        vol.Required(
            CONF_TRACEROUTE_INTERVAL,
            default=options_defaults.get(CONF_TRACEROUTE_INTERVAL, DEFAULT_TRACEROUTE_INTERVAL),
        ): vol.All(vol.Coerce(int), vol.Range(min=60, max=86400)),
        vol.Required(
            CONF_DOWNLOAD_TEST_INTERVAL,
            default=options_defaults.get(
                CONF_DOWNLOAD_TEST_INTERVAL,
                options_defaults.get(CONF_SPEEDTEST_INTERVAL, DEFAULT_DOWNLOAD_TEST_INTERVAL),
            ),
        ): vol.All(vol.Coerce(int), vol.Range(min=60, max=86400)),
        vol.Required(
            CONF_UPLOAD_TEST_INTERVAL,
            default=options_defaults.get(
                CONF_UPLOAD_TEST_INTERVAL,
                options_defaults.get(CONF_SPEEDTEST_INTERVAL, DEFAULT_UPLOAD_TEST_INTERVAL),
            ),
        ): vol.All(vol.Coerce(int), vol.Range(min=60, max=86400)),
        vol.Required(
            CONF_STATUS_INTERVAL,
            default=options_defaults.get(CONF_STATUS_INTERVAL, DEFAULT_STATUS_INTERVAL),
        ): vol.All(vol.Coerce(int), vol.Range(min=30, max=86400)),
        vol.Optional(
            CONF_EXTERNAL_OPT_IN,
            default=options_defaults.get(CONF_EXTERNAL_OPT_IN, DEFAULT_EXTERNAL_OPT_IN),
        ): bool,
        vol.Optional(
            CONF_TEST_TARGETS,
            default=", ".join(options_defaults.get(CONF_TEST_TARGETS, DEFAULT_TEST_TARGETS)),
        ): str,
        vol.Optional(
            CONF_AGENT_URL,
            default=options_defaults.get(CONF_AGENT_URL, DEFAULT_AGENT_URL),
        ): str,
    }
    for service in AVAILABLE_SERVICE_CATALOG:
        schema[vol.Optional(f"service_{service}", default=service in selected)] = bool
    return vol.Schema(schema)


class NetworkQualityConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Network Quality."""

    VERSION = 1

    def _default_region(self) -> str:
        return self.hass.config.location_name or DEFAULT_REGION

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step."""
        defaults = {
            CONF_REGION: self._default_region(),
            CONF_SPEEDTEST_INTERVAL: DEFAULT_SPEEDTEST_INTERVAL,
            CONF_PING_INTERVAL: DEFAULT_PING_INTERVAL,
            CONF_TRACEROUTE_INTERVAL: DEFAULT_TRACEROUTE_INTERVAL,
            CONF_DOWNLOAD_TEST_INTERVAL: DEFAULT_DOWNLOAD_TEST_INTERVAL,
            CONF_UPLOAD_TEST_INTERVAL: DEFAULT_UPLOAD_TEST_INTERVAL,
            CONF_STATUS_INTERVAL: DEFAULT_STATUS_INTERVAL,
            CONF_EXTERNAL_OPT_IN: DEFAULT_EXTERNAL_OPT_IN,
            CONF_TEST_TARGETS: DEFAULT_TEST_TARGETS,
            CONF_SERVICE_STATUSES: AVAILABLE_SERVICE_CATALOG,
            CONF_AGENT_URL: DEFAULT_AGENT_URL,
            CONF_DASHBOARD_AUTO_EMITTED: False,
        }
        errors: dict[str, str]
        if user_input is not None:
            errors = _validate_ranges(user_input)
            if not errors:
                parsed_targets = _parse_targets(user_input.get(CONF_TEST_TARGETS, ""))
                if parsed_targets:
                    errors = _validate_targets(parsed_targets)
            if not errors:
                await self.async_set_unique_id(user_input[CONF_ISP].strip().lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input.get(CONF_NAME, f"Network Quality ({user_input[CONF_ISP]})"),
                    data={
                        CONF_NAME: user_input[CONF_NAME],
                        CONF_ISP: user_input[CONF_ISP].strip(),
                        CONF_ROUTER_TYPE: user_input[CONF_ROUTER_TYPE],
                        CONF_DOWNLOAD_MIN: user_input[CONF_DOWNLOAD_MIN],
                        CONF_DOWNLOAD_NORMAL: user_input[CONF_DOWNLOAD_NORMAL],
                        CONF_DOWNLOAD_MAX: user_input[CONF_DOWNLOAD_MAX],
                        CONF_UPLOAD_MIN: user_input[CONF_UPLOAD_MIN],
                        CONF_UPLOAD_NORMAL: user_input[CONF_UPLOAD_NORMAL],
                        CONF_UPLOAD_MAX: user_input[CONF_UPLOAD_MAX],
                    },
                    options=_normalize_common_options({**defaults, **user_input}),
                )
        else:
            errors = {}

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema(
                data_defaults={},
                options_defaults=defaults,
                default_region=self._default_region(),
            ),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        """Return options flow."""
        return NetworkQualityOptionsFlow(config_entry)


class NetworkQualityOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage options."""
        errors: dict[str, str]
        if user_input is not None:
            errors = _validate_ranges(user_input)
            if not errors:
                parsed_targets = _parse_targets(user_input.get(CONF_TEST_TARGETS, ""))
                if parsed_targets:
                    errors = _validate_targets(parsed_targets)
            if not errors:
                self.hass.config_entries.async_update_entry(
                    self._config_entry,
                    title=user_input.get(CONF_NAME, f"Network Quality ({user_input[CONF_ISP]})"),
                    data={
                        CONF_NAME: user_input[CONF_NAME],
                        CONF_ISP: user_input[CONF_ISP].strip(),
                        CONF_ROUTER_TYPE: user_input[CONF_ROUTER_TYPE],
                        CONF_DOWNLOAD_MIN: user_input[CONF_DOWNLOAD_MIN],
                        CONF_DOWNLOAD_NORMAL: user_input[CONF_DOWNLOAD_NORMAL],
                        CONF_DOWNLOAD_MAX: user_input[CONF_DOWNLOAD_MAX],
                        CONF_UPLOAD_MIN: user_input[CONF_UPLOAD_MIN],
                        CONF_UPLOAD_NORMAL: user_input[CONF_UPLOAD_NORMAL],
                        CONF_UPLOAD_MAX: user_input[CONF_UPLOAD_MAX],
                    },
                )
                return self.async_create_entry(
                    title="",
                    data=_normalize_common_options({**self._config_entry.options, **user_input}),
                )
        else:
            errors = {}

        data_defaults = dict(self._config_entry.data)
        options = dict(self._config_entry.options)
        if CONF_REGION not in options:
            options[CONF_REGION] = self.hass.config.location_name or DEFAULT_REGION
        if CONF_DASHBOARD_AUTO_EMITTED not in options:
            options[CONF_DASHBOARD_AUTO_EMITTED] = False
        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(
                data_defaults=data_defaults,
                options_defaults=options,
                default_region=self.hass.config.location_name or DEFAULT_REGION,
            ),
            errors=errors,
        )
