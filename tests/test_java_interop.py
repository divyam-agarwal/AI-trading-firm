"""Proof of interop: the Python a2a-sdk client talks to the Java agent unchanged.

Skipped unless Java + Maven are present. Runs key-free via FUNDAMENTALS_LLM_STUB=1,
so it does not call Claude and needs no ANTHROPIC_API_KEY.
"""
import asyncio
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from orchestrator.a2a_client import call_agent

ROOT = Path(__file__).resolve().parent.parent
JAVA_DIR = ROOT / "agents" / "fundamentals-java"
JAR = JAVA_DIR / "target" / "fundamentals-java-0.1.0.jar"
PORT = 9001
BASE_URL = f"http://127.0.0.1:{PORT}"

pytestmark = pytest.mark.skipif(
    shutil.which("java") is None or shutil.which("mvn") is None,
    reason="Java/Maven not installed; skipping cross-language interop test",
)


def _build_jar() -> None:
    subprocess.run(
        ["mvn", "-q", "-f", str(JAVA_DIR / "pom.xml"), "package", "-DskipTests"],
        check=True,
    )


def _wait_for_port(port: int, timeout: float = 40.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.25)
    raise TimeoutError(f"Java agent did not start on port {port}")


@pytest.fixture(scope="module")
def java_agent():
    if not JAR.exists():
        _build_jar()
    env = {**os.environ, "FUNDAMENTALS_LLM_STUB": "1"}
    proc = subprocess.Popen(["java", "-jar", str(JAR)], env=env)
    try:
        _wait_for_port(PORT)
        yield BASE_URL
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_agent_card_resolves(java_agent):
    card = httpx.get(f"{java_agent}/.well-known/agent-card.json", timeout=10).json()
    assert card["name"] == "Fundamentals Analyst"
    assert card["supportedInterfaces"][0]["url"] == f"{BASE_URL}/"


def test_python_client_round_trips_against_java(java_agent):
    reply = asyncio.run(call_agent(java_agent, "AAPL"))
    assert reply, "expected a non-empty reply from the Java agent"
    assert "AAPL" in reply  # the stub echoes the ticker
