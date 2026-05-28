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

    class CoordinatorStub:
        """Lightweight stand-in because _build_service_statuses is stateless."""

    coordinator = CoordinatorStub()

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


def test_normalize_probe_targets_parses_ipv6_and_ports() -> None:
    """Local probe target normalization should robustly extract hosts."""
    coordinator_module = _load_coordinator_module()

    class CoordinatorStub:
        """Lightweight stand-in because _normalize_probe_targets is stateless."""

    coordinator = CoordinatorStub()
    hosts = coordinator_module.NetworkQualityCoordinator._normalize_probe_targets(
        coordinator,
        [
            "https://[2001:db8::1]:8443/ping",
            "[2001:db8::2]:9443",
            "example.org:443",
            "https://example.net:8443/status",
            "2001:db8::3",
            "[fe80::1%eth0]:443",
            "https://[2001:db8::1]:8443/duplicate",
        ],
    )

    assert hosts == [
        "2001:db8::1",
        "2001:db8::2",
        "example.org",
        "example.net",
        "2001:db8::3",
        "fe80::1%eth0",
    ]


def test_normalize_probe_targets_skips_invalid_port_syntax() -> None:
    """Invalid host:port combinations should not be used for local probes."""
    coordinator_module = _load_coordinator_module()

    class CoordinatorStub:
        """Lightweight stand-in because _normalize_probe_targets is stateless."""

    coordinator = CoordinatorStub()
    hosts = coordinator_module.NetworkQualityCoordinator._normalize_probe_targets(
        coordinator,
        [
            "[2001:db8::4]:99999",
            "https://[2001:db8::5]:bad",
            "example.com:abc",
            "[2001:db8::6]extra",
            "8.8.8.8:53",
        ],
    )

    assert hosts == ["8.8.8.8"]


def test_extract_method_metrics_reads_ookla_fast_iperf_http_values() -> None:
    """Method-specific metrics should be normalized from agent payloads."""
    coordinator_module = _load_coordinator_module()

    class CoordinatorStub:
        """Lightweight stand-in with required helper methods."""

        _first_float_value = coordinator_module.NetworkQualityCoordinator._first_float_value
        _to_float = coordinator_module.NetworkQualityCoordinator._to_float

    coordinator = CoordinatorStub()
    method_metrics = coordinator_module.NetworkQualityCoordinator._extract_method_metrics(
        coordinator,
        {
            "methods": {
                "ookla": {"download_mbps": 222.2, "upload_mbps": 33.3, "ping_ms": 9.1},
                "fast": {"download_mbps": 201.5},
                "iperf3": {"download_mbps": 250.0, "upload_mbps": 60.0, "jitter_ms": 1.2},
                "http_download": {"download_mbps": 190.0},
            },
            "ookla_packet_loss_percent": 0.2,
            "iperf3_packet_loss_percent": 0.4,
        },
    )

    assert method_metrics == {
        "ookla": {"download": 222.2, "upload": 33.3, "ping": 9.1, "packet_loss": 0.2},
        "fast": {"download": 201.5},
        "iperf3": {"download": 250.0, "upload": 60.0, "jitter": 1.2, "packet_loss": 0.4},
        "http_download": {"download": 190.0},
    }


def test_extract_test_runs_includes_method_specific_tests() -> None:
    """Test metadata normalization should include new method-specific timestamps."""
    coordinator_module = _load_coordinator_module()

    class CoordinatorStub:
        """Lightweight stand-in with required helper methods."""

        _normalize_timestamp = coordinator_module.NetworkQualityCoordinator._normalize_timestamp

    coordinator = CoordinatorStub()
    tests = coordinator_module.NetworkQualityCoordinator._extract_test_runs(
        coordinator,
        {
            "tests": {
                "ookla": {"last_run_at": "2026-05-28T12:00:00+00:00"},
                "fast": {"last_run_at": "2026-05-28T12:01:00+00:00"},
                "iperf3": {"last_run_at": "2026-05-28T12:02:00+00:00"},
                "http_download": {"last_run_at": "2026-05-28T12:03:00+00:00"},
            }
        },
    )

    assert tests["ookla_speedtest"]["last_run_at"] == "2026-05-28T12:00:00+00:00"
    assert tests["fast_speedtest"]["last_run_at"] == "2026-05-28T12:01:00+00:00"
    assert tests["iperf3"]["last_run_at"] == "2026-05-28T12:02:00+00:00"
    assert tests["http_download"]["last_run_at"] == "2026-05-28T12:03:00+00:00"
