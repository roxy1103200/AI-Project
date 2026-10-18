"""Loopback-only fault injection for the isolated evaluation stack, never production."""

import hmac
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

FAULT = {"mode": "", "path": ""}


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(trust_env=False, timeout=95) as client:
        app.state.client = client
        yield


app = FastAPI(lifespan=lifespan)


@app.post("/__fixture/fault")
async def fault(request: Request, x_fixture_token: str = Header(default="")) -> dict:
    if not hmac.compare_digest(x_fixture_token, os.environ["WEBSITE_FIXTURE_TOKEN"]):
        raise HTTPException(401)
    body = await request.json()
    if body.get("mode") not in {"", "java_unavailable", "truncate"}:
        raise HTTPException(400)
    if body.get("path", "") and not (body["path"].startswith("/internal/orders/OWEBREG") or body["path"] == "/internal/recommendations"):
        raise HTTPException(400)
    FAULT.update(mode=body.get("mode", ""), path=body.get("path", ""))
    return {"armed": FAULT["mode"]}


@app.api_route("/{path:path}", methods=["GET", "POST", "DELETE", "PUT", "PATCH", "OPTIONS"])
async def proxy(path: str, request: Request) -> Response:
    agent = path.startswith("agent/")
    target = "http://127.0.0.1:18000/" + path[6:] if agent else "http://127.0.0.1:18080/" + path
    if not agent and FAULT["mode"] == "java_unavailable" and "/" + path == FAULT["path"]:
        FAULT.update(mode="", path="")
        return JSONResponse({"message": "Isolated regression service fault"}, status_code=503)
    truncate = agent and FAULT["mode"] == "truncate"
    if truncate:
        FAULT.update(mode="", path="")
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in {"host", "content-length", "connection"}
    }
    upstream = await app.state.client.send(
        app.state.client.build_request(
            request.method, target, params=request.query_params, headers=headers, content=await request.body()
        ),
        stream=True,
    )

    async def content():
        try:
            async for chunk in upstream.aiter_raw():
                if truncate:
                    # A real Agent response has begun; terminate before its completion frame.
                    yield b'data: {"type":"status","message":"isolated transport interruption"}\n\n'
                    return
                yield chunk
        finally:
            await upstream.aclose()

    response_headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() not in {"content-length", "transfer-encoding", "connection", "content-encoding"}
    }
    return StreamingResponse(content(), status_code=upstream.status_code, headers=response_headers)
