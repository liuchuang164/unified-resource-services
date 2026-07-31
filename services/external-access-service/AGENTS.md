# External Access Service — Codex / Vibe Coding Development Constraints

> Scope: `services/external-access-service`
>
> Current delivery scope: **only Alibaba Farui (`ALI_FARUI`) external access**.
>
> Architecture authority: the uploaded Unified Access Plane architecture package. The existing `liuchuang164/claria/external-access-gateway` implementation is reference material only and must not override this document or the target architecture.

## 1. Non-negotiable architecture

The service must remain a generic **External Access Service**, not an Alibaba Farui-specific proxy. Alibaba Farui is the first provider adapter.

There are two distinct entry layers:

1. **External Access Gateway / Agent Tool layer**
   - `GET /eag/tools`
   - `GET /eag/tools/{tool_name}/schema`
   - `POST /eag/tools/execute`
   - Used by Agent, OpenClaw, Hermes, Sub Agent, and Skill callers.
   - Converts a trusted Tool request into an internal `ExternalRequest`.

2. **Unified External Entry / service control layer**
   - `GET /external/operations`
   - `GET /external/operations/{operation}/schema`
   - `POST /external/dispatch`
   - Used by the Gateway layer and business-domain services.
   - Owns authorization, policy enforcement, idempotency, provider routing, credential selection, rate limiting, timeout, retry, circuit breaking, usage/cost metering, standard response mapping, and audit.

Mandatory call paths:

- Agent path: `Agent/OpenClaw/Hermes -> /eag/tools/* -> /external/dispatch -> provider adapter -> Alibaba Farui`
- Business-service path: `Business service -> /external/dispatch -> provider adapter -> Alibaba Farui`

Forbidden shortcuts:

- Gateway code calling Alibaba Farui directly.
- Business services calling `/eag/tools/execute`.
- Provider adapters performing tenant authorization or business policy decisions.
- Exposing Alibaba Farui API keys, tokens, cookies, signatures, raw headers, or credential IDs to callers.
- Hard-coding Alibaba Farui semantics into common domain contracts.

## 2. Source-of-truth precedence

When requirements conflict, use this order:

1. This branch's architecture baseline and constraints.
2. Uploaded Unified Access Plane architecture package.
3. Contracts and shared conventions already present in `unified-resource-services`.
4. Alibaba Farui official API documentation and actual sandbox behavior.
5. `liuchuang164/claria/external-access-gateway` as implementation reference only.

Code copied or adapted from `claria` must be re-evaluated for:

- two-layer entry separation;
- `tenant_id + biz_domain` isolation;
- capability-token enforcement;
- provider-neutral ports and contracts;
- credential secrecy;
- idempotency and billing-safe retry;
- audit and usage metering;
- standard error mapping.

Do not copy directory structure or business assumptions merely because they already exist in `claria`.

## 3. Current provider and operation scope

Only register this tool in the initial phase:

- Tool name: `ali_farui`
- Provider code: `ALI_FARUI`
- Business domain initially allowed: `LEGAL`

Initial actions and canonical operations:

| Tool action | Canonical operation |
|---|---|
| `legal_consult` | `ALI_FARUI_LEGAL_CONSULT` |
| `law_search` | `ALI_FARUI_LAW_SEARCH` |
| `case_search` | `ALI_FARUI_CASE_SEARCH` |
| `legal_research_full` | `ALI_FARUI_LEGAL_RESEARCH_FULL` |

If the real Alibaba Farui account/API currently supports fewer capabilities, implement only verified capabilities and return an explicit `OPERATION_NOT_AVAILABLE` for unsupported operations. Do not fabricate success responses.

No other provider may be implemented in this phase. Other providers may appear only as interfaces, enum placeholders, or documented extension points when needed to keep the design provider-neutral.

## 4. Required bounded contexts and module boundaries

Use clean/hexagonal boundaries. Exact language/framework should follow repository conventions, but responsibilities must remain separated.

### 4.1 Gateway layer

Responsibilities:

