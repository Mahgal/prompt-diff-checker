# SMOKE.md — prompt-diff-checker

Commands run from `prompt-diff-checker/` on 2026-11-10 (Python 3.12.3).
All exit codes are real, from the runs below.

## 1. Unit tests

```bash
python3 -m unittest discover -s tests -v
```

Exit code: **0** — 5 tests, all `ok`:

- `test_removed_and_renamed_fields_detected` — ok
- `test_identical_prompts_produce_empty_drift` — ok
- `test_schema_comparison_handles_nested_objects` — ok
- `test_changed_type_detected` — ok
- `test_env_model_without_endpoint_fails_cleanly` — ok

Note: the first test run exited 1 because of a bug in my own test data
(`schema_c` in the nested-object test was missing the `id` key, so `id`
was reported as removed). The implementation was correct; I fixed the test
(`schema_c` now includes `"id": "string"`) and re-ran — exit 0.

## 2. CLI end-to-end (default mock model, offline)

```bash
python3 diff_checker.py --prompt-a prompts/a.txt --prompt-b prompts/b.txt \
  --inputs inputs/ --out report.md
```

Exit code: **0** — output: `Wrote report.md (3 inputs, 6 drift changes)`.
The generated `report.md` is committed in this directory; the same output is
pasted verbatim in README.md ("Example output").

## 3. `--model env` with no endpoint configured (clean-failure check)

```bash
env -u PROMPT_DIFF_CHECKER_ENDPOINT -u PROMPT_DIFF_CHECKER_API_KEY \
  python3 diff_checker.py --prompt-a prompts/a.txt --prompt-b prompts/b.txt \
  --inputs inputs/ --out /tmp/pdc-env-report.md --model env
```

Exit code: **2** — stderr: `Error: No model endpoint configured: set the
PROMPT_DIFF_CHECKER_ENDPOINT environment variable to an HTTP(S) endpoint URL
(optionally PROMPT_DIFF_CHECKER_API_KEY for auth), or run with --model mock
(the default, offline).` No traceback.
