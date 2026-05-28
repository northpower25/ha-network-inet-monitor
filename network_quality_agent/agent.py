from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
import json
from pathlib import Path
import secrets
from statistics import mean
from typing import Any

from aiohttp import web

OPTIONS_PATH = Path("/data/options.json")
DEFAULTS: dict[str, Any] = {
    "bind_host": "0.0.0.0",
    "bind_port": 8099,
    "interval_seconds": 60,
    "speedtest_interval_seconds": 900,
    "speedtest_timeout_seconds": 120,
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
        self._latest_probe: dict[str, float | bool] = {
            "online": False,
            "ping": 0.0,
            "jitter": 0.0,
            "packet_loss": 100.0,
            "availability": 0.0,
        }
        self._speedtest: dict[str, Any] = {
            "download_mbps": 0.0,
            "upload_mbps": 0.0,
            "ping_ms": None,
            "running": False,
            "last_run_at": None,
            "last_started_at": None,
            "last_finished_at": None,
            "reason": "pending",
        }
        self._speedtest_task: asyncio.Task[None] | None = None
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
        now = datetime.now(tz=UTC)
        now_iso = now.isoformat()
        async with self._lock:
            self.options = load_options()
            self._latest_probe = probe
            if self._should_start_speedtest(now=now):
                self._speedtest["running"] = True
                self._speedtest["last_started_at"] = now_iso
                self._speedtest["reason"] = "running"
                self._speedtest_task = asyncio.create_task(self._run_speedtest())
            self.metrics = {
                "timestamp": now_iso,
                "online": bool(probe["online"])
                or float(self._speedtest.get("download_mbps", 0.0)) > 0.0
                or float(self._speedtest.get("upload_mbps", 0.0)) > 0.0,
                "download_mbps": float(self._speedtest.get("download_mbps", 0.0)),
                "upload_mbps": float(self._speedtest.get("upload_mbps", 0.0)),
                "ping_ms": probe["ping"],
                "jitter_ms": probe["jitter"],
                "packet_loss_percent": probe["packet_loss"],
                "availability_percent": probe["availability"],
                "tests": {
                    "ping": {"last_run_at": now_iso},
                    "traceroute": {"last_run_at": now_iso},
                    "status": {"last_run_at": now_iso},
                    "download": {
                        "last_run_at": self._speedtest["last_run_at"],
                        "last_started_at": self._speedtest["last_started_at"],
                        "last_finished_at": self._speedtest["last_finished_at"],
                        "reason": self._speedtest["reason"],
                    },
                    "upload": {
                        "last_run_at": self._speedtest["last_run_at"],
                        "last_started_at": self._speedtest["last_started_at"],
                        "last_finished_at": self._speedtest["last_finished_at"],
                        "reason": self._speedtest["reason"],
                    },
                    "ookla": {
                        "last_run_at": self._speedtest["last_run_at"],
                        "last_started_at": self._speedtest["last_started_at"],
                        "last_finished_at": self._speedtest["last_finished_at"],
                        "reason": self._speedtest["reason"],
                    },
                },
                "methods": self._build_method_metrics(),
                "active_tests": ["download", "upload", "ookla"] if self._speedtest["running"] else [],
                "download_test_running": self._speedtest["running"],
                "upload_test_running": self._speedtest["running"],
            }

    async def get_metrics(self) -> dict[str, Any]:
        async with self._lock:
            return dict(self.metrics)

    def _build_method_metrics(self) -> dict[str, dict[str, float]]:
        if self._speedtest["last_run_at"] is None or self._speedtest.get("reason") != "ok":
            return {}
        metrics: dict[str, float] = {
            "download_mbps": float(self._speedtest.get("download_mbps", 0.0)),
            "upload_mbps": float(self._speedtest.get("upload_mbps", 0.0)),
        }
        ping_ms = self._speedtest.get("ping_ms")
        if isinstance(ping_ms, (int, float)):
            metrics["ping_ms"] = round(float(ping_ms), 2)
        return {"ookla": metrics}

    def _should_start_speedtest(self, *, now: datetime) -> bool:
        if self._speedtest["running"]:
            return False
        interval_seconds = int(self.options.get("speedtest_interval_seconds", 900))
        if interval_seconds <= 0:
            self._speedtest["reason"] = "disabled"
            return False
        last_started_at = self._speedtest.get("last_started_at")
        if not isinstance(last_started_at, str):
            return True
        try:
            last_started = datetime.fromisoformat(last_started_at)
        except ValueError:
            return True
        if last_started.tzinfo is None:
            last_started = last_started.replace(tzinfo=UTC)
        return (now - last_started.astimezone(UTC)).total_seconds() >= interval_seconds

    async def _run_speedtest(self) -> None:
        try:
            results = await asyncio.to_thread(
                self._run_speedtest_sync,
                float(self.options.get("speedtest_timeout_seconds", 120)),
            )
        except asyncio.CancelledError:
            await self._finish_speedtest(
                download_mbps=float(self._speedtest.get("download_mbps", 0.0)),
                upload_mbps=float(self._speedtest.get("upload_mbps", 0.0)),
                ping_ms=self._speedtest.get("ping_ms"),
                reason="cancelled",
            )
            raise
        except Exception as err:
            await self._finish_speedtest(
                download_mbps=float(self._speedtest.get("download_mbps", 0.0)),
                upload_mbps=float(self._speedtest.get("upload_mbps", 0.0)),
                ping_ms=self._speedtest.get("ping_ms"),
                reason=f"failed:{type(err).__name__}",
            )
            return
        await self._finish_speedtest(
            download_mbps=float(results.get("download_mbps", 0.0)),
            upload_mbps=float(results.get("upload_mbps", 0.0)),
            ping_ms=results.get("ping_ms"),
            reason="ok",
        )

    async def _finish_speedtest(
        self,
        *,
        download_mbps: float,
        upload_mbps: float,
        ping_ms: float | None,
        reason: str,
    ) -> None:
        finished_at = datetime.now(tz=UTC).isoformat()
        async with self._lock:
            self._speedtest.update(
                {
                    "download_mbps": max(0.0, round(download_mbps, 2)),
                    "upload_mbps": max(0.0, round(upload_mbps, 2)),
                    "ping_ms": round(float(ping_ms), 2) if isinstance(ping_ms, (int, float)) else None,
                    "running": False,
                    "last_run_at": finished_at,
                    "last_finished_at": finished_at,
                    "reason": reason,
                }
            )
            self.metrics = {
                **self.metrics,
                "timestamp": finished_at,
                "online": bool(self._latest_probe["online"])
                or max(0.0, round(download_mbps, 2)) > 0.0
                or max(0.0, round(upload_mbps, 2)) > 0.0,
                "download_mbps": max(0.0, round(download_mbps, 2)),
                "upload_mbps": max(0.0, round(upload_mbps, 2)),
                "tests": {
                    **self.metrics.get("tests", {}),
                    "download": {
                        "last_run_at": finished_at,
                        "last_started_at": self._speedtest["last_started_at"],
                        "last_finished_at": finished_at,
                        "reason": reason,
                    },
                    "upload": {
                        "last_run_at": finished_at,
                        "last_started_at": self._speedtest["last_started_at"],
                        "last_finished_at": finished_at,
                        "reason": reason,
                    },
                    "ookla": {
                        "last_run_at": finished_at,
                        "last_started_at": self._speedtest["last_started_at"],
                        "last_finished_at": finished_at,
                        "reason": reason,
                    },
                },
                "methods": self._build_method_metrics(),
                "active_tests": [],
                "download_test_running": False,
                "upload_test_running": False,
            }

    def _run_speedtest_sync(self, timeout: float) -> dict[str, float | None]:
        import speedtest

        runner = speedtest.Speedtest(timeout=timeout, secure=True)
        runner.get_best_server()
        download_bits_per_second = float(runner.download())
        upload_bits_per_second = float(runner.upload(pre_allocate=False))
        results = runner.results.dict()
        ping_ms = results.get("ping")
        return {
            "download_mbps": download_bits_per_second / 1_000_000.0,
            "upload_mbps": upload_bits_per_second / 1_000_000.0,
            "ping_ms": float(ping_ms) if isinstance(ping_ms, (int, float)) else None,
        }

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
            connection_coro = asyncio.open_connection(host, CONNECT_PORT)
            _, writer = await asyncio.wait_for(connection_coro, timeout=timeout)
        except (OSError, TimeoutError):
            return None
        try:
            elapsed = (asyncio.get_running_loop().time() - started) * 1000.0
            return round(elapsed, 2)
        finally:
            if writer is not None:
                with contextlib.suppress(OSError):
                    writer.close()
                    await writer.wait_closed()


async def metrics_handler(request: web.Request) -> web.Response:
    state: AgentState = request.app["state"]
    token = str(state.options.get("token", "")).strip()
    if token:
        header = request.headers.get("Authorization", "")
        prefix = "Bearer "
        if not header.startswith(prefix) or not secrets.compare_digest(
            header[len(prefix) :],
            token,
        ):
            return web.json_response({"error": "unauthorized"}, status=401)
    return web.json_response(await state.get_metrics())


async def health_handler(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def update_loop(app: web.Application) -> None:
    state: AgentState = app["state"]
    while True:
        with contextlib.suppress(Exception):
            await state.update_metrics()
        await asyncio.sleep(int(state.options.get("interval_seconds", 60)))


async def start_background(app: web.Application) -> None:
    app["update_task"] = asyncio.create_task(update_loop(app))


async def stop_background(app: web.Application) -> None:
    state: AgentState = app["state"]
    speedtest_task = state._speedtest_task
    if speedtest_task is not None and not speedtest_task.done():
        speedtest_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await speedtest_task
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
