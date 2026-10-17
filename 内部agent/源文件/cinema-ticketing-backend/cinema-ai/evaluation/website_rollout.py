"""Reload verified local project services and check builds without changing business rows.

The sandbox configuration is loaded privately from its existing file. This does not
perform a payment, refund, order mutation or database migration.
"""

import json
import os
import subprocess
from pathlib import Path

import httpx
from dotenv import dotenv_values

from evaluation.website_environment import AI, BACKEND, ROOT, wait_http


def powershell(script: str) -> str:
    return subprocess.check_output(
        ["powershell.exe", "-NoProfile", "-Command", script], text=True, creationflags=subprocess.CREATE_NO_WINDOW
    ).strip()


def reload_local() -> None:
    output = BACKEND / "target/website-rollout"
    output.mkdir(parents=True, exist_ok=True)
    # Inspect only the owning listener and fixed project fingerprints; never print its command line.
    inspected = powershell(
        "$c=Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction Stop | Select-Object -First 1; "
        "$p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$c.OwningProcess); "
        "$q=Get-Process -Id $p.ProcessId; "
        "@{pid=$p.ProcessId; executable=$p.ExecutablePath; started=$q.StartTime.ToUniversalTime().Ticks.ToString(); "
        "project=($p.CommandLine.Contains('cinema-ticketing-backend') -and $p.CommandLine.Contains('profiles.active=local'))} | ConvertTo-Json -Compress"
    )
    process = json.loads(inspected)
    if not process["project"] or Path(process["executable"]).name.lower() != "java.exe":
        raise RuntimeError("Port 8080 is not the verified local project Java service")
    with httpx.Client(trust_env=False, timeout=10) as client:
        before = client.get("http://127.0.0.1:8080/api/payments/config").json()
    env = os.environ.copy()
    env.update(
        {key: value for key, value in dotenv_values(BACKEND / ".env.alipay-sandbox").items() if value is not None}
    )
    for key in (
        "AUTH_INITIALIZE_SCHEMA",
        "REPORTS_INITIALIZE_SCHEMA",
        "PAYMENT_INITIALIZE_SCHEMA",
        "AI_FEEDBACK_INITIALIZE_SCHEMA",
        "AI_MEMORY_INITIALIZE_SCHEMA",
        "REVIEWS_INITIALIZE_SCHEMA",
    ):
        env[key] = "false"
    java_token = dotenv_values(AI / ".env").get("AI_INTERNAL_TOKEN", "local-internal-token")
    env["AI_INTERNAL_TOKEN"] = java_token
    task_tmp = ROOT / "outputs/jtmp"
    task_tmp.mkdir(parents=True, exist_ok=True)
    # Recheck process creation time immediately before stopping the originally inspected PID.
    powershell(
        f"$p=Get-Process -Id {int(process['pid'])} -ErrorAction Stop; "
        f"if($p.StartTime.ToUniversalTime().Ticks.ToString() -ne '{process['started']}') {{throw 'Java PID changed'}}; "
        "Stop-Process -Id $p.Id -Force"
    )
    with (output / "java.log").open("wb") as log:
        child = subprocess.Popen(
            [
                process["executable"],
                "-Duser.timezone=Asia/Shanghai",
                f"-Djdk.net.unixdomain.tmpdir={task_tmp}",
                "-jar",
                str(BACKEND / "target/cinema-ticketing-backend-0.0.1-SNAPSHOT.jar"),
                "--spring.profiles.active=local",
                "--server.port=8080",
            ],
            cwd=BACKEND,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    wait_http("http://127.0.0.1:8080/api/health")
    with httpx.Client(trust_env=False, timeout=10) as client:
        after = client.get("http://127.0.0.1:8080/api/payments/config").json()
    if before.get("data") != after.get("data"):
        raise RuntimeError("Payment capability changed after reload; inspect private local configuration")
    print(f"Java reloaded pid={child.pid}; public payment capabilities preserved", flush=True)
    for service, port in (("mcp", 8020), ("agent", 8000), ("gateway", 8010)):
        for action in ("stop", "start"):
            script = BACKEND / f"{action}-ai-local.ps1"
            with (output / f"{action}-{service}.log").open("wb") as log:
                result = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-File", str(script), "-Service", service],
                    cwd=BACKEND,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            if result.returncode:
                raise RuntimeError(f"Failed to {action} the verified project {service}; see rollout log")
        wait_http(f"http://127.0.0.1:{port}/internal/runtime", {"X-Internal-Token": java_token})
        print(f"{service} reloaded; protected runtime responds", flush=True)
    (output / "result.json").write_text(
        json.dumps(
            {
                "java_reloaded": True,
                "payment_capabilities_preserved": True,
                "components": ["java", "mcp", "agent", "gateway"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    reload_local()
