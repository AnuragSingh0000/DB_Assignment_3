"""Managed test harness for Module B verification."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import requests

from config import (
    TEST_API_PORT,
    TEST_DB_HEALTHCHECK_CMD,
    TEST_DB_RESTART_CMD,
)
from helpers import clear_session_cache

_ACTIVE_HARNESS: "ManagedHarness | None" = None


def set_active_harness(harness: "ManagedHarness | None") -> None:
    global _ACTIVE_HARNESS
    _ACTIVE_HARNESS = harness


def get_active_harness() -> "ManagedHarness | None":
    return _ACTIVE_HARNESS


class ManagedHarness:
    def __init__(self, workdir: str | Path, *, port: int = TEST_API_PORT, pool_size: int = 5):
        self.workdir = Path(workdir)
        self.port = port
        self.pool_size = pool_size
        self.base_url = f"http://127.0.0.1:{port}"
        self.results_dir = self.workdir / "loadtest" / "results"
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self._server_log_path = self.results_dir / "managed_server.log"
        self._server_log_handle = None
        self._server_process: subprocess.Popen[str] | None = None

    def __enter__(self) -> "ManagedHarness":
        self.start_api()
        set_active_harness(self)
        os.environ["TEST_BASE_URL"] = self.base_url
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        set_active_harness(None)
        self.stop_api()

    def start_api(self) -> None:
        if self._server_process and self._server_process.poll() is None:
            return
        self._server_log_handle = self._server_log_path.open("a", encoding="utf-8")
        env = os.environ.copy()
        env["TEST_BASE_URL"] = self.base_url
        env["DB_POOL_SIZE"] = str(self.pool_size)
        cmd = [
            "../.venv/bin/python",
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
            "--no-access-log",
        ]
        self._server_process = subprocess.Popen(
            cmd,
            cwd=self.workdir,
            env=env,
            stdout=self._server_log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.wait_for_api()
        clear_session_cache()

    def stop_api(self) -> None:
        if not self._server_process:
            return
        if self._server_process.poll() is None:
            self._server_process.terminate()
            try:
                self._server_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._server_process.kill()
                self._server_process.wait(timeout=5)
        self._server_process = None
        if self._server_log_handle:
            self._server_log_handle.close()
            self._server_log_handle = None
        clear_session_cache()

    def restart_api(self) -> None:
        self.stop_api()
        self.start_api()

    def wait_for_api(self, timeout: int = 30) -> None:
        deadline = time.time() + timeout
        last_error = None
        while time.time() < deadline:
            try:
                response = requests.get(f"{self.base_url}/health", timeout=2)
                if response.status_code == 200:
                    return
            except requests.RequestException as exc:
                last_error = exc
            time.sleep(0.5)
        raise RuntimeError(f"Managed API did not become healthy at {self.base_url}: {last_error}")

    def _run_shell(self, command: str, *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=self.workdir,
            shell=True,
            text=True,
            capture_output=True,
            timeout=timeout,
        )

    def restart_database(self) -> None:
        if not TEST_DB_RESTART_CMD.strip():
            raise RuntimeError("TEST_DB_RESTART_CMD is required for full-stack restart verification.")
        result = self._run_shell(TEST_DB_RESTART_CMD, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(
                "Database restart command failed: "
                f"{TEST_DB_RESTART_CMD}\nstdout: {result.stdout}\nstderr: {result.stderr}"
            )
        self.wait_for_database()
        clear_session_cache()

    def wait_for_database(self, timeout: int = 60) -> None:
        command = TEST_DB_HEALTHCHECK_CMD.strip()
        if not command:
            raise RuntimeError("TEST_DB_HEALTHCHECK_CMD is required for full-stack restart verification.")
        deadline = time.time() + timeout
        last_result: subprocess.CompletedProcess[str] | None = None
        while time.time() < deadline:
            last_result = self._run_shell(command, timeout=15)
            if last_result.returncode == 0:
                return
            time.sleep(1)
        stdout = last_result.stdout if last_result else ""
        stderr = last_result.stderr if last_result else ""
        raise RuntimeError(f"Database health check failed: {command}\nstdout: {stdout}\nstderr: {stderr}")

    def restart_stack(self) -> None:
        self.stop_api()
        self.restart_database()
        self.start_api()