- expose the three `/eag` endpoints;
- resolve trusted agent context;
- verify capability token scope;
- expose only tools/actions allowed for the current tenant and business domain;
- validate Tool input schema;
- convert `ToolRequest` to provider-neutral `ExternalDispatchRequest`;
- call the unified external entry through an application port;
- wrap the response in the common Tool response format.

Must not:

- read provider credentials;
- choose a physical credential;
- implement provider retry/signature logic;
- perform raw network calls;
- make legal conclusions.

### 4.2 Unified external entry

Responsibilities:

- validate request and trusted context;
- enforce tenant/business-domain/provider/operation policy;
- validate idempotency and anti-replay rules;
- resolve provider adapter and credential reference;
- apply timeout, rate limit, retry, circuit breaker, cache, and budget controls;
- call the adapter through a port;
- record usage, cost, latency, result state, and audit events;
- normalize provider responses and failures.

This is the authoritative control point. Every real provider call must pass through it.

### 4.3 Provider credential manager

Responsibilities:

- retrieve credentials by `tenant_id + biz_domain + provider_code + environment`;
- support secret references rather than plaintext config where possible;
- support rotation/version metadata;
- return a short-lived in-process credential object only to the adapter execution path.

Must never:

- serialize secrets into API responses;
- write secrets into structured logs, traces, metrics labels, audit records, snapshots, test fixtures, or exception messages;
- accept provider secrets from Agent Tool input.

### 4.4 Provider adapter layer

The Alibaba Farui adapter only performs protocol adaptation:

- map canonical operation input to verified Farui request shape;
- add authentication/signature required by the provider;
- call the provider;
- parse provider response;
- map provider errors into normalized adapter errors;
- return provider usage metadata when available.

It must not contain tenant policy, user-role policy, billing rules, Agent logic, or business workflow orchestration.

### 4.5 Audit and usage metering

Record at minimum:

- `request_id`, `trace_id`, `audit_id`;
- trusted `tenant_id`, `biz_domain`;
- request source;
- agent/user/session/task IDs when present;
- provider code and canonical operation;
- credential reference/version, never secret value;
- attempt count, cache hit, circuit state;
- start/end time and latency;
- normalized outcome/error code;
- provider usage and estimated/actual cost when available;
- payload/response hashes or safe summaries, not unrestricted sensitive content.

Allowed and denied requests must both be auditable.

## 5. Trusted context and isolation

`tenant_id` and `biz_domain` are mandatory isolation keys.

Rules:

- Never trust identity fields supplied only inside model-generated Tool params.
- Construct `TenantBizContext` from authenticated middleware and verified capability-token claims.
- If body/query identity fields are accepted for compatibility, they must exactly match trusted context or the request is rejected.
- Tool registry visibility must be filtered before returning tools or schemas.
- Credential resolution, rate limit keys, cache keys, idempotency keys, audit records, and usage records must all include tenant and business-domain scope.
- Cross-tenant fallback is forbidden.
- Global/default credentials may only be used through an explicit platform policy and must still produce tenant-scoped audit and usage records.

Capability token scope must be precise enough to bind:

- tenant;
- business domain;
- tool;
- action;
- optional resource/scene constraints;
- expiration and token ID for anti-replay.

## 6. Canonical contracts

### 6.1 Tool execution request

Minimum fields:

```json
{
  "request_id": "req_001",
  "trace_id": "trace_001",
  "agent_id": "agent_001",
  "session_id": "session_001",
  "task_id": "task_001",
  "tenant_id": "tenant_A",
  "biz_domain": "LEGAL",
  "tool_name": "ali_farui",
  "action": "legal_research_full",
  "capability_token": "<signed-token>",
  "input": {
    "query": "民间借贷纠纷中只有转账记录时的法律依据和类案风险"
  }
}
```

### 6.2 Unified dispatch request

Minimum fields:

