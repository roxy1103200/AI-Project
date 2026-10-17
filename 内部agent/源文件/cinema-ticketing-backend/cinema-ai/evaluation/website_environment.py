"""Start an owned, loopback-only website stack with isolated H2 and Redis fixtures.

Run from cinema-ai: python -m evaluation.website_environment --output ../target/website-regression
The private connection file stays under ignored target/. Stop only recorded owned PIDs.
"""

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import httpx
from dotenv import dotenv_values

AI = Path(__file__).resolve().parents[1]
BACKEND = AI.parent
ROOT = BACKEND.parent
PORTS = {
    "redis": 16379,
    "database": 19092,
    "fixture": 18090,
    "java": 18080,
    "proxy": 18081,
    "mcp": 18020,
    "agent": 18000,
    "gateway": 18010,
    "web": 15173,
}


def wait_http(url: str, headers: dict[str, str] | None = None, seconds: int = 90) -> None:
    deadline = time.monotonic() + seconds
    with httpx.Client(trust_env=False, timeout=2) as client:
        while time.monotonic() < deadline:
            try:
                if client.get(url, headers=headers).is_success:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.3)
    raise RuntimeError(f"Service did not become ready: {url}")


def start(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    if (output / "private.json").exists():
        raise RuntimeError("Use a new output directory; existing process evidence is preserved")
    for name, port in PORTS.items():
        with socket.socket() as listener:
            try:
                listener.bind(("127.0.0.1", port))
            except OSError as exc:
                raise RuntimeError(f"Dedicated {name} port {port} is occupied") from exc
    private = {
        "token": secrets.token_hex(32),
        "fixture_token": secrets.token_hex(32),
        "db_password": secrets.token_hex(24),
        "account_password": "Web!" + secrets.token_hex(12),
        "ports": PORTS,
        "processes": {},
        "process_created": {},
        "output": str(output),
    }
    path = output / "private.json"
    env = os.environ.copy()
    env.update({key: value for key, value in dotenv_values(AI / ".env").items() if value is not None})
    env.update(
        {
            "PYTHONUTF8": "1",
            "AI_INTERNAL_TOKEN": private["token"],
            "WEBSITE_FIXTURE_TOKEN": private["fixture_token"],
            "WEBSITE_FIXTURE_DB_PASSWORD": private["db_password"],
            "WEBSITE_FIXTURE_ACCOUNT_PASSWORD": private["account_password"],
            "JAVA_API_URL": "http://127.0.0.1:18081",
            "CINEMA_MCP_URL": "http://127.0.0.1:18020/mcp",
            "AGENT_API_URL": "http://127.0.0.1:18081/agent",
            "AI_REDIS_URL": "redis://127.0.0.1:16379/0",
            "AI_AUTH_REDIS_URL": "redis://127.0.0.1:16379/0",
            "AI_REDIS_PREFIX": "website-regression:",
            "MEMORY_ENABLED": "false",
            "GLM_L1_ENABLED": "false",
            "AGENT_AB_FORCE_VARIANT": "A",
            "RERANK_ENABLED": "false",
            "DIFY_API_KEY": "unused-website-regression",
            "PAYMENT_ENABLED": "false",
            "PAYMENT_MOCK_ENABLED": "false",
            "DB_URL": "jdbc:h2:tcp://127.0.0.1:19092/mem:website;MODE=MySQL;DATABASE_TO_LOWER=TRUE",
            "DB_USERNAME": "sa",
            "DB_PASSWORD": private["db_password"],
            "SPRING_DATASOURCE_DRIVER_CLASS_NAME": "org.h2.Driver",
            "SPRING_DATA_REDIS_HOST": "127.0.0.1",
            "SPRING_DATA_REDIS_PORT": "16379",
            "SPRING_PROFILES_ACTIVE": "website-regression",
            "SPRING_SQL_INIT_MODE": "never",
            "AUTH_INITIALIZE_SCHEMA": "false",
            "REPORTS_INITIALIZE_SCHEMA": "false",
            "PAYMENT_INITIALIZE_SCHEMA": "false",
            "AI_FEEDBACK_INITIALIZE_SCHEMA": "false",
            "AI_MEMORY_INITIALIZE_SCHEMA": "false",
            "REVIEWS_INITIALIZE_SCHEMA": "false",
            "SPRING_RABBITMQ_LISTENER_SIMPLE_AUTO_STARTUP": "false",
            "SPRING_RABBITMQ_LISTENER_DIRECT_AUTO_STARTUP": "false",
            "SPRING_RABBITMQ_DYNAMIC": "false",
            "ORDER_RECONCILE_INITIAL_DELAY_MS": "2147483647",
            "PAYMENT_RECONCILE_INITIAL_DELAY_MS": "2147483647",
            "SERVER_PORT": "18080",
            "LOG_FILE": str(output / "java-app.log"),
            "RATE_LIMIT_REQUESTS_PER_MINUTE": "10000",
            "CINEMA_WEB_PORT": "15173",
            "CINEMA_JAVA_PROXY": "http://127.0.0.1:18081",
            "CINEMA_GATEWAY_PROXY": "http://127.0.0.1:18010",
        }
    )
    classpath = (BACKEND / "target/website-classpath.txt").read_text().strip()
    redis_jar = next(Path(item) for item in classpath.split(os.pathsep) if "embedded-redis" in item)
    executable = output / "redis-server.exe"
    with zipfile.ZipFile(redis_jar) as archive:
        executable.write_bytes(archive.read("redis-server-5.0.14.1-windows-amd64.exe"))

    def launch(name: str, arguments: list[str], cwd: Path) -> None:
        with (output / f"{name}.log").open("wb") as log:
            process = subprocess.Popen(
                arguments,
                cwd=cwd,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        private["processes"][name] = process.pid
        stamp = subprocess.check_output(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                f"(Get-Process -Id {process.pid}).StartTime.ToUniversalTime().Ticks",
            ],
            creationflags=subprocess.CREATE_NO_WINDOW,
            text=True,
        ).strip()
        private["process_created"][name] = stamp
        path.write_text(json.dumps(private, indent=2), encoding="utf-8")
        print(f"Started owned {name} pid={process.pid}", flush=True)

    java = os.getenv("WEBSITE_JAVA", r"D:\java\jdk21\bin\java.exe")
    # Keep Windows AF_UNIX temporary paths below their length limit.
    java_tmp = ROOT / "outputs/jtmp"
    java_tmp.mkdir(parents=True, exist_ok=True)
    java_args = [
        java,
        "-Duser.timezone=Asia/Shanghai",
        f"-Djava.io.tmpdir={java_tmp}",
        f"-Djdk.net.unixdomain.tmpdir={java_tmp}",
    ]
    main_cp = str(BACKEND / "target/classes") + os.pathsep + classpath
    launch(
        "redis", [str(executable), "--bind", "127.0.0.1", "--port", "16379", "--save", "", "--appendonly", "no"], output
    )
    launch(
        "fixture",
        [
            *java_args,
            "-cp",
            str(BACKEND / "target/test-classes") + os.pathsep + main_cp,
            "com.cinema.ticketing.service.WebsiteFixtureServer",
        ],
        BACKEND,
    )
    wait_http("http://127.0.0.1:18090/snapshot", {"X-Fixture-Token": private["fixture_token"]})
    launch("java", [*java_args, "-cp", main_cp, "com.cinema.ticketing.CinemaTicketingApplication"], BACKEND)
    wait_http("http://127.0.0.1:18080/api/health")
    launch(
        "proxy",
        [sys.executable, "-m", "uvicorn", "evaluation.website_proxy:app", "--host", "127.0.0.1", "--port", "18081"],
        AI,
    )
    launch("mcp", [sys.executable, "-m", "uvicorn", "app.mcp_server:app", "--host", "127.0.0.1", "--port", "18020"], AI)
    wait_http("http://127.0.0.1:18020/health")
    launch("agent", [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "18000"], AI)
    wait_http("http://127.0.0.1:18000/health")
    launch(
        "gateway",
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "18010"],
        BACKEND / "cinema-ai-gateway",
    )
    wait_http("http://127.0.0.1:18010/internal/runtime", {"X-Internal-Token": private["token"]})
    launch(
        "web",
        [r"C:\Program Files\nodejs\node.exe", "node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--strictPort"],
        ROOT / "cinema-ticketing-frontend",
    )
    wait_http("http://127.0.0.1:15173/__cinema_runtime")
    print("Isolated website ready at http://127.0.0.1:15173 (private configuration under ignored target)", flush=True)


def stop(output: Path) -> None:
    path = output / "private.json"
    private = json.loads(path.read_text(encoding="utf-8"))
    # Only PIDs created by this launcher, never enumerate/kill the user's original services.
    for name, pid in reversed(list(private["processes"].items())):
        expected = private.get("process_created", {}).get(name)
        if expected:
            probe = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-Command",
                    f"(Get-Process -Id {pid} -ErrorAction SilentlyContinue).StartTime.ToUniversalTime().Ticks",
                ],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if probe.stdout.strip() != expected:
                print(f"Owned {name}: process already exited or PID reused; left untouched", flush=True)
                continue
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW
        )
        print(f"Owned {name}: stop exit={result.returncode}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stop", action="store_true")
    options = parser.parse_args()
    (stop if options.stop else start)(options.output.resolve())
