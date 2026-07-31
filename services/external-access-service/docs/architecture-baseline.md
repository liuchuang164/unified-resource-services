# External Access Service Architecture Baseline

Status: **FROZEN FOR INITIAL DEVELOPMENT**

Scope: Alibaba Farui is the only provider implemented in the first delivery, while the service architecture remains provider-neutral.

## 1. Position in Unified Access Plane

The External Access Service is one of three controlled access services:

- Data Access Service: internal structured/object/vector/state data;
- External Access Service: third-party capabilities and APIs;
- File & Media Stream Access Service: files, uploads/downloads, and media streams.

All three services share tenant context, capability control, policy, audit, observability, idempotency, and secret-redaction conventions.

The External Access Service governs third-party access. It is not a legal workflow engine and does not replace business-domain services.

## 2. Required two-layer entry

```mermaid
flowchart TB
  subgraph AGENT[Agent callers]
    A1[Agent]
    A2[OpenClaw]
    A3[Hermes]
    A4[Sub Agent / Skill]
  end

  subgraph BIZ[Business services]
    B1[庭策本体服务]
    B2[Other business-domain services]
  end

  subgraph EAG[Layer 1: External Access Gateway]
    E1[GET /eag/tools]
    E2[GET /eag/tools/{tool_name}/schema]
    E3[POST /eag/tools/execute]
    E4[Tool Registry]
    E5[Schema Validator]
    E6[Trusted Agent Context Resolver]
    E7[External Request Converter]
  end

  subgraph ENTRY[Layer 2: Unified External Entry]
    U1[GET /external/operations]
    U2[GET /external/operations/{operation}/schema]
    U3[POST /external/dispatch]
    U4[Auth and Policy]
    U5[Idempotency / Anti-replay]
    U6[Provider Router]
    U7[Rate Limit / Timeout / Retry / Circuit Breaker]
    U8[Cost and Usage Meter]
    U9[External Audit]
  end

  subgraph PROVIDER[Provider layer]
    P1[Credential Manager]
    P2[ALI_FARUI Adapter]
    P3[Alibaba Farui API]
  end

  A1 --> E1
  A2 --> E2
  A3 --> E3
  A4 --> E3
  E1 --> E4
  E2 --> E4
  E3 --> E5 --> E6 --> E7 --> U3

  B1 --> U3
  B2 --> U3

  U1 --> U6
  U2 --> U6
  U3 --> U4 --> U5 --> U6 --> U7 --> P1 --> P2 --> P3
  U7 --> U8
  U7 --> U9
```

Critical boundary:

- Agent callers enter through the Gateway Tool layer.
- Business services enter the unified external entry directly.
- Every real provider call passes through `/external/dispatch` application logic.
- Gateway and business services never receive provider credentials.

## 3. Alibaba Farui initial tool model

Tool name: `ali_farui`

Supported action names reserved by the architecture:

- `legal_consult`
- `law_search`
- `case_search`
- `legal_research_full`

Canonical operations:

- `ALI_FARUI_LEGAL_CONSULT`
- `ALI_FARUI_LAW_SEARCH`
- `ALI_FARUI_CASE_SEARCH`
- `ALI_FARUI_LEGAL_RESEARCH_FULL`

Only capabilities verified against the real account/API may be enabled. Registration of an operation does not permit a fake implementation.

## 4. Example dispatch

```json
{
  "request_source": "AGENT_TOOL",
  "auth_context": {
    "tenant_id": "tenant_A",
    "user_id": "user_001"
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
    "retry": {
      "enabled": true,
      "max_attempts": 2
    },
    "max_cost_amount": 5,
    "cost_unit": "CNY"
  }
}
```

## 5. Module boundaries

| Module | Owns | Must not own |
|---|---|---|
| External Access Gateway | Tool listing, schemas, capability verification, request conversion | Credentials, raw provider calls, provider retry/signature |
| Unified External Entry | Authorization, policy, routing, resilience, idempotency, cost, audit | Business legal reasoning |
| Credential Manager | Secret lookup, rotation metadata, scoped credential resolution | Logging or returning plaintext secrets |
| Provider Registry/Router | Canonical operation to adapter resolution | Tenant authorization bypass |
| Alibaba Farui Adapter | Protocol/auth mapping and provider response parsing | Tenant policy, billing policy, Agent workflow |
| Rate Limit/Retry/Circuit Breaker | Controlled outbound-call governance | Hidden failure or unlimited retries |
| Cost & Usage Meter | Calls, usage, cost evidence | Product pricing decisions |
| External Audit | Allowed/denied call evidence and safe summaries | Full credentials or unrestricted sensitive payloads |

## 6. Isolation and security invariants

1. `tenant_id + biz_domain` scope is mandatory on every request and persistence key.
2. Agent-provided identity is not trusted without authenticated context and capability-token verification.
3. Tool visibility and operation access are filtered by tenant/business-domain policy.
4. Credentials are resolved server-side and never supplied by Agent input.
5. Provider host is configuration-controlled and allowlisted; arbitrary outbound URLs are forbidden.
6. Logs, audit, traces, metrics, fixtures, and errors recursively redact secrets.
7. Retry is bounded and only applied to classified retryable, safe operations.
8. Cost/budget checks occur before billable calls; actual usage is recorded after calls.
9. Provider responses are normalized and treated as untrusted external content.
10. No cross-tenant cache, rate-limit, credential, audit, or usage key is permitted.

## 7. Reference implementation rule

`liuchuang164/claria/external-access-gateway` may be used to learn:

- existing Alibaba Farui authentication and payload shape;
- working endpoint behavior;
- reusable response parsing;
- known provider failure cases.

It is explicitly not authoritative for:

- service boundaries;
- endpoint design;
- tenant/business-domain isolation;
- capability-token rules;
- provider-neutral contracts;
- idempotency, cost, audit, and resilience controls.

Any adapted code must enter through the Alibaba Farui adapter boundary and satisfy the constraints in `../AGENTS.md`.

## 8. Initial acceptance boundary

The first development milestone is complete only when:

- both entry layers exist and are tested;
- only `ALI_FARUI` is enabled;
- the Farui adapter is replaceable through a provider port;
- tenant/business-domain and capability controls fail closed;
- secrets are absent from source, logs, audit, fixtures, snapshots, and reports;
- timeout/retry/rate-limit/circuit/cost behavior has fault-injection coverage;
- fake-provider and real-provider test evidence are clearly distinguished;
- a controlled end-to-end call reaches Alibaba Farui through the unified external entry.