```json
{
  "request_id": "req_001",
  "trace_id": "trace_001",
  "request_source": "AGENT_TOOL",
  "auth_context": {
    "tenant_id": "tenant_A",
    "user_id": "user_001",
    "roles": ["LAWYER"]
  },
  "biz_context": {
    "biz_domain": "LEGAL",
    "biz_scene": "LEGAL_RESEARCH"
  },
  "operation": "ALI_FARUI_LEGAL_RESEARCH_FULL",
  "provider": {
    "provider_code": "ALI_FARUI",
    "capability": "LEGAL_RESEARCH"
  },
  "payload": {
    "query": "民间借贷纠纷中只有转账记录时的法律依据和类案风险"
  },
  "policy": {
    "timeout_ms": 30000,
    "retry": {"enabled": true, "max_attempts": 2},
    "max_cost_amount": 5,
    "cost_unit": "CNY"
  }
}
```

Request contracts must use strict JSON Schema/OpenAPI definitions. Reject unknown security-sensitive fields. Do not accept arbitrary provider URLs, HTTP methods, headers, credential names, or raw request bodies from Agent callers.

### 6.3 Unified response

Use the shared response envelope:

```json
{
  "success": true,
  "request_id": "req_001",
  "trace_id": "trace_001",
  "code": "OK",
  "message": "Operation completed successfully",
  "data": {},
  "usage": {
    "latency_ms": 25,
    "provider": "ALI_FARUI",
    "attempts": 1,
    "cache_hit": false
  },
  "audit_id": "audit_001",
  "error": null
}
```

Provider raw response may be retained only behind an explicitly governed diagnostic setting. Public responses must use stable canonical fields so future provider adapters can be substituted.

## 7. Reliability and cost safety

- Every outbound call must have connection and total timeouts.
- Retry only failures classified as retryable.
- Do not retry validation, authentication, authorization, unsupported-operation, or deterministic provider errors.
- For potentially billable calls, retries require an idempotency strategy or proof the provider operation is read-only.
- Use exponential backoff with jitter and a strict attempt limit.
- Circuit breaker state must be scoped by provider and preferably tenant/credential pool where appropriate.
- Rate limiting must support tenant, operation, and credential/provider dimensions.
- Cache only operations whose semantics and data sensitivity permit caching; cache keys must include tenant, business domain, provider, operation, normalized input hash, and contract version.
- Budget/cost policy must be checked before the provider call and usage recorded after the call.
- Never silently downgrade to another provider in this phase.

## 8. Security and privacy

Mandatory protections:

- recursive redaction for `authorization`, `cookie`, `token`, `access_token`, `refresh_token`, `api_key`, `secret`, `signature`, and equivalent aliases;
- log/trace payload size limits;
- safe exception mapping;
- outbound host allowlist fixed by provider configuration;
- TLS certificate verification enabled;
- no user-controlled proxy URL or redirect target;
- SSRF-safe network client behavior;
- input size, result size, and pagination limits;
- HTML/Markdown/provider text treated as untrusted content;
- prompt-injection-like text returned by provider must never be interpreted as service configuration or system instruction.

Legal research results are reference material, not authoritative legal advice. The service transports and normalizes results; it does not assert legal correctness.

## 9. Error model

Define stable normalized error codes, including at least:

- `INVALID_REQUEST`
- `UNAUTHENTICATED`
- `CAPABILITY_TOKEN_INVALID`
- `CAPABILITY_DENIED`
- `TENANT_CONTEXT_MISMATCH`
- `TOOL_NOT_FOUND`
- `ACTION_NOT_SUPPORTED`
- `OPERATION_NOT_AVAILABLE`
- `PROVIDER_NOT_CONFIGURED`
- `PROVIDER_CREDENTIAL_UNAVAILABLE`
- `RATE_LIMITED`
- `BUDGET_EXCEEDED`
- `IDEMPOTENCY_CONFLICT`
- `PROVIDER_TIMEOUT`
- `PROVIDER_AUTH_FAILED`
- `PROVIDER_REJECTED_REQUEST`
- `PROVIDER_RATE_LIMITED`
- `PROVIDER_UNAVAILABLE`
- `PROVIDER_RESPONSE_INVALID`
- `CIRCUIT_OPEN`
- `INTERNAL_ERROR`

