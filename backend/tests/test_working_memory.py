from __future__ import annotations

import json
import unittest

from ask_jeremy_backend.working_memory import (
    apply_memory_update,
    make_memory_update,
    normalize_working_memory,
    render_working_memory,
    tool_payload_memory_updates,
)


class WorkingMemoryTests(unittest.TestCase):
    def test_llm_pin_update_is_deduped_and_rendered(self) -> None:
        memory = normalize_working_memory({})
        update = make_memory_update(
            section="business_rules",
            content=json.dumps({"rule": "GBIX B means 91+ DPD or write-off"}),
            source="wiki/sources/clv-b-score-gbix-definition.md",
            confidence="high",
        )

        memory, changed = apply_memory_update(memory, update)
        self.assertTrue(changed)
        memory, changed = apply_memory_update(memory, update)
        self.assertFalse(changed)

        self.assertEqual(len(memory["business_rules"]), 1)
        self.assertEqual(
            memory["business_rules"][0]["content"]["rule"],
            "GBIX B means 91+ DPD or write-off",
        )
        rendered = render_working_memory(memory)
        self.assertIn("GBIX B means 91+ DPD or write-off", rendered)

    def test_current_plan_can_replace_previous_plan(self) -> None:
        memory = normalize_working_memory({})
        first_update = make_memory_update(
            section="current_plan",
            content="Search wiki",
            mode="append",
        )
        replacement = make_memory_update(
            section="current_plan",
            content="Build SQL from referenced warehouse tables only",
            mode="replace",
        )

        memory, _ = apply_memory_update(memory, first_update)
        memory, changed = apply_memory_update(memory, replacement)

        self.assertTrue(changed)
        self.assertEqual(len(memory["current_plan"]), 1)
        self.assertEqual(
            memory["current_plan"][0]["content"],
            "Build SQL from referenced warehouse tables only",
        )

    def test_tool_payload_auto_captures_policy_errors(self) -> None:
        updates = tool_payload_memory_updates(
            tool_name="execute_sql_query",
            payload={
                "ok": False,
                "error_type": "warehouse_table_policy_error",
                "recoverable": False,
                "message": "Blocked due to non-reference warehouse table(s): X",
            },
        )

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["section"], "failed_attempts")
        self.assertEqual(
            updates[0]["item"]["content"]["error_type"],
            "warehouse_table_policy_error",
        )

    def test_tool_payload_auto_captures_loaded_skill_references(self) -> None:
        updates = tool_payload_memory_updates(
            tool_name="load_skill_reference",
            payload={
                "ok": True,
                "message": "Loaded 100 chars from dim_account.md",
                "file_path": "C:/repo/.agents/skills/snowflake-datawarehouse/references/dim_account.md",
                "content": "# dim_account",
                "truncated": False,
            },
        )

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["section"], "loaded_sources")
        self.assertEqual(
            updates[0]["item"]["content"]["source_type"],
            "skill_reference",
        )


if __name__ == "__main__":
    unittest.main()
