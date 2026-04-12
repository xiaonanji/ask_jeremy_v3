"""Remote MCP server integration for Ask Jeremy.

MCP servers are configured in backend/mcp.json:

    [
      {
        "name":         "my-server",
        "url":          "http://192.168.1.100/mcp",
        "bearer_token": "secret",
        "enabled":      true
      }
    ]

Connections are established once at server startup and held for the process
lifetime. Restart the backend to pick up changes to mcp.json.
"""
from __future__ import annotations

import json
import threading
import warnings
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pydantic
from langchain_core.tools import BaseTool


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class McpServerConfig:
    name: str
    url: str
    bearer_token: str = ""
    enabled: bool = True


def load_mcp_configs(config_path: Path) -> list[McpServerConfig]:
    """Parse mcp.json and return enabled server configs."""
    if not config_path.exists():
        return []
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        warnings.warn(f"Could not read MCP config at {config_path}: {exc}", stacklevel=2)
        return []
    if not isinstance(raw, list):
        warnings.warn(f"mcp.json must be a JSON array, ignoring.", stacklevel=2)
        return []
    configs: list[McpServerConfig] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        url = item.get("url")
        if not name or not url:
            warnings.warn(
                f"MCP server entry missing 'name' or 'url', skipping: {item}", stacklevel=2
            )
            continue
        configs.append(McpServerConfig(
            name=str(name),
            url=str(url),
            bearer_token=str(item.get("bearer_token", "")),
            enabled=bool(item.get("enabled", True)),
        ))
    return [c for c in configs if c.enabled]


# ---------------------------------------------------------------------------
# Thread-local event emitter
# ---------------------------------------------------------------------------

_mcp_event_local = threading.local()


def set_mcp_event_emitter(emitter: Any) -> None:
    """Register an event-push callback for the current (worker) thread.

    The streaming worker calls this once before running the LangGraph stream.
    The emitter is a callable that accepts a dict and forwards it to the SSE
    queue via ``loop.call_soon_threadsafe``.
    """
    _mcp_event_local.emitter = emitter


def _emit_mcp_event(server_name: str, tool_name: str) -> None:
    emitter = getattr(_mcp_event_local, "emitter", None)
    if emitter is not None:
        emitter({
            "type": "mcp_tool_call",
            "server_name": server_name,
            "tool_name": tool_name,
        })


# ---------------------------------------------------------------------------
# Tool wrapper
# ---------------------------------------------------------------------------

class McpToolProxy(BaseTool):
    """Wraps an MCP-backed LangChain tool to emit a visibility event before each call."""

    _inner: BaseTool = pydantic.PrivateAttr()
    _server_name: str = pydantic.PrivateAttr()

    def __init__(self, *, inner: BaseTool, server_name: str) -> None:
        init_kwargs: dict[str, Any] = {
            "name": inner.name,
            "description": inner.description or f"Tool provided by MCP server '{server_name}'",
        }
        if inner.args_schema is not None:
            init_kwargs["args_schema"] = inner.args_schema
        super().__init__(**init_kwargs)
        self._inner = inner
        self._server_name = server_name

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        _emit_mcp_event(self._server_name, self.name)
        return self._inner._run(*args, **kwargs)

    async def _arun(self, *args: Any, **kwargs: Any) -> Any:
        _emit_mcp_event(self._server_name, self.name)
        return await self._inner._arun(*args, **kwargs)


# ---------------------------------------------------------------------------
# Connection setup
# ---------------------------------------------------------------------------

async def connect_mcp_servers(
    configs: list[McpServerConfig],
) -> tuple[list[BaseTool], AsyncExitStack]:
    """Connect to each enabled MCP server.

    Returns a flat list of wrapped tools and an AsyncExitStack that must be
    closed when the application shuts down.
    """
    exit_stack = AsyncExitStack()

    if not configs:
        return [], exit_stack

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError:
        warnings.warn(
            "langchain-mcp-adapters is not installed; MCP servers will not be loaded. "
            "Run: pip install langchain-mcp-adapters",
            stacklevel=2,
        )
        return [], exit_stack

    tools: list[BaseTool] = []
    for cfg in configs:
        headers: dict[str, str] = {}
        if cfg.bearer_token:
            headers["Authorization"] = f"Bearer {cfg.bearer_token}"
        try:
            client: MultiServerMCPClient = await exit_stack.enter_async_context(
                MultiServerMCPClient({
                    cfg.name: {
                        "url": cfg.url,
                        "transport": "streamable_http",
                        "headers": headers,
                    }
                })
            )
            for tool in client.get_tools():
                tools.append(McpToolProxy(inner=tool, server_name=cfg.name))
        except Exception as exc:
            warnings.warn(
                f"Failed to connect to MCP server '{cfg.name}' at {cfg.url}: {exc}",
                stacklevel=2,
            )

    return tools, exit_stack