Raw provider error bodies and secrets must not be returned to callers.

## 10. Development phases and gates

Do not generate the full service in one uncontrolled pass. Each phase must leave compilable, testable code and a written verification result.

### Phase 0 — architecture and contracts

Deliver only:

- service skeleton;
- module boundaries and ports;
- canonical contracts and JSON Schemas;
- tool/operation registry definitions;
- error model;
- configuration schema with secret references only;
- ADRs for the two-layer entry and provider adapter boundary;
- contract/security tests using fakes, no real provider call.

Gate: architecture tests prove Gateway cannot directly depend on the Farui HTTP client.

### Phase 1 — unified entry core

Deliver:

- trusted context validation;
- policy port;
- idempotency port;
- provider registry/router;
- audit and usage ports;
- standard response/error mapping;
- in-memory test adapters.

Gate: all allow/deny/error paths emit audit records and preserve tenant isolation.

### Phase 2 — Agent Tool Gateway

Deliver the three `/eag` endpoints, capability filtering, schema validation, and request conversion.

Gate: forged tenant IDs, expired tokens, wrong action scopes, unknown fields, and direct provider parameters are rejected.

### Phase 3 — Alibaba Farui adapter

Deliver verified Farui HTTP/auth mapping behind the adapter port. Start with mocked/sandbox integration tests. Real credentials must be injected through secret references and never committed.

Gate: captured request/response fixtures contain no real secret; provider errors normalize correctly.

### Phase 4 — reliability and cost governance

Deliver rate limiting, timeout, retry, circuit breaker, cache policy, and cost/usage metering.

Gate: fault-injection tests cover timeout, 429, 5xx, malformed response, auth failure, retry exhaustion, circuit open, and budget denial.

### Phase 5 — real integration and release evidence

Deliver controlled real-provider verification, OpenAPI, operations runbook, observability dashboard definitions, and final test report.

Gate: real call proves end-to-end path through `/external/dispatch`; logs/audit contain no credentials; no cross-tenant leakage; all required tests pass.

Codex must stop at each phase boundary and report changed files, tests, unresolved risks, and exact next gate. It must not self-approve a gate based only on compilation.

## 11. Testing requirements

Minimum automated coverage:

- unit tests for schemas, converters, policy decisions, router, redaction, error mapping, retry classification, and cost checks;
- contract tests for all six HTTP endpoints;
- architecture/dependency tests enforcing layer boundaries;
- tenant/business-domain isolation tests;
- capability-token negative tests;
- idempotency and anti-replay tests;
- fake-provider integration tests;
- fault-injection tests;
- audit completeness tests;
- secret leakage scans over source, fixtures, logs, snapshots, and reports;
- real-provider smoke test only when explicitly configured.

Tests must assert outcomes and side effects, not merely HTTP status codes.

Never mark a fake-provider test as a real Alibaba Farui integration test.

## 12. Coding constraints

- Prefer small explicit modules over a single gateway/controller/service file.
- Keep domain/application code independent from HTTP framework and Alibaba SDK/client types.
- No `any`-style untyped escape hatches in public contracts without written justification.
- No swallowing exceptions or returning fake fallback data.
- No placeholder TODO on a security-critical path while claiming the phase complete.
- No hard-coded tenant, provider credential, endpoint, price, timeout, or quota in application logic.
- Configuration must be validated at startup and fail closed.
- Database migrations, if added, must be forward-only, scoped, reviewed, and tested.
- Every public endpoint and operation must have versioned contract tests.
- Generated OpenAPI must match runtime validation.

## 13. Required delivery report for every Codex change

Each implementation response/commit must state:

1. phase and gate being addressed;
2. files changed;
3. architecture boundaries preserved;
4. tests run with exact results;
5. whether any real Alibaba Farui call occurred;
6. credential handling and secret-scan result;
7. known limitations and next gate;
8. explicit confirmation that no other provider was implemented.

A build passing without these proofs is not considered completion.
