"""Tests for Nabu Casa cloud connection status handling."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import types
from typing import Generic, TypeVar


_T = TypeVar("_T")


def _install_homeassistant_stubs() -> None:
    if "homeassistant" in sys.modules:
        return

    homeassistant = types.ModuleType("homeassistant")
    config_entries = types.ModuleType("homeassistant.config_entries")
    core = types.ModuleType("homeassistant.core")
    helpers = types.ModuleType("homeassistant.helpers")
    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    storage = types.ModuleType("homeassistant.helpers.storage")
    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")

    class ConfigEntry:  # pragma: no cover - lightweight import stub
        pass

    class HomeAssistant:  # pragma: no cover - lightweight import stub
        pass

    class Store(Generic[_T]):  # pragma: no cover - lightweight import stub
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def async_load(self) -> dict[str, list[dict[str, object]]]:
            return {}

        def async_delay_save(self, *_args, **_kwargs) -> None:
            return None

    class DataUpdateCoordinator(Generic[_T]):  # pragma: no cover - import stub
        def __init__(self, *_args, **_kwargs) -> None:
            self.data = {}
            self.last_update_success = True

    class UpdateFailed(Exception):
        """Import stub for coordinator exceptions."""

    def async_get_clientsession(_hass: HomeAssistant) -> None:  # pragma: no cover
        return None

    config_entries.ConfigEntry = ConfigEntry
    core.HomeAssistant = HomeAssistant
    aiohttp_client.async_get_clientsession = async_get_clientsession
    storage.Store = Store
    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    update_coordinator.UpdateFailed = UpdateFailed

    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.aiohttp_client"] = aiohttp_client
    sys.modules["homeassistant.helpers.storage"] = storage
    sys.modules["homeassistant.helpers.update_coordinator"] = update_coordinator


def _load_module(module_name: str, file_path: Path) -> types.ModuleType:
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    spec = spec_from_file_location(module_name, file_path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_coordinator_module() -> types.ModuleType:
    repo_root = Path(__file__).resolve().parents[1]
    custom_components_path = repo_root / "custom_components"
    package_path = custom_components_path / "network_quality"

    custom_components_pkg = sys.modules.setdefault("custom_components", types.ModuleType("custom_components"))
    custom_components_pkg.__path__ = [str(custom_components_path)]

    network_quality_pkg = sys.modules.setdefault(
        "custom_components.network_quality", types.ModuleType("custom_components.network_quality")
    )
    network_quality_pkg.__path__ = [str(package_path)]

    _install_homeassistant_stubs()
    _load_module("custom_components.network_quality.analytics", package_path / "analytics.py")
    _load_module("custom_components.network_quality.const", package_path / "const.py")
    return _load_module("custom_components.network_quality.coordinator", package_path / "coordinator.py")


def test_nabu_casa_cloud_connection_reflects_online_state() -> None:
    """Nabu Casa cloud service should mirror online connectivity state."""
    coordinator_module = _load_coordinator_module()
    coordinator = object.__new__(coordinator_module.NetworkQualityCoordinator)

    online = coordinator_module.NetworkQualityCoordinator._build_service_statuses(
        coordinator,
        services=["nabu_casa_cloud"],
        external_opt_in=False,
        online=True,
    )
    offline = coordinator_module.NetworkQualityCoordinator._build_service_statuses(
        coordinator,
        services=["nabu_casa_cloud"],
        external_opt_in=False,
        online=False,
    )

    assert online[0].name == "nabu_casa_cloud"
    assert online[0].reachable is True
    assert online[0].detail == "external_checks_disabled"
    assert offline[0].reachable is False
    assert offline[0].detail == "external_checks_disabled"
