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
