#!/usr/bin/env python3
"""prompt-diff-checker: show what a prompt change does to structured JSON outputs.

Given two prompt versions and a directory of input JSON files, run both
prompts over every input, infer the JSON schema of each output, and write a
Markdown field-drift report (added / removed / renamed / changed-type fields).

The default model is an offline, deterministic mock: it reads the list of
output fields from the prompt text itself (backticked names under
"Output fields") and fills each one from the input with a fixed rule, so the
demo runs with no API key and no network. A real endpoint can be plugged in
with ``--model env`` (see :func:`env_generate`).

Stdlib only. Python 3.10+.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

__version__ = "0.1.0"

FIELD_RE = re.compile(r"`([a-z][a-z0-9_]*)`")


class ModelError(Exception):
    """Raised when the configured model cannot produce an output."""


class UsageError(Exception):
    """Raised for bad CLI input (missing files, empty input dir, ...)."""


# ---------------------------------------------------------------------------
# Prompt parsing + mock model
# ---------------------------------------------------------------------------

def parse_fields(prompt_text: str) -> list[str]:
    """Return the output field names a prompt asks for, in order.

    Fields are the backticked identifiers in the prompt (the "Output fields"
    list). Duplicates are dropped, order is preserved.
    """
    seen: list[str] = []
    for name in FIELD_RE.findall(prompt_text):
        if name not in seen:
            seen.append(name)
    return seen


def _classify_category(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ("charged", "billing", "payment", "refund", "invoice", "subscription")):
        return "billing"
    if any(w in t for w in ("login", "password", "account", "sign in", "locked out")):
        return "account"
    if any(w in t for w in ("crash", "error", "bug", "not working", "broken", "fails")):
        return "technical"
    if any(w in t for w in ("delivery", "shipping", "package", "tracking", "arrived")):
        return "shipping"
    return "general"


def _classify_priority(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ("urgent", "asap", "critical", "immediately", "down")):
        return "high"
    if any(w in t for w in ("soon", "important", "please hurry")):
        return "medium"
    return "low"


def _classify_sentiment(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ("frustrat", "angry", "terrible", "unacceptable", "furious", "awful")):
        return "negative"
    if any(w in t for w in ("great", "thank", "love", "excellent", "wonderful")):
        return "positive"
    return "neutral"


def _classify_action(text: str) -> str:
    t = text.lower()
    if "refund" in t:
        return "refund"
    if "cancel" in t:
        return "cancel_subscription"
    if "replace" in t:
        return "replace_item"
    if any(w in t for w in ("fix", "repair", "resolve")):
        return "fix_issue"
    return "investigate"


def _summary(text: str) -> str:
    first = text.strip().split(".")[0].strip()
    return first[:140]


def _extract_field(name: str, data: dict) -> object:
    """Fill one output field from an input record. Unknown fields -> ""."""
    customer = data.get("customer") or {}
    if not isinstance(customer, dict):
        customer = {"name": str(customer)}
    subject = str(data.get("subject", ""))
    body = str(data.get("body", ""))
    text = f"{subject} {body}"

    if name == "ticket_id":
        return str(data.get("id", data.get("ticket_id", "")))
    if name == "customer_name":
        return str(customer.get("name", ""))
    if name == "customer":
        return {"name": str(customer.get("name", "")),
                "tier": str(customer.get("tier", "standard"))}
    if name == "issue_category":
        return _classify_category(text)
    if name == "priority":
        return _classify_priority(text)
    if name == "sentiment":
        return _classify_sentiment(text)
    if name in ("summary", "issue_summary"):
        return _summary(body or subject)
    if name == "requested_action":
        return _classify_action(text)
    return ""


def mock_generate(prompt_text: str, data: dict) -> dict:
    """Deterministic offline model: output fields come from the prompt."""
    fields = parse_fields(prompt_text)
    return {name: _extract_field(name, data) for name in fields}


# ---------------------------------------------------------------------------
# Pluggable model (env endpoint)
# ---------------------------------------------------------------------------

def env_generate(prompt_text: str, data: dict) -> dict:
    """Call a real endpoint configured through environment variables.

    Requires ``PROMPT_DIFF_CHECKER_ENDPOINT`` (HTTP(S) URL accepting a JSON
    POST of ``{"prompt": ..., "input": ...}`` and returning either a JSON
    object directly or ``{"output": {...}}``). ``PROMPT_DIFF_CHECKER_API_KEY``
    is sent as a Bearer token when set. Any failure raises ModelError with a
    plain message -- never a traceback.
    """
    endpoint = os.environ.get("PROMPT_DIFF_CHECKER_ENDPOINT", "").strip()
    if not endpoint:
        raise ModelError(
            "No model endpoint configured: set the PROMPT_DIFF_CHECKER_ENDPOINT "
            "environment variable to an HTTP(S) endpoint URL "
            "(optionally PROMPT_DIFF_CHECKER_API_KEY for auth), "
            "or run with --model mock (the default, offline)."
        )
    payload = json.dumps({"prompt": prompt_text, "input": data}).encode()
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("PROMPT_DIFF_CHECKER_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode())
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        raise ModelError(f"env model request to {endpoint} failed: {exc}") from None
    if isinstance(result, dict) and isinstance(result.get("output"), dict):
        return result["output"]
    if isinstance(result, dict):
        return result
    raise ModelError(f"env model at {endpoint} returned a non-object JSON response")


def generate(prompt_text: str, data: dict, model: str) -> dict:
    if model == "mock":
        return mock_generate(prompt_text, data)
    if model == "env":
        return env_generate(prompt_text, data)
    raise ModelError(f"Unknown model {model!r} (expected 'mock' or 'env')")


# ---------------------------------------------------------------------------
# Schema inference + drift comparison
# ---------------------------------------------------------------------------

def infer_schema(value: object) -> object:
    """Infer a JSON-schema-like shape: scalars become type names, objects recurse."""
    if isinstance(value, dict):
        return {key: infer_schema(val) for key, val in value.items()}
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if value is None:
        return "null"
    return "string"


def _schema_label(schema: object) -> str:
    if isinstance(schema, dict):
        return "object"
    return str(schema)


def compare_schemas(schema_a: object, schema_b: object,
                    value_a: object = None, value_b: object = None,
                    path: str = "") -> list[dict]:
    """Diff two inferred schemas.

    Returns change dicts with keys ``path``, ``kind`` (added / removed /
    renamed / changed-type), ``a`` and ``b``. A removed field and an added
    field at the same level with the same type *and* the same value in the
    actual outputs are reported as one ``renamed`` change, not as an
    add + a remove.
    """
    changes: list[dict] = []
    if isinstance(schema_a, dict) and isinstance(schema_b, dict):
        a = value_a if isinstance(value_a, dict) else {}
        b = value_b if isinstance(value_b, dict) else {}
        removed = [k for k in schema_a if k not in schema_b]
        added = [k for k in schema_b if k not in schema_a]

        # Rename detection: same type, same observed value.
        renamed_pairs: list[tuple[str, str]] = []
        for old in list(removed):
            for new in list(added):
                if (_schema_label(schema_a[old]) == _schema_label(schema_b[new])
                        and a.get(old) == b.get(new)
                        and a.get(old) is not None):
                    renamed_pairs.append((old, new))
                    removed.remove(old)
                    added.remove(new)
                    break
        for old, new in renamed_pairs:
            p = f"{path}.{new}" if path else new
            changes.append({"path": p, "kind": "renamed",
                            "a": old, "b": new,
                            "detail": f"renamed from `{old}` to `{new}`"})

        for key in removed:
            p = f"{path}.{key}" if path else key
            changes.append({"path": p, "kind": "removed",
                            "a": _schema_label(schema_a[key]), "b": "-",
                            "detail": f"present in A ({_schema_label(schema_a[key])}), absent in B"})
        for key in added:
            p = f"{path}.{key}" if path else key
            changes.append({"path": p, "kind": "added",
                            "a": "-", "b": _schema_label(schema_b[key]),
                            "detail": f"absent in A, present in B ({_schema_label(schema_b[key])})"})
        for key in schema_a:
            if key in schema_b:
                p = f"{path}.{key}" if path else key
                changes.extend(compare_schemas(schema_a[key], schema_b[key],
                                               a.get(key), b.get(key), p))
        return changes

    if schema_a != schema_b:
        return [{"path": path or "(root)", "kind": "changed-type",
                 "a": _schema_label(schema_a), "b": _schema_label(schema_b),
                 "detail": f"type changed from {_schema_label(schema_a)} "
                           f"to {_schema_label(schema_b)}"}]
    return []


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def build_report(prompt_a_name: str, prompt_b_name: str, model: str,
                 per_input: list[dict]) -> str:
    """Render the Markdown field-drift report for all inputs."""
    total = sum(len(item["changes"]) for item in per_input)
    counts = {"added": 0, "removed": 0, "renamed": 0, "changed-type": 0}
    for item in per_input:
        for change in item["changes"]:
            counts[change["kind"]] += 1

    lines = [
        "# Prompt Diff Report",
        "",
        f"- Prompt A: `{prompt_a_name}`",
        f"- Prompt B: `{prompt_b_name}`",
        f"- Model: `{model}`",
        f"- Inputs checked: {len(per_input)}",
        f"- Total drift changes: {total}",
        "",
        "## Summary",
        "",
        "| Change | Count |",
        "| --- | ---: |",
        f"| Added fields | {counts['added']} |",
        f"| Removed fields | {counts['removed']} |",
        f"| Renamed fields | {counts['renamed']} |",
        f"| Changed types | {counts['changed-type']} |",
        "",
    ]
    if total == 0:
        lines += ["No schema drift detected. Both prompts produce the same "
                  "output schema on every input.", ""]
    lines += ["## Per-input drift", ""]
    for item in per_input:
        lines.append(f"### {item['name']}")
        lines.append("")
        if not item["changes"]:
            lines.append("No drift.")
            lines.append("")
            continue
        lines.append("| Field | Change | A | B |")
        lines.append("| --- | --- | --- | --- |")
        for change in sorted(item["changes"], key=lambda c: c["path"]):
            lines.append(f"| `{change['path']}` | {change['kind']} | "
                         f"{change['a']} | {change['b']} |")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def run(prompt_a: Path, prompt_b: Path, inputs_dir: Path,
        out_path: Path, model: str) -> int:
    if not prompt_a.is_file():
        raise UsageError(f"Prompt A not found: {prompt_a}")
    if not prompt_b.is_file():
        raise UsageError(f"Prompt B not found: {prompt_b}")
    if not inputs_dir.is_dir():
        raise UsageError(f"Inputs directory not found: {inputs_dir}")
    input_files = sorted(inputs_dir.glob("*.json"))
    if not input_files:
        raise UsageError(f"No *.json input files in {inputs_dir}")

    prompt_a_text = prompt_a.read_text(encoding="utf-8")
    prompt_b_text = prompt_b.read_text(encoding="utf-8")

    per_input: list[dict] = []
    for input_file in input_files:
        try:
            data = json.loads(input_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise UsageError(f"Cannot read input {input_file}: {exc}") from None
        out_a = generate(prompt_a_text, data, model)
        out_b = generate(prompt_b_text, data, model)
        changes = compare_schemas(infer_schema(out_a), infer_schema(out_b),
                                  out_a, out_b)
        per_input.append({"name": input_file.name, "changes": changes})

    report = build_report(prompt_a.name, prompt_b.name, model, per_input)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"Wrote {out_path} ({len(per_input)} inputs, "
          f"{sum(len(i['changes']) for i in per_input)} drift changes)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Diff the JSON schemas produced by two prompt versions "
                    "across a set of test inputs.")
    parser.add_argument("--prompt-a", required=True, help="Prompt A file")
    parser.add_argument("--prompt-b", required=True, help="Prompt B file")
    parser.add_argument("--inputs", required=True, help="Directory of input JSON files")
    parser.add_argument("--out", required=True, help="Output Markdown report path")
    parser.add_argument("--model", default="mock", choices=["mock", "env"],
                        help="Model backend: mock (default, offline) or env "
                             "(endpoint from PROMPT_DIFF_CHECKER_ENDPOINT)")
    args = parser.parse_args(argv)
    try:
        return run(Path(args.prompt_a), Path(args.prompt_b), Path(args.inputs),
                   Path(args.out), args.model)
    except (UsageError, ModelError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
