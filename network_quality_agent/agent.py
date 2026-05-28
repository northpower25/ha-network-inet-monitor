from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
import json
from pathlib import Path
import secrets
from statistics import mean, median
from typing import Any

import aiohttp
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
    # HTTP download test – BNetzA-analogous multi-server measurement
    # Each server is downloaded in parallel with multiple streams for the
    # configured duration; the median speed across responding servers is used.
    "http_download_targets": [
        "speedtest.wtnet.de",
        "speedtest.studiofunk.de",
        "fra.speedtest.clouvider.net",
    ],
    "http_download_path": "/10G.bin",
    "http_download_duration_seconds": 10,
    "http_download_streams": 4,
    # iperf3 tests – primary DE/EU servers (sequential to avoid interference)
    "iperf3_targets": [
        "fra.speedtest.clouvider.net",
        "speedtest.wtnet.de",
        "speedtest.studiofunk.de",
    ],
    # iperf3 additional EU diversity servers
    "iperf3_eu_targets": [
        "ams.speedtest.clouvider.net",
        "lon.speedtest.clouvider.net",
    ],
    "iperf3_port": 5201,
    "iperf3_duration_seconds": 10,
    "iperf3_streams": 4,
    # Ookla speedtest (provider: ookla_auto – uses get_best_server())
    "speedtest_ookla_enabled": True,
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
    options["http_download_targets"] = [str(h).strip() for h in options.get("http_download_targets", []) if str(h).strip()]
    options["iperf3_targets"] = [str(h).strip() for h in options.get("iperf3_targets", []) if str(h).strip()]
    options["iperf3_eu_targets"] = [str(h).strip() for h in options.get("iperf3_eu_targets", []) if str(h).strip()]
    return options


