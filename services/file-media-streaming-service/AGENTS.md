# File / Media Streaming Service — Agent Constraints

This file governs all AI-assisted development under `services/file-media-streaming-service/**`.

## 1. Current phase

The current phase is **constraint and architecture baseline only**.

Until the architecture baseline is reviewed, agents MUST NOT:

- implement production business logic;
- introduce a framework or language by assumption;
- create database migrations;
- add cloud-vendor-specific SDK coupling;
- copy the architecture of another service without an explicit mapping;
- silently change module boundaries, APIs, storage responsibilities, or tenant-isolation rules.

## 2. Source of truth order

When documents conflict, use this priority:

1. user-supplied original architecture package and diagrams;
2. `docs/file-media-streaming-service/architecture-baseline.md`;
3. `docs/file-media-streaming-service/vibi-coding-constraints.md`;
4. repository-wide conventions;
5. implementation convenience.

Implementation convenience can never override an architecture decision.

## 3. Service identity and boundary

The service is a controlled file, audio, and video ingestion/streaming platform. It is not a generic data gateway and not an AI model service.

The service MUST preserve two entry paths:

- Agent callers such as Hermes, OpenClaw, and sub-agents enter through the File / Media Access Gateway and tool-style APIs.
- Ontology and ordinary business services enter through the service's unified business API.

The service owns:

- upload/download and stream session control;
- file/audio/video resource metadata;
- chunking, resumable transfer, integrity verification, and idempotency;
- routing to storage and processing capabilities;
- orchestration of OCR, ASR, video-frame extraction, transcoding, and related adapters;
- signed access URL or stream endpoint issuance;
- tenant, business-domain, case/resource scope enforcement;
- audit, trace, quota, lifecycle, retry, and cleanup state.

The service does not own:

- legal-domain reasoning or ontology semantics;
- long-term agent memory;
- model training or model-serving internals;
- arbitrary database distribution logic;
- direct exposure of MinIO, PostgreSQL, Redis, OCR, ASR, FFmpeg, or cloud SDKs to callers.

## 4. Mandatory context

Every externally initiated operation MUST carry and validate the applicable context:

- `tenant_id`;
- `biz_domain`;
- `request_id`;
- `trace_id`;
- caller identity and caller type;
- resource owner or business object identifier when applicable;
- idempotency key for retryable write operations.

No cross-tenant fallback, global default tenant, or implicit scope inheritance is allowed.

## 5. Architecture rules

- Keep gateway, application orchestration, domain model, infrastructure adapters, and provider integrations separated.
- Use ports/interfaces between the domain/application layer and MinIO, PostgreSQL, Redis, OCR, ASR, video processing, callback, and message-queue implementations.
- Provider-specific fields MUST NOT leak into public contracts.
- Metadata and binary content MUST be managed separately.
- Long-running processing MUST use asynchronous jobs; request threads must not block on full OCR/ASR/transcoding workflows.
- State transitions MUST be explicit, validated, and auditable.
- Upload completion MUST require integrity verification before a resource becomes available.
- Cleanup and expiration actions MUST be idempotent and safe to retry.
- Signed URLs and stream credentials MUST be short-lived and scope-limited.

## 6. Required development sequence

For each implementation phase, agents MUST work in this order:

1. restate the relevant architecture boundary;
2. define or update contracts and schemas;
3. write acceptance criteria and failure cases;
4. write tests;
5. implement the smallest vertical slice;
6. run static checks, unit tests, contract tests, and integration tests;
7. update architecture and decision records;
8. report changed files, executed commands, results, residual risks, and next step.

Do not implement several speculative phases in one change.

## 7. Quality gates

A change is incomplete unless it includes, as applicable:

- positive, negative, timeout, duplicate-request, and permission tests;
- tenant-isolation tests;
- idempotency and state-transition tests;
- secret and sensitive-log review;
- observability fields and trace propagation;
- API/schema compatibility checks;
- cleanup and failure-recovery behavior;
- documentation updates.

Coverage percentage alone is not proof of correctness.

## 8. Forbidden shortcuts

Agents MUST NOT:

- use TODO placeholders for security or tenant isolation;
- return success before durable state is recorded;
- use filenames or client MIME types as the sole trust source;
- log tokens, signed URLs, credentials, raw private media, or complete request bodies by default;
- bypass the service through direct object-storage URLs;
- hard-code tenant IDs, bucket names, provider endpoints, or credentials;
- collapse all processing into one controller or one oversized service class;
- add silent fallback to another tenant, domain, bucket, provider, or model;
- claim tests passed without showing the exact commands and results.

## 9. Stop conditions

Stop and report instead of guessing when:

- the original architecture package contradicts this baseline;
- a public API, storage schema, lifecycle policy, security boundary, or provider choice is missing;
- a destructive migration or incompatible contract change is required;
- credentials or external infrastructure are unavailable for a required verification;
- the requested change would turn this service into a different bounded context.
