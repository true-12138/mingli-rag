# -*- coding: utf-8 -*-
"""MCP HTTP 传输的 Bearer token 鉴权测试。

不启动真实网络服务：用 starlette 的 TestClient 直接驱动 mcp 2.x 生成的
ASGI app，验证「无 token / 错 token → 401，正确 token → 进入 MCP 协议层」。
stdio 不经过 HTTP 鉴权，所以这里只覆盖 sse / streamable-http。

没装 mcp 的环境会整文件 skip；``mcp_auth`` 也依赖 mcp 的 AccessToken 类型。
"""
import asyncio
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import mcp_auth  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

TOKEN = "mingli-test-token"
BASE_URL = "http://127.0.0.1:8765"
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "mcp-auth-test", "version": "0"},
    },
}


def _client(transport: str) -> TestClient:
    auth = mcp_auth.build_http_auth(TOKEN, BASE_URL)
    server = MCPServer(name="mcp-auth-test", version="0", **auth)
    security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    if transport == "streamable-http":
        app = server.streamable_http_app(host="127.0.0.1", transport_security=security)
    else:
        app = server.sse_app(host="127.0.0.1", transport_security=security)
    return TestClient(app)


@pytest.fixture(scope="module")
def streamable_client():
    with _client("streamable-http") as client:
        yield client


@pytest.fixture(scope="module")
def sse_client():
    with _client("sse") as client:
        yield client


def test_token_from_env():
    assert mcp_auth.token_from_env({}) == ""
    assert mcp_auth.token_from_env({mcp_auth.TOKEN_ENV: "  abc  "}) == "abc"


def test_token_matches_is_exact():
    assert mcp_auth.token_matches(TOKEN, TOKEN)
    assert not mcp_auth.token_matches(TOKEN + "x", TOKEN)
    assert not mcp_auth.token_matches("wrong", TOKEN)
    assert not mcp_auth.token_matches("", TOKEN)
    assert not mcp_auth.token_matches(TOKEN, "")
    # 非 ASCII token 也不能让 compare_digest 抛 TypeError
    assert mcp_auth.token_matches("令牌", "令牌")
    assert not mcp_auth.token_matches("令牌", "密钥")


def test_static_verifier_only_accepts_exact_token():
    verifier = mcp_auth.StaticTokenVerifier(TOKEN)
    assert asyncio.run(verifier.verify_token(TOKEN)) is not None
    assert asyncio.run(verifier.verify_token("wrong")) is None
    assert asyncio.run(verifier.verify_token("")) is None


def test_build_http_auth_disabled_without_token():
    assert mcp_auth.build_http_auth("", BASE_URL) == {}
    auth = mcp_auth.build_http_auth(TOKEN, BASE_URL)
    assert set(auth) == {"auth", "token_verifier"}


def test_streamable_http_without_header_is_401(streamable_client):
    response = streamable_client.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)
    assert response.status_code == 401
    assert "www-authenticate" in response.headers


def test_streamable_http_wrong_token_is_401(streamable_client):
    headers = {**MCP_HEADERS, "Authorization": "Bearer wrong-token"}
    response = streamable_client.post("/mcp", json=INITIALIZE, headers=headers)
    assert response.status_code == 401


def test_streamable_http_correct_token_reaches_protocol(streamable_client):
    headers = {**MCP_HEADERS, "Authorization": "Bearer %s" % TOKEN}
    response = streamable_client.post("/mcp", json=INITIALIZE, headers=headers)
    assert response.status_code == 200
    assert '"result"' in response.text


def test_sse_without_header_is_401(sse_client):
    response = sse_client.get("/sse", headers={"Accept": "text/event-stream"})
    assert response.status_code == 401


def test_sse_wrong_token_is_401(sse_client):
    headers = {"Accept": "text/event-stream", "Authorization": "Bearer wrong-token"}
    response = sse_client.get("/sse", headers=headers)
    assert response.status_code == 401
