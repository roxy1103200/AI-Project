"""Compare real Qwen calls on current/previous workflows and real development queries."""

import argparse
import asyncio
import contextvars
import hashlib
import importlib
import json
import logging
import os
import random
import shutil
import socket
import subprocess
import sys
import threading
import time
import types
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from dotenv import load_dotenv

from evaluation.metrics import PRICE_SOURCE, judge, summarize

AI_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = AI_ROOT.parent
REPO_ROOT = BACKEND_ROOT.parent
ACTIVE: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("evaluation_trial")


class ObservedModel:
    """Record provider-reported usage without changing prompts or exposing credentials."""

    def __init__(self, inner: Any, stage: str = "answer") -> None:
        self.inner, self.stage = inner, stage

    def bind(self, **kwargs: Any) -> "ObservedModel":
        """Preserve the existing structured-understanding call and its parameters."""
        return ObservedModel(self.inner.bind(**kwargs), "understanding")

    def bind_tools(self, *args: Any, **kwargs: Any) -> "ObservedModel":
        """Preserve the exact model tool definitions and selection mode."""
        return ObservedModel(self.inner.bind_tools(*args, **kwargs), "decision")

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        """Count attempted logical model calls, including ones that fail."""
        call = {"stage": self.stage, "usage": None, "error": None}
        ACTIVE.get()["model_calls"].append(call)
        started = time.perf_counter()
        try:
            result = await self.inner.ainvoke(*args, **kwargs)
            call["usage"] = result.usage_metadata
            call["resolved_model"] = result.response_metadata.get("model_name")
            if self.stage == "decision":
                ACTIVE.get()["proposals"].extend(result.tool_calls)
            return result
        except BaseException as exc:
            call["error"] = type(exc).__name__
            raise
        finally:
            call["duration_ms"] = (time.perf_counter() - started) * 1000

    async def astream(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        """Request final stream usage; never substitute token estimates for missing usage."""
        call = {"stage": self.stage, "usage": None, "error": None}
        ACTIVE.get()["model_calls"].append(call)
        started = time.perf_counter()
        try:
            async for chunk in self.inner.astream(*args, stream_usage=True, **kwargs):
                if chunk.usage_metadata:
                    call["usage"] = chunk.usage_metadata
                yield chunk
        except BaseException as exc:
            call["error"] = type(exc).__name__
            raise
        finally:
            call["duration_ms"] = (time.perf_counter() - started) * 1000


class RecordedMcp:
    """Observe real MCP calls and results through the unmodified SDK client."""

    def __init__(self, client: Any) -> None:
        self.client = client

    async def call_tool(self, name: str, arguments: dict[str, Any], *, user_id: int) -> Any:
        call = {"name": name, "arguments": arguments, "user_id": user_id}
        ACTIVE.get()["tools"].append(call)
        result = await self.client.call_tool(name, arguments, user_id=user_id)
        call["result"] = result
        return result


class RecordedTool:
    """Observe local policy/recommendation tools without altering their Java/RAG calls."""

    def __init__(self, name: str, tool: Any) -> None:
        self.name, self.tool = name, tool

    async def ainvoke(self, arguments: dict[str, Any]) -> Any:
        row = ACTIVE.get()
        call = {"name": self.name, "arguments": arguments, "user_id": row["user_id"]}
        row["tools"].append(call)
        result = await self.tool.ainvoke(arguments)
        call["result"] = result
        return result


@asynccontextmanager
async def services(directory: Path) -> AsyncIterator[None]:
    """Own an isolated Java process and real MCP listener; clean up only those resources."""
    java_port = int(os.getenv("EVAL_JAVA_PORT", "18080"))
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", java_port)) == 0:
            raise RuntimeError("Evaluation Java port is occupied; select EVAL_JAVA_PORT")
    os.environ["JAVA_API_URL"] = f"http://127.0.0.1:{java_port}"
    args = [
        os.getenv("EVAL_JAVA_EXE", "D:/java/jdk21/bin/java.exe"),
        "-Duser.timezone=Asia/Shanghai",
        f"-Djdk.net.unixdomain.tmpdir={BACKEND_ROOT / 'target/sockets'}",
        "-jar",
        str(BACKEND_ROOT / "target/cinema-ticketing-backend-0.0.1-SNAPSHOT.jar"),
        "--spring.profiles.active=local",
        f"--server.port={java_port}",
        "--auth.initialize-schema=false",
        "--ai.feedback.initialize-schema=false",
        "--ai.memory.initialize-schema=false",
        "--reviews.initialize-schema=false",
        "--spring.sql.init.mode=never",
        "--spring.rabbitmq.dynamic=false",
        "--spring.rabbitmq.listener.simple.auto-startup=false",
        "--spring.rabbitmq.listener.direct.auto-startup=false",
        "--order.reconcile.initial-delay-ms=2147483647",
        "--order.reconcile.fixed-delay-ms=2147483647",
    ]
    with (directory / "java.log").open("wb") as log:
        process = subprocess.Popen(
            args,
            cwd=BACKEND_ROOT,
            env=os.environ.copy(),
            stdout=log,
            stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        server = None
        thread = None
        listener = None
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=2) as client:
                for _ in range(120):
                    if process.poll() is not None:
                        raise RuntimeError("Evaluation Java process exited; inspect java.log")
                    try:
                        response = await client.get(
                            os.environ["JAVA_API_URL"] + "/internal/movies",
                            headers={"X-Internal-Token": os.getenv("AI_INTERNAL_TOKEN", "local-internal-token")},
                        )
                        if response.status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(0.5)
                else:
                    raise RuntimeError("Evaluation Java readiness timeout")
            from app.mcp_server import create_app

            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            listener.listen(128)
            port = listener.getsockname()[1]
            os.environ["CINEMA_MCP_URL"] = f"http://127.0.0.1:{port}/mcp"
            server = uvicorn.Server(uvicorn.Config(create_app(), log_level="error", lifespan="on"))
            thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
            thread.start()
            while not server.started:
                if not thread.is_alive():
                    raise RuntimeError("Evaluation MCP failed to start")
                await asyncio.sleep(0.05)
            yield
        finally:
            if server:
                server.should_exit = True
            if thread:
                await asyncio.to_thread(thread.join, 5)
            if listener:
                listener.close()
            process.terminate()
            await asyncio.to_thread(process.wait, 10)


def previous_module(ref: str, directory: Path) -> types.ModuleType:
    """Execute the actual pre-ReAct entry point from Git, retaining its original dependencies."""
    path = "cinema-ticketing-backend/cinema-ai/app/main.py"
    source = subprocess.check_output(["git", "show", f"{ref}:{path}"], cwd=REPO_ROOT)
    (directory / "baseline_main.py").write_bytes(source)
    module = types.ModuleType("evaluation_baseline_main")
    module.__file__ = str(AI_ROOT / "app/main.py")
    sys.modules[module.__name__] = module
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


def instrument(assistant: Any) -> None:
    """Attach observers to injected boundaries; keep all application decisions intact."""
    assistant.mcp = RecordedMcp(assistant.mcp)
    assistant.tools = {name: RecordedTool(name, tool) for name, tool in assistant.tools.items()}


async def trial(
    module: types.ModuleType, case: dict[str, Any], variant: str, repetition: int, model: Any
) -> dict[str, Any]:
    """Time application-level SSE from request entry through completion, excluding setup."""
    row = {
        "case_id": case["id"],
        "group": case["group"],
        "variant": variant,
        "repetition": repetition,
        "user_id": case["user_id"],
        "question": case["question"],
        "model_calls": [],
        "proposals": [],
        "tools": [],
        "validation": [],
        "errors": [],
        "answer": "",
        "completed": False,
        "ttft_ms": None,
    }
    token = ACTIVE.set(row)
    assistant = module.assistant
    assistant.model = ObservedModel(model)
    request = module.LiveChatRequest(
        user_id=case["user_id"],
        session_id=f"eval-{variant}-{case['id']}-{repetition}",
        question=case["question"],
        history=case["history"],
    )
    started = time.perf_counter()
    try:
        async with asyncio.timeout(80):
            async for wire in assistant.live(request):
                packet = json.loads(wire.removeprefix("data: ").strip())
                if packet["type"] == "delta" and packet.get("text"):
                    if row["ttft_ms"] is None:
                        row["ttft_ms"] = (time.perf_counter() - started) * 1000
                    row["answer"] += packet["text"]
                elif packet["type"] == "error":
                    row["errors"].append({"code": packet.get("code", "agent_error")})
                elif packet["type"] == "complete":
                    row["completed"] = True
    except Exception as exc:
        row["errors"].append({"code": type(exc).__name__})
    finally:
        row["total_ms"] = (time.perf_counter() - started) * 1000
        ACTIVE.reset(token)
    row["score"] = judge(case, row)
    return row


def summaries(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Expose groups so clarification shortcuts cannot hide composite task failures."""
    return {
        variant: {
            group: summarize(
                [row for row in rows if row["variant"] == variant and (group == "all" or row["group"] == group)]
            )
            for group in ("all", "simple", "composite", "clarify", "safety")
        }
        for variant in ("baseline", "react")
    }


async def run(options: argparse.Namespace) -> None:
    """Freeze cases, alternate paired versions, and checkpoint every paid trial."""
    load_dotenv(AI_ROOT / ".env")
    os.environ["MEMORY_ENABLED"] = "false"
    os.environ["AGENT_MAX_TOOL_CALLS"] = "4"
    directory = Path(options.output).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    from app.model_config import create_model

    model = create_model()
    if model is None:
        raise RuntimeError("Real model key required; deterministic fallback is not a model evaluation")
    async with services(directory):
        if options.manifest:
            manifest = Path(options.manifest).resolve()
            cases = json.loads(manifest.read_text(encoding="utf-8"))
            shutil.copyfile(manifest, directory / "cases.json")
            shutil.copyfile(manifest.parent / "snapshot.json", directory / "snapshot.json")
        else:
            from evaluation.live_cases import prepare_live

            cases = await prepare_live(directory)
        if options.limit:
            cases = cases[: options.limit]
        ref = subprocess.check_output(["git", "rev-parse", options.baseline_ref], cwd=REPO_ROOT, text=True).strip()
        current_ref = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
        metadata = {
            "started_beijing": datetime.now(timezone(timedelta(hours=8))).isoformat(),
            "baseline_ref": ref,
            "current_ref": current_ref,
            "model": model.model_name,
            "temperature": model.temperature,
            "max_tokens": model.max_tokens,
            "thinking": model.extra_body,
            "case_count": len(cases),
            "repeats": options.repeats,
            "concurrency": 1,
            "memory_enabled": False,
            "tool_budget": 4,
            "data_mode": "real_java_mysql_redis",
            "timing_boundary": "Assistant.live application SSE; excludes gateway/auth/browser",
            "price_source": PRICE_SOURCE,
            "price_asof": "2026-10-09",
            "price_currency": "CNY",
            "prices_per_million": {"input": 0.2, "output": 0.8, "cached_input": 0.04},
            "manifest_sha256": hashlib.sha256((directory / "cases.json").read_bytes()).hexdigest(),
            "snapshot_sha256": hashlib.sha256((directory / "snapshot.json").read_bytes()).hexdigest(),
        }
        (directory / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        if options.prepare_only:
            print(json.dumps({"prepared_cases": len(cases), "output": str(directory)}, ensure_ascii=True), flush=True)
            return
        current = importlib.import_module("app.main")
        baseline = previous_module(ref, directory)
        from app import react_agent

        original_validate = react_agent.validate_arguments

        def observe_validation(name: str, arguments: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
            observed = {"name": name, "arguments": arguments, "accepted": False}
            ACTIVE.get()["validation"].append(observed)
            result = original_validate(name, arguments, state)
            observed["accepted"] = True
            return result

        react_agent.validate_arguments = observe_validation
        modules = {"react": current, "baseline": baseline}
        for module in modules.values():
            instrument(module.assistant)
        output = directory / "trials.jsonl"
        rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()] if output.exists() else []
        done = {(row["case_id"], row["variant"], row["repetition"]) for row in rows}
        try:
            with output.open("a", encoding="utf-8") as stream:
                for repetition in range(1, options.repeats + 1):
                    ordered = list(cases)
                    random.Random(20261009 + repetition).shuffle(ordered)
                    for index, case in enumerate(ordered):
                        variants = ("baseline", "react") if (index + repetition) % 2 else ("react", "baseline")
                        for variant in variants:
                            if (case["id"], variant, repetition) in done:
                                continue
                            row = await trial(modules[variant], case, variant, repetition, model)
                            stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                            stream.flush()
                            rows.append(row)
                            print(
                                json.dumps(
                                    {
                                        "done": len(rows),
                                        "planned": len(cases) * options.repeats * 2,
                                        "case": case["id"],
                                        "variant": variant,
                                        "success": row["score"]["task_success"],
                                        "tools_ok": row["score"]["tool_correct"],
                                        "seconds": round(row["total_ms"] / 1000, 2),
                                        "model_calls": len(row["model_calls"]),
                                    },
                                    ensure_ascii=True,
                                ),
                                flush=True,
                            )
                            (directory / "summary.json").write_text(
                                json.dumps(summaries(rows), ensure_ascii=False, indent=2), encoding="utf-8"
                            )
        finally:
            react_agent.validate_arguments = original_validate
            for module in modules.values():
                await module.assistant.client.aclose()
            await model.root_async_client.close()
        print(json.dumps({"finished": len(rows), "output": str(directory)}, ensure_ascii=True), flush=True)


def main() -> None:
    """Parse a reproducible evaluation invocation; runtime secrets are never serialized."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--baseline-ref", default="039085e")
    parser.add_argument("--repeats", type=int, default=2, choices=range(1, 6))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--manifest")
    parser.add_argument("--prepare-only", action="store_true")
    logging.basicConfig(level=logging.ERROR)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
