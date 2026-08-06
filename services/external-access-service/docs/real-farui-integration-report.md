# Real Alibaba Farui Integration Gate Report

Date: 2026-08-06

## Scope

- Scope: `services/external-access-service` only.
- Goal: replace the placeholder Farui protocol mapping with real Alibaba Farui connection modes and add a real gate.
- Non-goals: no `farui-service`, no `farui-gateway`, no Agent or business-service direct Farui call, no raw Farui response exposure, no real secret committed.

## Architecture Result

Status: PASS

- Agent path remains `POST /eag/tools/execute -> UnifiedExternalEntry -> Provider Runtime -> ALI_FARUI Adapter`.
- Business path remains `POST /external/dispatch -> UnifiedExternalEntry -> Provider Runtime -> ALI_FARUI Adapter`.
- Gateway does not read credentials or call Farui directly.
- Business service entry does not call Gateway.
- Credential resolution stays behind `EnvironmentCredentialProvider` and returns a short-lived `ProviderCredential`.
- Adapter only performs Farui protocol/auth mapping and normalized response parsing.

## Farui Connection Modes

| Mode | Source | Status |
|---|---|---|
| ACS3 AK/SK | `ALI_FARUI_ACCESS_KEY_ID`, `ALI_FARUI_ACCESS_KEY_SECRET`, `ALI_FARUI_WORKSPACE_ID` or `FARUI_*` aliases | Implemented, not run locally because env is missing |
| Workspace API key | `ALI_FARUI_ENDPOINT + ALI_FARUI_APP_KEY` or CSV credentials file | Implemented and run with local CSV |

CSV file used locally:

- Path: `/Users/liuchuang/Desktop/external-access-server/默认业务空间-apiKey-6381250.csv`
- Secret values: not recorded
- Non-secret connection evidence: workspace id present, DashScope endpoint present, app/model id present

## Operation Mapping

| Canonical operation | ACS3 action/path | Workspace API-key path |
|---|---|---|
| `ALI_FARUI_LEGAL_CONSULT` | `RunLegalAdviceConsultation`, `/{workspace_id}/farui/legalAdvice/consult` | `/api/v1/apps/{app_id}/completion` |
| `ALI_FARUI_LAW_SEARCH` | `RunSearchLawQuery`, `/{workspace_id}/farui/search/law/query` | `/api/v1/apps/{app_id}/completion` |
| `ALI_FARUI_CASE_SEARCH` | `RunSearchCaseFullText`, `/{workspace_id}/farui/search/case/fulltext` | `/api/v1/apps/{app_id}/completion` |
| `ALI_FARUI_LEGAL_RESEARCH_FULL` | `RunSearchCaseFullText`, `/{workspace_id}/farui/search/case/fulltext` | `/api/v1/apps/{app_id}/completion` |

## Verification

| Check | Result | Evidence |
|---|---|---|
| Unit/integration/e2e suite | PASS | `56 passed, 2 skipped` |
| Ruff | PASS | `All checks passed!` |
| Mypy | PASS | `Success: no issues found in 58 source files` |
| Real Farui gate with `RUN_REAL_FARUI_GATE=1` and local CSV | FAIL | Provider returned HTTP 403 through both Agent and Business paths |

Real gate command:

```bash
RUN_REAL_FARUI_GATE=1 PYTHONPATH=src python -m pytest tests/integration/test_real_farui_gate.py -q
```

Real gate result:

- Business path: FAIL at first tool, normalized error `PROVIDER_AUTH_FAILED`, provider HTTP status `403`.
- Agent path: FAIL at first tool, normalized error `PROVIDER_AUTH_FAILED`, provider HTTP status `403`.
- Provider URL shape reached: workspace DashScope app completion endpoint.
- No raw provider response body or secret was stored in this report.

## Gate Conclusion

Real Alibaba Farui Integration Gate: FAIL

Reason: the provided workspace API-key CSV is readable and routed through the required service architecture, but Alibaba returned `403 Forbidden` for the app completion call. This is treated as a real provider authentication/authorization failure, not a mock success.

The implementation is ready for another real gate run after the CSV API key/app id is granted permission, or after AK/SK/workspace credentials are supplied for ACS3 mode.
