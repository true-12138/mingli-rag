# -*- coding: utf-8 -*-
"""MCP HTTP 传输的静态 Bearer token 鉴权。

mcp 2.x 在 ``MCPServer(auth=..., token_verifier=...)`` 上提供了原生接入点：
HTTP app（``sse_app`` / ``streamable_http_app``）会给 MCP 路由套上
``RequireAuthMiddleware``，令牌无效时在协议层之前返回 401。这里实现一个
「单个共享密钥」的 ``TokenVerifier``，不引入 OAuth 授权服务器。

stdio 不经过这一层：本地管道由宿主进程直接拉起，不需要 HTTP 鉴权。
"""
from __future__ import annotations

import hmac
import os
from typing import Any, Mapping

from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings

TOKEN_ENV = "MINGLI_MCP_TOKEN"


def token_from_env(environ: Mapping[str, str] | None = None) -> str:
    """读取共享 token；未设置或只有空白时返回空串。"""
    env = os.environ if environ is None else environ
    return (env.get(TOKEN_ENV) or "").strip()


def token_matches(presented: str | None, expected: str | None) -> bool:
    """常量时间比较两个 token；任一方为空都视为不匹配。"""
    if not isinstance(presented, str) or not isinstance(expected, str):
        return False
    if not presented or not expected:
        return False
    return hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))


class StaticTokenVerifier:
    """把请求里的 Bearer token 与一个共享密钥做常量时间比较。"""

    def __init__(self, token: str) -> None:
        token = (token or "").strip()
        if not token:
            raise ValueError("启用 MCP HTTP 鉴权时 MINGLI_MCP_TOKEN 不能为空")
        self._token = token

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token_matches(token, self._token):
            return None
        return AccessToken(token=token, client_id="mingli-mcp", scopes=[])


def build_http_auth(token: str, base_url: str) -> dict[str, Any]:
    """构造传给 ``MCPServer`` 的鉴权参数；没有 token 时返回空 dict。

    ``AuthSettings`` 是 mcp 的原生配置，虽然字段名来自 OAuth，但只启用
    ``token_verifier`` 时不会创建授权端点，仅用于给 MCP 路由加 Bearer 校验。
    ``validate_token_resource=False``：我们校验的是共享密钥本身，不是 JWT 的 aud。
    """
    if not token:
        return {}
    return {
        "auth": AuthSettings(
            issuer_url=base_url,
            resource_server_url=base_url,
            required_scopes=[],
            validate_token_resource=False,
        ),
        "token_verifier": StaticTokenVerifier(token),
    }
