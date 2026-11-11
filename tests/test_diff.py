"""Tests for prompt-diff-checker (stdlib unittest only)."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diff_checker import (  # noqa: E402
    build_report,
    compare_schemas,
    infer_schema,
    mock_generate,
)

ROOT = Path(__file__).resolve().parent.parent
PROMPT_A = (ROOT / "prompts" / "a.txt").read_text(encoding="utf-8")
PROMPT_B = (ROOT / "prompts" / "b.txt").read_text(encoding="utf-8")
INPUT_001 = json.loads((ROOT / "inputs" / "ticket-001.json").read_text(encoding="utf-8"))


class TestDriftDetection(unittest.TestCase):
    def test_removed_and_renamed_fields_detected(self):
        out_a = mock_generate(PROMPT_A, INPUT_001)
        out_b = mock_generate(PROMPT_B, INPUT_001)
        changes = compare_schemas(infer_schema(out_a), infer_schema(out_b), out_a, out_b)
        by_kind = {c["kind"]: c for c in changes}
        # Prompt B drops requested_action entirely.
        self.assertIn("removed", by_kind)
        self.assertEqual(by_kind["removed"]["path"], "requested_action")
        # Prompt B renames summary -> issue_summary (same value).
        self.assertIn("renamed", by_kind)
        self.assertEqual(by_kind["renamed"]["a"], "summary")
        self.assertEqual(by_kind["renamed"]["b"], "issue_summary")
        self.assertEqual(by_kind["renamed"]["path"], "issue_summary")

    def test_identical_prompts_produce_empty_drift(self):
        out_a = mock_generate(PROMPT_A, INPUT_001)
        out_b = mock_generate(PROMPT_A, INPUT_001)
        changes = compare_schemas(infer_schema(out_a), infer_schema(out_b), out_a, out_b)
        self.assertEqual(changes, [])
        report = build_report("a.txt", "a.txt", "mock",
                              [{"name": "ticket-001.json", "changes": changes}])
        self.assertIn("No schema drift detected", report)
        self.assertIn("Total drift changes: 0", report)

    def test_schema_comparison_handles_nested_objects(self):
        # Nested field removed.
        schema_a = {"customer": {"name": "string", "tier": "string"}, "id": "string"}
        schema_b = {"customer": {"name": "string"}, "id": "string"}
        changes = compare_schemas(schema_a, schema_b,
                                  {"customer": {"name": "x", "tier": "premium"}, "id": "1"},
                                  {"customer": {"name": "x"}, "id": "1"})
        self.assertEqual(
            [(c["path"], c["kind"]) for c in changes], [("customer.tier", "removed")])
        # Nested field type changed.
        schema_c = {"customer": {"name": "string", "tier": "integer"}, "id": "string"}
        changes = compare_schemas(schema_a, schema_c,
                                  {"customer": {"name": "x", "tier": "premium"}, "id": "1"},
                                  {"customer": {"name": "x", "tier": 1}, "id": "1"})
        self.assertEqual(
            [(c["path"], c["kind"]) for c in changes],
            [("customer.tier", "changed-type")])
        # Nested object replaced by a scalar is a changed type, not a crash.
        changes = compare_schemas(schema_a, {"customer": "string", "id": "string"},
                                  {"customer": {"name": "x"}}, {"customer": "x"})
        self.assertEqual(
            [(c["path"], c["kind"]) for c in changes],
            [("customer", "changed-type")])

    def test_changed_type_detected(self):
        changes = compare_schemas({"priority": "string"}, {"priority": "integer"},
                                  {"priority": "high"}, {"priority": 1})
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["kind"], "changed-type")
        self.assertEqual(changes[0]["path"], "priority")


class TestCli(unittest.TestCase):
    def test_env_model_without_endpoint_fails_cleanly(self):
        env = dict(os.environ)
        env.pop("PROMPT_DIFF_CHECKER_ENDPOINT", None)
        env.pop("PROMPT_DIFF_CHECKER_API_KEY", None)
        result = subprocess.run(
            [sys.executable, str(ROOT / "diff_checker.py"),
             "--prompt-a", str(ROOT / "prompts" / "a.txt"),
             "--prompt-b", str(ROOT / "prompts" / "b.txt"),
             "--inputs", str(ROOT / "inputs"),
             "--out", str(ROOT / "report.md"),
             "--model", "env"],
            capture_output=True, text=True, env=env, cwd=str(ROOT))
        self.assertEqual(result.returncode, 2)
        self.assertIn("PROMPT_DIFF_CHECKER_ENDPOINT", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
