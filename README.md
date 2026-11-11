# prompt-diff-checker

Change a prompt, silently change your JSON output — this tool shows you exactly which fields moved.

## The problem

When you edit a prompt that produces structured JSON, fields get added, dropped, renamed, or change type — and downstream code breaks before anyone notices. `prompt-diff-checker` runs two prompt versions over the same test inputs and reports the schema drift between them.

## Quick start

Requires Python 3.10+ and nothing else (stdlib only, no network in the default path).

```bash
python diff_checker.py --prompt-a prompts/a.txt --prompt-b prompts/b.txt \
  --inputs inputs/ --out report.md
```

Open `report.md` for the field-drift report.

The bundled prompts extract structured data from support tickets. Prompt A
asks for `summary` and `requested_action`; prompt B renames `summary` to
`issue_summary` and drops `requested_action` — the report below is what that
edit actually does to the output schema.

## Example output

The following is the real output of the command above, run on the three
bundled inputs (`inputs/ticket-001.json` … `ticket-003.json`) with the
default offline mock model:

```markdown
# Prompt Diff Report

- Prompt A: `a.txt`
- Prompt B: `b.txt`
- Model: `mock`
- Inputs checked: 3
- Total drift changes: 6

## Summary

| Change | Count |
| --- | ---: |
| Added fields | 0 |
| Removed fields | 3 |
| Renamed fields | 3 |
| Changed types | 0 |

## Per-input drift

### ticket-001.json

| Field | Change | A | B |
| --- | --- | --- | --- |
| `issue_summary` | renamed | summary | issue_summary |
| `requested_action` | removed | string | - |

### ticket-002.json

| Field | Change | A | B |
| --- | --- | --- | --- |
| `issue_summary` | renamed | summary | issue_summary |
| `requested_action` | removed | string | - |

### ticket-003.json

| Field | Change | A | B |
| --- | --- | --- | --- |
| `issue_summary` | renamed | summary | issue_summary |
| `requested_action` | removed | string | - |
```

Reading it: every ticket loses `requested_action` (any code reading that
field breaks), and `summary` did not disappear — it was renamed to
`issue_summary` with the same value, so a rename fix is enough there.

## How it works

- **Schema inference:** each output's JSON shape is inferred recursively
  (scalars become type names, objects recurse), so drift inside nested
  objects such as `customer.tier` is caught too.
- **Rename detection:** a field removed in A and a field added in B at the
  same level, with the same type *and* the same observed value, is reported
  as one `renamed` change instead of an add plus a remove.
- **Mock model (default):** offline and deterministic. It reads the output
  fields from the prompt text itself (the backticked names under
  "Output fields") and fills each one from the input with a fixed rule, so
  the demo runs with no API key and no network. Edit the field list in a
  prompt and the mock output schema follows.
- **Real model:** `--model env` posts `{"prompt": ..., "input": ...}` to the
  endpoint in `PROMPT_DIFF_CHECKER_ENDPOINT` (optional
  `PROMPT_DIFF_CHECKER_API_KEY` as a Bearer token) and accepts a JSON object
  or `{"output": {...}}` in reply. With the endpoint unset it exits 2 with a
  clear message instead of a traceback.

## Tests

```bash
python -m unittest discover -s tests -v
```

5 tests, all passing: removed/renamed detection, identical prompts produce an
empty drift report, nested-object schema comparison (removed nested field,
changed nested type, object replaced by a scalar), changed-type detection,
and a clean exit-2 failure for `--model env` with no endpoint configured.

## Division of labour with `prompt-regression`

This project is the sibling of
[`prompt-regression`](https://github.com/Mahgal/prompt-regression)
(same author, same prompt-QA family — see that repo for the link back):

- **`prompt-regression` asserts pass/fail on prompt outputs** — it runs a
  prompt against a test set and checks each output against assertions.
- **`prompt-diff-checker` visualises schema drift across a test set** — it
  compares two prompt versions and shows which output fields were added,
  removed, renamed, or changed type.

Use `prompt-regression` to decide whether a prompt version is *correct*;
use `prompt-diff-checker` to see what a prompt edit *changed*. They share
the same "run prompts over JSON inputs, no heavy dependencies" shape on
purpose, but they answer different questions and neither replaces the other.

## License

MIT — see [LICENSE](LICENSE).
