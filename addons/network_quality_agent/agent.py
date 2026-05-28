from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
import json
from pathlib import Path
from statistics import mean
from typing import Any

from aiohttp import web

OPTIONS_PATH = Path("/data/options.json")
DEFAULTS: dict[str, Any] = {
    "bind_host": "0.0.0.0",
    "bind_port": 8099,
    "interval_seconds": 60,
    "connect_timeout_seconds": 3.0,
    "probe_attempts": 3,
    "targets": ["1.1.1.1", "8.8.8.8", "9.9.9.9"],
    "token": "",
}
CONNECT_PORT = 443


def load_options() -> dict[str, Any]:
    options = dict(DEFAULTS)
    if OPTIONS_PATH.exists():
        try:
            options.update(json.loads(OPTIONS_PATH.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
    options["targets"] = [str(item).strip() for item in options.get("targets", []) if str(item).strip()]
    return options


class AgentState:
    def __init__(self) -> None:
        self.options = load_options()
        self.metrics: dict[str, Any] = {
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "online": False,
            "download_mbps": 0.0,
            "upload_mbps": 0.0,
            "ping_ms": 0.0,
            "jitter_ms": 0.0,
            "packet_loss_percent": 100.0,
            "availability_percent": 0.0,
            "tests": {},
            "methods": {},
        }
        self._lock = asyncio.Lock()

    async def update_metrics(self) -> None:
        probe = await self._probe_targets()
        now_iso = datetime.now(tz=UTC).isoformat()
        async with self._lock:
            self.metrics = {
                "timestamp": now_iso,
                "online": probe["online"],
                "download_mbps": 0.0,
                "upload_mbps": 0.0,
                "ping_ms": probe["ping"],
                "jitter_ms": probe["jitter"],
                "packet_loss_percent": probe["packet_loss"],
                "availability_percent": probe["availability"],
                "tests": {
                    "ping": {"last_run_at": now_iso},
                    "traceroute": {"last_run_at": now_iso},
                    "status": {"last_run_at": now_iso},
                    "download": {
                        "last_run_at": None,
                        "last_started_at": None,
                        "last_finished_at": None,
                        "reason": "not_configured",
                    },
                    "upload": {
                        "last_run_at": None,
                        "last_started_at": None,
                        "last_finished_at": None,
                        "reason": "not_configured",
                    },
                },
                "methods": {},
            }

    async def get_metrics(self) -> dict[str, Any]:
        async with self._lock:
            return dict(self.metrics)

    async def _probe_targets(self) -> dict[str, float | bool]:
        targets = self.options.get("targets", [])
        if not targets:
            return {"online": False, "ping": 0.0, "jitter": 0.0, "packet_loss": 100.0, "availability": 0.0}

        timeout = float(self.options.get("connect_timeout_seconds", 3.0))
        attempts = int(self.options.get("probe_attempts", 3))
        latencies: list[float] = []
        failed = 0
        for idx in range(attempts):
            host = targets[idx % len(targets)]
            latency = await self._measure_connect_latency(host=host, timeout=timeout)
            if latency is None:
                failed += 1
                continue
            latencies.append(latency)

        if not latencies:
            return {"online": False, "ping": 0.0, "jitter": 0.0, "packet_loss": 100.0, "availability": 0.0}

        deltas = [abs(current - previous) for previous, current in zip(latencies, latencies[1:])]
        successful = attempts - failed
        return {
            "online": successful > 0,
            "ping": round(mean(latencies), 2),
            "jitter": round(mean(deltas), 2) if deltas else 0.0,
            "packet_loss": round((failed / attempts) * 100.0, 2),
            "availability": round((successful / attempts) * 100.0, 2),
        }

    async def _measure_connect_latency(self, *, host: str, timeout: float) -> float | None:
        started = asyncio.get_running_loop().time()
        writer = None
        try:
            connection = asyncio.open_connection(host, CONNECT_PORT)
            _, writer = await asyncio.wait_for(connection, timeout=timeout)
        except (OSError, TimeoutError):
            return None
        try:
            elapsed = (asyncio.get_running_loop().time() - started) * 1000.0
            return round(elapsed, 2)
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()


async def metrics_handler(request: web.Request) -> web.Response:
    state: AgentState = request.app["state"]
    token = str(state.options.get("token", "")).strip()
    if token:
        header = request.headers.get("Authorization", "")
        prefix = "Bearer "
        if not header.startswith(prefix) or header[len(prefix) :] != token:
            return web.json_response({"error": "unauthorized"}, status=401)
    return web.json_response(await state.get_metrics())


async def health_handler(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def update_loop(app: web.Application) -> None:
    state: AgentState = app["state"]
    while True:
        await state.update_metrics()
        await asyncio.sleep(int(state.options.get("interval_seconds", 60)))


async def start_background(app: web.Application) -> None:
    app["update_task"] = asyncio.create_task(update_loop(app))


async def stop_background(app: web.Application) -> None:
    task: asyncio.Task[Any] | None = app.get("update_task")
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


def create_app() -> web.Application:
    app = web.Application()
    app["state"] = AgentState()
    app.router.add_get("/metrics", metrics_handler)
    app.router.add_get("/health", health_handler)
    app.on_startup.append(start_background)
    app.on_cleanup.append(stop_background)
    return app


if __name__ == "__main__":
    options = load_options()
    web.run_app(
        create_app(),
        host=str(options.get("bind_host", "0.0.0.0")),
        port=int(options.get("bind_port", 8099)),
    )
