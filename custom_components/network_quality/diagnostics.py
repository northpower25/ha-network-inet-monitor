"""Diagnostics for Network Quality integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_AGENT_URL, CONF_ISP, DATA_COORDINATOR, DOMAIN

TO_REDACT = {CONF_AGENT_URL, CONF_ISP}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics data."""
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": async_redact_data(dict(entry.options), TO_REDACT),
        "data": coordinator.data,
    }
