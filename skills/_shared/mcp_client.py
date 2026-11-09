#!/usr/bin/env python3
"""通用 MCP over Streamable-HTTP 客户端（纯标准库），供各 fetch 脚本共用。

为什么单独一份：领星与卖家精灵都是 MCP，但业务工具名不同——
领星走 `action(toolId, params)`，卖家精灵直接 `tools/call(name, arguments)`。
本模块把"连上去、发 JSON-RPC、解 content[].text"这段公共逻辑收一次。

凭证两条路，任选一条（后者专治 Trae / WorkBuddy 这类 GUI 客户端拿不到 shell 变量）：
  1) 环境变量（Shell / cron / CI 最稳）：
     领星：LINGXING_MCP_URL / LINGXING_MCP_KEY（请求头 X-Mcp-Key）
     卖家精灵：SELLERSPRITE_MCP_URL / SELLERSPRITE_MCP_KEY（请求头 secret-key）
  2) 本机私密文件 config/mcp.local.json（不进 Git、不进分发包）：
     {"lingxing": {"url": "...", "key": "..."},
      "sellersprite": {"url": "...", "key": "..."}}
  优先级：环境变量 > 本机文件。任何客户端只要能跑 python3 就通用。
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

# 本模块在 skills/_shared/，仓库根是上两级
ROOT = Path(__file__).resolve().parent.parent.parent
LOCAL_SECRETS = ROOT / "config" / "mcp.local.json"
_secrets_cache = None


def _local_secrets() -> dict:
    """读 config/mcp.local.json；不存在/坏 JSON 都当空，不抛（凭证缺失由调用方报）。"""
    global _secrets_cache
    if _secrets_cache is not None:
        return _secrets_cache
    _secrets_cache = {}
    try:
        _secrets_cache = json.loads(LOCAL_SECRETS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return _secrets_cache


def credential(service: str, env_url: str, env_key: str,
               default_url: str = "") -> tuple:
    """取 (url, key)。环境变量优先，其次 config/mcp.local.json。

    service 用文件里的段名（lingxing / sellersprite）；env_url/env_key 是对应变量名。
    url 都没有时用 default_url（卖家精灵有公开端点，领星没有）。
    """
    url = os.environ.get(env_url) or ""
    key = os.environ.get(env_key) or ""
    if not (url and key):
        block = _local_secrets().get(service) or {}
        url = url or block.get("url") or ""
        key = key or block.get("key") or ""
    return (url or default_url), key


def where_credentials_come_from() -> str:
    """给 doctor/排错用：说清现在走的是哪条路。"""
    src = []
    if os.environ.get("LINGXING_MCP_KEY"):
        src.append("领星=环境变量")
    elif (_local_secrets().get("lingxing") or {}).get("key"):
        src.append("领星=config/mcp.local.json")
    if os.environ.get("SELLERSPRITE_MCP_KEY"):
        src.append("卖家精灵=环境变量")
    elif (_local_secrets().get("sellersprite") or {}).get("key"):
        src.append("卖家精灵=config/mcp.local.json")
    return "，".join(src) or "未找到任何凭证"


class MCPError(RuntimeError):
    pass


class MCPClient:
    """最小可用的 MCP Streamable-HTTP 客户端（initialize + tools/call）。"""

    def __init__(self, url: str, headers: dict, timeout: int = 60):
        self.url = url.rstrip("/")
        self.headers = dict(headers)
        self.timeout = timeout
        self._id = 0
        self._session = None

    # ---- 低层 ----
    def _post(self, payload):
        # MCP Streamable HTTP 规范要求 Accept 同时声明 json 与 event-stream，
        # 卖家精灵服务端严格校验（只给 application/json 会 400），领星两者都接受。
        hdrs = {"Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                **self.headers}
        if self._session:
            hdrs["mcp-session-id"] = self._session
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode("utf-8"),
                                     headers=hdrs, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            sid = resp.headers.get("mcp-session-id")
            if sid:
                self._session = sid
            body = resp.read().decode("utf-8")
        obj = self._parse_body(body)
        if obj is None:
            raise MCPError("MCP 响应里没有 JSON-RPC result：%s…" % body[:300])
        return obj

    @staticmethod
    def _parse_body(body: str):
        """兼容三种响应形态：纯 JSON、ndjson、SSE（`data: {json}`）。

        卖家精灵走 SSE 且要求 Mcp-Session-Id（initialize 时下发，后续必带）；
        领星多返纯 JSON。从后往前取第一条带 result/error 的。
        """
        candidates = []
        for line in body.splitlines():
            s = line.strip()
            if not s:
                continue
            if s.startswith("data:"):
                candidates.append(s[5:].strip())
            elif s.startswith("{") or s.startswith("["):
                candidates.append(s)
        for raw in reversed(candidates):
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and ("result" in obj or "error" in obj):
                return obj
        return None

    def _call(self, method, params=None):
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            payload["params"] = params
        obj = self._post(payload)
        if "error" in obj:
            raise MCPError("%s 出错：%s" % (method, obj["error"]))
        return obj["result"]

    # ---- 高层 ----
    def initialize(self, client_name="amz-ops-fetch"):
        self._call("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                  "clientInfo": {"name": client_name, "version": "1.0"}})
        try:
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except Exception:
            pass  # 通知失败不致命

    def call_tool(self, name, arguments):
        """调一个 MCP 工具，返回其 content 里的结构化结果。

        注意：卖家精灵会把「业务数据」和「计费信息」两个 JSON 拼在一段文本里
        （`{"items":[...]}{"billing":{...}}`），直接 json.loads 会失败。
        这里用 raw_decode 取第一个完整对象（业务数据），计费信息丢弃。
        """
        res = self._call("tools/call", {"name": name, "arguments": arguments})
        text = "".join(p.get("text", "") for p in res.get("content", []) if isinstance(p, dict))
        if res.get("isError"):
            raise MCPError("工具 %s 返回错误：%s" % (name, text[:300]))
        s = text.strip()
        if not s:
            return {}
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass
        try:  # 多 JSON 拼接：只取第一个
            obj, _ = json.JSONDecoder().raw_decode(s)
            return obj
        except json.JSONDecodeError:
            return {"_raw": text}


# ---- 两个业务后端的便捷构造函数 ----

def lingxing_client() -> MCPClient:
    url, key = credential("lingxing", "LINGXING_MCP_URL", "LINGXING_MCP_KEY")
    if not url or not key:
        raise SystemExit(
            "缺领星凭证：任选一种——(1) export LINGXING_MCP_URL 与 LINGXING_MCP_KEY；"
            "(2) 填 config/mcp.local.json 的 lingxing 段（见 docs/CLIENTS.md）")
    c = MCPClient(url, {"X-Mcp-Key": key})
    c.initialize("amz-lingxing")
    return c


def sellersprite_client() -> MCPClient:
    # 端点带 v2 路径（2026-11-04 实测：/mcp 会 400，必须 /v2/mcp）
    url, key = credential("sellersprite", "SELLERSPRITE_MCP_URL", "SELLERSPRITE_MCP_KEY",
                          default_url="https://mcp.sellersprite.com/v2/mcp")
    if not key:
        raise SystemExit(
            "缺卖家精灵凭证：任选一种——(1) export SELLERSPRITE_MCP_KEY；"
            "(2) 填 config/mcp.local.json 的 sellersprite 段（见 docs/CLIENTS.md）")
    c = MCPClient(url, {"secret-key": key})
    c.initialize("amz-sellersprite")
    return c


def lingxing_action(client: MCPClient, tool_id: str, params: dict) -> dict:
    """领星专用：业务工具走 action(toolId, params)。返回 data 段。"""
    res = client.call_tool("action", {"toolId": tool_id, "params": params})
    if isinstance(res, dict) and res.get("success") is False:
        raise MCPError("领星 %s success=false：%s" % (tool_id, str(res.get("msg"))[:200]))
    return (res.get("data") or {}) if isinstance(res, dict) else {}