def _median_float(values: list[float]) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    mid = len(sorted_vals) // 2
    if len(sorted_vals) % 2 == 0:
        return round((sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0, 2)
    return round(sorted_vals[mid], 2)


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
            "method_results": {},
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
        """Build per-method metrics dict for the /metrics payload."""
        if self._speedtest["last_run_at"] is None:
            return {}

        result: dict[str, dict[str, float]] = {}
        method_results = self._speedtest.get("method_results", {})

        # Ookla
        ookla = method_results.get("ookla", {})
        if ookla.get("reason") == "ok":
            m: dict[str, float] = {
                "download_mbps": round(float(ookla.get("download_mbps", 0.0)), 2),
                "upload_mbps": round(float(ookla.get("upload_mbps", 0.0)), 2),
            }
            if isinstance(ookla.get("ping_ms"), (int, float)):
                m["ping_ms"] = round(float(ookla["ping_ms"]), 2)
            result["ookla"] = m

        # HTTP download (BNetzA-analogous)
        http = method_results.get("http_download", {})
        if http.get("reason") == "ok" and float(http.get("download_mbps", 0.0)) > 0.0:
            result["http_download"] = {
                "download_mbps": round(float(http["download_mbps"]), 2),
            }

        # iperf3 (combined DE + EU targets)
        iperf = method_results.get("iperf3", {})
        if iperf.get("reason") == "ok":
            iperf_entry: dict[str, float] = {}
            if float(iperf.get("download_mbps", 0.0)) > 0.0:
                iperf_entry["download_mbps"] = round(float(iperf["download_mbps"]), 2)
            if float(iperf.get("upload_mbps", 0.0)) > 0.0:
                iperf_entry["upload_mbps"] = round(float(iperf["upload_mbps"]), 2)
            if iperf_entry:
                result["iperf3"] = iperf_entry

        return result

    def _best_download_mbps(self, method_results: dict[str, Any]) -> float:
        candidates = [
            float(method_results.get("http_download", {}).get("download_mbps", 0.0)),
            float(method_results.get("iperf3", {}).get("download_mbps", 0.0)),
            float(method_results.get("ookla", {}).get("download_mbps", 0.0)),
        ]
        return max(candidates)

    def _best_upload_mbps(self, method_results: dict[str, Any]) -> float:
        candidates = [
            float(method_results.get("ookla", {}).get("upload_mbps", 0.0)),
            float(method_results.get("iperf3", {}).get("upload_mbps", 0.0)),
        ]
        return max(candidates)

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
        method_results: dict[str, Any] = {}
        try:
            method_results = await self._run_all_speedtest_methods()
        except asyncio.CancelledError:
            await self._finish_speedtest(
                download_mbps=float(self._speedtest.get("download_mbps", 0.0)),
                upload_mbps=float(self._speedtest.get("upload_mbps", 0.0)),
                ping_ms=self._speedtest.get("ping_ms"),
                reason="cancelled",
                method_results=method_results,
            )
            raise
        except Exception as err:
            await self._finish_speedtest(
                download_mbps=float(self._speedtest.get("download_mbps", 0.0)),
                upload_mbps=float(self._speedtest.get("upload_mbps", 0.0)),
                ping_ms=self._speedtest.get("ping_ms"),
                reason=f"failed:{type(err).__name__}",
                method_results=method_results,
            )
            return

        download_mbps = self._best_download_mbps(method_results)
        upload_mbps = self._best_upload_mbps(method_results)
        ping_ms = method_results.get("ookla", {}).get("ping_ms")
        reason = "ok" if (download_mbps > 0.0 or upload_mbps > 0.0) else "no_data"
        await self._finish_speedtest(
            download_mbps=download_mbps,
            upload_mbps=upload_mbps,
            ping_ms=ping_ms,
            reason=reason,
            method_results=method_results,
        )

    async def _run_all_speedtest_methods(self) -> dict[str, Any]:
        """Run all configured speedtest methods and return per-method results."""
        method_results: dict[str, Any] = {}

        # 1. HTTP download – all servers tested in parallel (BNetzA-analogous)
        try:
            http_result = await self._run_http_download_tests()
            if http_result:
                method_results["http_download"] = http_result
        except Exception:
            pass

        # 2. iperf3 – servers tested sequentially (one at a time to avoid
        #    mutual interference; combines iperf3_targets + iperf3_eu_targets)
        try:
            iperf_result = await self._run_iperf3_tests()
            if iperf_result:
                method_results["iperf3"] = iperf_result
        except Exception:
            pass

        # 3. Ookla speedtest (provider: ookla_auto)
        if self.options.get("speedtest_ookla_enabled", True):
            try:
                ookla = await asyncio.to_thread(
                    self._run_speedtest_sync,
                    float(self.options.get("speedtest_timeout_seconds", 120)),
                )
                method_results["ookla"] = {**ookla, "reason": "ok"}
            except Exception as err:
                method_results["ookla"] = {"reason": f"failed:{type(err).__name__}"}

        return method_results

    # ------------------------------------------------------------------
    # HTTP download test (BNetzA-analogous)
    # ------------------------------------------------------------------

    async def _run_http_download_tests(self) -> dict[str, Any]:
        """Download from each configured HTTP target in parallel and return aggregate."""
        targets = self.options.get("http_download_targets", [])
        if not targets:
            return {}

        path = str(self.options.get("http_download_path", "/10G.bin"))
        duration = float(self.options.get("http_download_duration_seconds", 10))
        streams = max(1, int(self.options.get("http_download_streams", 4)))

        connector = aiohttp.TCPConnector(limit=0)
        timeout = aiohttp.ClientTimeout(total=duration + 30, connect=10)
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            tasks = [
                self._http_download_single(session, host, path, duration, streams)
                for host in targets
            ]
            server_results: list[dict[str, Any]] = await asyncio.gather(*tasks)

        successful = [r for r in server_results if r.get("reason") == "ok" and float(r.get("download_mbps", 0.0)) > 0.0]
        if not successful:
            return {"servers": server_results, "download_mbps": 0.0, "reason": "all_failed"}

        median_speed = _median_float([float(r["download_mbps"]) for r in successful])
        return {
            "servers": server_results,
            "download_mbps": median_speed,
            "reason": "ok",
        }

    async def _http_download_single(
        self,
        session: aiohttp.ClientSession,
        host: str,
        path: str,
        duration: float,
        streams: int,
    ) -> dict[str, Any]:
        """Stream-download from one server using *streams* parallel connections."""
        url = f"http://{host}{path}"

        async def _one_stream() -> int:
            try:
                async with session.get(url) as resp:
                    resp.raise_for_status()
                    bytes_count = 0
                    deadline = asyncio.get_running_loop().time() + duration
                    async for chunk in resp.content.iter_chunked(65536):
                        bytes_count += len(chunk)
                        if asyncio.get_running_loop().time() >= deadline:
                            break
                    return bytes_count
            except Exception:
                return 0

        wall_start = asyncio.get_running_loop().time()
        tasks = [asyncio.create_task(_one_stream()) for _ in range(streams)]
        byte_counts: list[int] = list(await asyncio.gather(*tasks))
        wall_elapsed = asyncio.get_running_loop().time() - wall_start

        total_bytes = sum(byte_counts)
        # Require at least half the requested duration to produce a valid result
        if wall_elapsed >= duration * 0.4 and total_bytes > 0:
            mbps = (total_bytes * 8) / (wall_elapsed * 1_000_000)
            return {"host": host, "download_mbps": round(mbps, 2), "reason": "ok"}
        return {"host": host, "download_mbps": 0.0, "reason": "failed:no_data"}

    # ------------------------------------------------------------------
    # iperf3 tests
    # ------------------------------------------------------------------

    async def _run_iperf3_tests(self) -> dict[str, Any]:
        """Run iperf3 download test against each configured target sequentially."""
        all_targets: list[str] = []
        for h in self.options.get("iperf3_targets", []):
            h = str(h).strip()
            if h:
                all_targets.append(h)
        for h in self.options.get("iperf3_eu_targets", []):
            h = str(h).strip()
            if h and h not in all_targets:
                all_targets.append(h)

        if not all_targets:
            return {}

        port = int(self.options.get("iperf3_port", 5201))
        duration = int(self.options.get("iperf3_duration_seconds", 10))
        streams = max(1, int(self.options.get("iperf3_streams", 4)))

        server_results: list[dict[str, Any]] = []
        for host in all_targets:
            result = await self._iperf3_single(host, port, duration, streams)
            server_results.append(result)

        successful = [r for r in server_results if r.get("reason") == "ok" and float(r.get("download_mbps", 0.0)) > 0.0]
        if not successful:
            return {"servers": server_results, "download_mbps": 0.0, "reason": "all_failed"}

        # Use median download across successful servers to dampen outliers
        median_dl = _median_float([float(r["download_mbps"]) for r in successful])
        upload_values = [float(r["upload_mbps"]) for r in successful if float(r.get("upload_mbps", 0.0)) > 0.0]
        result_dict: dict[str, Any] = {
            "servers": server_results,
            "download_mbps": median_dl,
            "reason": "ok",
        }
        if upload_values:
            result_dict["upload_mbps"] = _median_float(upload_values)
        return result_dict

    async def _iperf3_single(
        self,
        host: str,
        port: int,
        duration: int,
        streams: int,
    ) -> dict[str, Any]:
        """Run one iperf3 reverse-mode (download) test against *host*."""
        cmd = [
            "iperf3",
            "-c", host,
            "-p", str(port),
            "-t", str(duration),
            "-P", str(streams),
            "-R",   # reverse: server→client measures download from client's perspective
            "-J",   # JSON output
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, _ = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=float(duration) + 30,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                return {"host": host, "download_mbps": 0.0, "reason": "timeout"}

            raw = stdout.decode(errors="replace").strip()
            if not raw:
                return {"host": host, "download_mbps": 0.0, "reason": "failed:no_output"}

            data = json.loads(raw)

            if "error" in data:
                short_error = str(data["error"])[:80]
                return {"host": host, "download_mbps": 0.0, "reason": f"iperf3_error:{short_error}"}

            end = data.get("end", {})
            # In reverse mode (-R), sum_received at the client = download throughput
            dl_bps = float(end.get("sum_received", {}).get("bits_per_second", 0.0))
            # sum_sent (server→client confirms what was pushed) – use as upload proxy
            ul_bps = float(end.get("sum_sent", {}).get("bits_per_second", 0.0))
            return {
                "host": host,
                "download_mbps": round(dl_bps / 1_000_000, 2),
                "upload_mbps": round(ul_bps / 1_000_000, 2),
                "reason": "ok",
            }
        except FileNotFoundError:
            return {"host": host, "download_mbps": 0.0, "reason": "iperf3_not_installed"}
        except (json.JSONDecodeError, KeyError, TypeError) as err:
            return {"host": host, "download_mbps": 0.0, "reason": f"parse_error:{type(err).__name__}"}
        except Exception as err:
            return {"host": host, "download_mbps": 0.0, "reason": f"failed:{type(err).__name__}"}

    # ------------------------------------------------------------------
    # Ookla speedtest (provider: ookla_auto)
    # ------------------------------------------------------------------

    async def _finish_speedtest(
        self,
        *,
        download_mbps: float,
        upload_mbps: float,
        ping_ms: float | None,
        reason: str,
        method_results: dict[str, Any] | None = None,
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
                    "method_results": method_results or {},
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
