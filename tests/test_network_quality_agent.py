"""Tests for Network Quality add-on agent speed test reporting."""

from __future__ import annotations

import asyncio
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import types


def _load_agent_module() -> types.ModuleType:
    if "aiohttp" not in sys.modules:
        aiohttp = types.ModuleType("aiohttp")
        web = types.ModuleType("aiohttp.web")

        class Application(dict):
            def __init__(self) -> None:
                super().__init__()
                self.router = types.SimpleNamespace(add_get=lambda *_args, **_kwargs: None)
                self.on_startup: list[object] = []
                self.on_cleanup: list[object] = []

        class Request:
            def __init__(self) -> None:
                self.app: dict[str, object] = {}
                self.headers: dict[str, str] = {}

        class Response(dict):
            pass

        def json_response(data: object, status: int = 200) -> dict[str, object]:
            return {"data": data, "status": status}

        def run_app(*_args, **_kwargs) -> None:
            return None

        web.Application = Application
        web.Request = Request
        web.Response = Response
        web.json_response = json_response
        web.run_app = run_app
        aiohttp.web = web
        sys.modules["aiohttp"] = aiohttp
        sys.modules["aiohttp.web"] = web

    module_name = "network_quality_agent.agent"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    file_path = Path(__file__).resolve().parents[1] / "network_quality_agent" / "agent.py"
    spec = spec_from_file_location(module_name, file_path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_agent_runs_speedtest_and_reports_timestamps() -> None:
    """Successful speedtests should populate download/upload test metadata."""

    async def _run() -> None:
        agent_module = _load_agent_module()
        state = agent_module.AgentState()

        async def fake_probe() -> dict[str, float | bool]:
            return {
                "online": True,
                "ping": 12.5,
                "jitter": 1.2,
                "packet_loss": 0.0,
                "availability": 100.0,
            }

        def fake_speedtest(_timeout: float) -> dict[str, float]:
            return {"download_mbps": 123.45, "upload_mbps": 23.45, "ping_ms": 9.1}

        state._probe_targets = fake_probe  # type: ignore[method-assign]
        state._run_speedtest_sync = fake_speedtest  # type: ignore[method-assign]

        await state.update_metrics()
        assert state._speedtest_task is not None
        await asyncio.wait_for(state._speedtest_task, timeout=1)

        metrics = await state.get_metrics()
        assert metrics["download_mbps"] == 123.45
        assert metrics["upload_mbps"] == 23.45
        assert metrics["tests"]["download"]["last_started_at"] is not None
        assert metrics["tests"]["download"]["last_run_at"] is not None
        assert metrics["tests"]["upload"]["last_run_at"] is not None
        assert metrics["tests"]["ookla"]["last_run_at"] is not None
        assert metrics["methods"]["ookla"]["download_mbps"] == 123.45
        assert metrics["methods"]["ookla"]["upload_mbps"] == 23.45

    asyncio.run(_run())


def test_agent_records_failed_speedtest_attempts() -> None:
    """Failed speedtests should still update last_run metadata for diagnostics."""

    async def _run() -> None:
        agent_module = _load_agent_module()
        state = agent_module.AgentState()

        async def fake_probe() -> dict[str, float | bool]:
            return {
                "online": True,
                "ping": 10.0,
                "jitter": 0.5,
                "packet_loss": 0.0,
                "availability": 100.0,
            }

        def failing_speedtest(_timeout: float) -> dict[str, float]:
            raise RuntimeError("boom")

        state._probe_targets = fake_probe  # type: ignore[method-assign]
        state._run_speedtest_sync = failing_speedtest  # type: ignore[method-assign]

        await state.update_metrics()
        assert state._speedtest_task is not None
        await asyncio.wait_for(state._speedtest_task, timeout=1)

        metrics = await state.get_metrics()
        assert metrics["tests"]["download"]["last_run_at"] is not None
        assert metrics["tests"]["upload"]["last_run_at"] is not None
        # With multi-method speedtest, per-method failures are stored in
        # method_results; the top-level reason is "no_data" when no method
        # produced usable throughput values.
        assert metrics["tests"]["download"]["reason"] == "no_data"
        assert metrics["tests"]["upload"]["reason"] == "no_data"
        assert metrics["methods"] == {}

    asyncio.run(_run())
