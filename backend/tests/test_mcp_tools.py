from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel

from ask_jeremy_backend.mcp_tools import McpToolProxy, load_mcp_configs


class Mem0SearchArgs(BaseModel):
    query: str
    user_id: str | None = None


class NoUserIdArgs(BaseModel):
    query: str


class RecordingTool(BaseTool):
    name: str = "mem0_search_memory"
    description: str = "Records forwarded arguments."
    args_schema: type[BaseModel] = Mem0SearchArgs
    forwarded_kwargs: dict[str, Any] | None = None
    forwarded_args: tuple[Any, ...] | None = None

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def _arun(self, *args: Any, **kwargs: Any) -> Any:
        self.forwarded_args = args
        self.forwarded_kwargs = dict(kwargs)
        return {"ok": True}


class RecordingToolWithoutUserId(RecordingTool):
    args_schema: type[BaseModel] = NoUserIdArgs


class RecordingToolWithJsonSchema(RecordingTool):
    args_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "user_id": {"type": "string"},
        },
        "required": ["query"],
        "additionalProperties": False,
    }


class McpConfigTests(unittest.TestCase):
    def test_load_mcp_configs_reads_user_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mcp.json"
            config_path.write_text(
                """
                [
                  {
                    "name": "mem0",
                    "url": "https://mem0.seanji.net/mcp",
                    "bearer_token": "${MEM0_MCP_TOKEN}",
                    "user_id": "seanji",
                    "enabled": true
                  }
                ]
                """,
                encoding="utf-8",
            )

            configs = load_mcp_configs(config_path)

        self.assertEqual(len(configs), 1)
        self.assertEqual(configs[0].user_id, "seanji")

    def test_load_mcp_configs_defaults_missing_user_id_to_empty_string(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mcp.json"
            config_path.write_text(
                """
                [
                  {
                    "name": "other",
                    "url": "https://example.com/mcp",
                    "enabled": true
                  }
                ]
                """,
                encoding="utf-8",
            )

            configs = load_mcp_configs(config_path)

        self.assertEqual(len(configs), 1)
        self.assertEqual(configs[0].user_id, "")

    def test_proxy_overrides_model_supplied_user_id_when_configured(self) -> None:
        tool = RecordingTool()
        proxy = McpToolProxy(inner=tool, server_name="mem0", user_id="seanji")

        result = proxy._run(query="birth date", user_id="default")

        self.assertEqual(result, {"ok": True})
        self.assertIsNotNone(tool.forwarded_kwargs)
        self.assertEqual(tool.forwarded_kwargs["user_id"], "seanji")
        self.assertEqual(tool.forwarded_kwargs["query"], "birth date")

    def test_proxy_does_not_inject_user_id_for_tools_without_that_argument(self) -> None:
        tool = RecordingToolWithoutUserId()
        proxy = McpToolProxy(inner=tool, server_name="mem0", user_id="seanji")

        result = proxy._run(query="anything")

        self.assertEqual(result, {"ok": True})
        self.assertIsNotNone(tool.forwarded_kwargs)
        self.assertNotIn("user_id", tool.forwarded_kwargs)

    def test_proxy_overrides_positional_dict_user_id_when_configured(self) -> None:
        tool = RecordingTool()
        proxy = McpToolProxy(inner=tool, server_name="mem0", user_id="seanji")

        result = proxy._run({"query": "birth date", "user_id": "default"})

        self.assertEqual(result, {"ok": True})
        self.assertIsNotNone(tool.forwarded_args)
        self.assertEqual(tool.forwarded_args[0]["user_id"], "seanji")
        self.assertEqual(tool.forwarded_args[0]["query"], "birth date")

    def test_proxy_uses_empty_user_id_when_config_is_missing(self) -> None:
        tool = RecordingTool()
        proxy = McpToolProxy(inner=tool, server_name="mem0")

        result = proxy._run(query="birth date", user_id="default")

        self.assertEqual(result, {"ok": True})
        self.assertIsNotNone(tool.forwarded_kwargs)
        self.assertEqual(tool.forwarded_kwargs["user_id"], "")

    def test_proxy_detects_user_id_in_json_schema_dict(self) -> None:
        tool = RecordingToolWithJsonSchema()
        proxy = McpToolProxy(inner=tool, server_name="mem0", user_id="seanji")

        result = proxy._run(query="birth date", user_id="default")

        self.assertEqual(result, {"ok": True})
        self.assertIsNotNone(tool.forwarded_kwargs)
        self.assertEqual(tool.forwarded_kwargs["user_id"], "seanji")


if __name__ == "__main__":
    unittest.main()
