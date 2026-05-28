"""Shared entity helpers for Network Quality integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN


def build_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return a shared device description for all integration entities."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title or "Network Quality",
        manufacturer="Network Quality",
        model="Internet Monitor",
    )
