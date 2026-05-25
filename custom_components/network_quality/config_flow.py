"""Config flow for Network Quality integration."""

from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowResult
import voluptuous as vol

from .const import (
    AVAILABLE_SERVICE_CATALOG,
    CONF_AGENT_URL,
    CONF_DOWNLOAD_MAX,
    CONF_DOWNLOAD_MIN,
    CONF_DOWNLOAD_NORMAL,
    CONF_EXTERNAL_OPT_IN,
    CONF_ISP,
    CONF_PING_INTERVAL,
    CONF_REGION,
    CONF_ROUTER_TYPE,
    CONF_SERVICE_STATUSES,
    CONF_SPEEDTEST_INTERVAL,
    CONF_STATUS_INTERVAL,
    CONF_TEST_TARGETS,
    CONF_UPLOAD_MAX,
    CONF_UPLOAD_MIN,
    CONF_UPLOAD_NORMAL,
    DEFAULT_AGENT_URL,
    DEFAULT_EXTERNAL_OPT_IN,
    DEFAULT_PING_INTERVAL,
    DEFAULT_REGION,
    DEFAULT_SPEEDTEST_INTERVAL,
    DEFAULT_STATUS_INTERVAL,
    DEFAULT_TEST_TARGETS,
    DOMAIN,
)

ROUTER_TYPES = ["fritzbox", "openwrt", "unifi", "other"]


class NetworkQualityConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Network Quality."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_DOWNLOAD_MIN] > user_input[CONF_DOWNLOAD_NORMAL]:
                errors[CONF_DOWNLOAD_NORMAL] = "download_range"
            elif user_input[CONF_DOWNLOAD_NORMAL] > user_input[CONF_DOWNLOAD_MAX]:
                errors[CONF_DOWNLOAD_MAX] = "download_range"
            elif user_input[CONF_UPLOAD_MIN] > user_input[CONF_UPLOAD_NORMAL]:
                errors[CONF_UPLOAD_NORMAL] = "upload_range"
            elif user_input[CONF_UPLOAD_NORMAL] > user_input[CONF_UPLOAD_MAX]:
                errors[CONF_UPLOAD_MAX] = "upload_range"
            else:
                await self.async_set_unique_id(user_input[CONF_ISP].strip().lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input.get(CONF_NAME, f"Network Quality ({user_input[CONF_ISP]})"),
                    data=user_input,
                    options={
                        CONF_REGION: DEFAULT_REGION,
                        CONF_SPEEDTEST_INTERVAL: DEFAULT_SPEEDTEST_INTERVAL,
                        CONF_PING_INTERVAL: DEFAULT_PING_INTERVAL,
                        CONF_STATUS_INTERVAL: DEFAULT_STATUS_INTERVAL,
                        CONF_EXTERNAL_OPT_IN: DEFAULT_EXTERNAL_OPT_IN,
                        CONF_TEST_TARGETS: DEFAULT_TEST_TARGETS,
                        CONF_SERVICE_STATUSES: AVAILABLE_SERVICE_CATALOG,
                        CONF_AGENT_URL: DEFAULT_AGENT_URL,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default="Network Quality"): str,
                    vol.Required(CONF_ISP): str,
                    vol.Required(CONF_ROUTER_TYPE, default=ROUTER_TYPES[0]): vol.In(ROUTER_TYPES),
                    vol.Required(CONF_DOWNLOAD_MIN): vol.Coerce(float),
                    vol.Required(CONF_DOWNLOAD_NORMAL): vol.Coerce(float),
                    vol.Required(CONF_DOWNLOAD_MAX): vol.Coerce(float),
                    vol.Required(CONF_UPLOAD_MIN): vol.Coerce(float),
                    vol.Required(CONF_UPLOAD_NORMAL): vol.Coerce(float),
                    vol.Required(CONF_UPLOAD_MAX): vol.Coerce(float),
                }
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
        if user_input is not None:
            targets = [line.strip() for line in user_input[CONF_TEST_TARGETS].splitlines() if line.strip()]
            services = [
                service
                for service in AVAILABLE_SERVICE_CATALOG
                if user_input.get(f"service_{service}", False)
            ]
            return self.async_create_entry(
                title="",
                data={
                    CONF_REGION: user_input[CONF_REGION],
                    CONF_SPEEDTEST_INTERVAL: user_input[CONF_SPEEDTEST_INTERVAL],
                    CONF_PING_INTERVAL: user_input[CONF_PING_INTERVAL],
                    CONF_STATUS_INTERVAL: user_input[CONF_STATUS_INTERVAL],
                    CONF_EXTERNAL_OPT_IN: user_input[CONF_EXTERNAL_OPT_IN],
                    CONF_TEST_TARGETS: targets or DEFAULT_TEST_TARGETS,
                    CONF_SERVICE_STATUSES: services or AVAILABLE_SERVICE_CATALOG,
                    CONF_AGENT_URL: user_input[CONF_AGENT_URL].strip(),
                },
            )

        options = self._config_entry.options
        selected = set(options.get(CONF_SERVICE_STATUSES, AVAILABLE_SERVICE_CATALOG))
        schema: dict[Any, Any] = {
            vol.Optional(CONF_REGION, default=options.get(CONF_REGION, DEFAULT_REGION)): str,
            vol.Required(
                CONF_SPEEDTEST_INTERVAL,
                default=options.get(CONF_SPEEDTEST_INTERVAL, DEFAULT_SPEEDTEST_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=60, max=86400)),
            vol.Required(
                CONF_PING_INTERVAL,
                default=options.get(CONF_PING_INTERVAL, DEFAULT_PING_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),
            vol.Required(
                CONF_STATUS_INTERVAL,
                default=options.get(CONF_STATUS_INTERVAL, DEFAULT_STATUS_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=30, max=86400)),
            vol.Optional(
                CONF_EXTERNAL_OPT_IN,
                default=options.get(CONF_EXTERNAL_OPT_IN, DEFAULT_EXTERNAL_OPT_IN),
            ): bool,
            vol.Optional(
                CONF_TEST_TARGETS,
                default="\n".join(options.get(CONF_TEST_TARGETS, DEFAULT_TEST_TARGETS)),
            ): str,
            vol.Optional(
                CONF_AGENT_URL,
                default=options.get(CONF_AGENT_URL, DEFAULT_AGENT_URL),
            ): str,
        }
        for service in AVAILABLE_SERVICE_CATALOG:
            schema[vol.Optional(f"service_{service}", default=service in selected)] = bool

        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))
