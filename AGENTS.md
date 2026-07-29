# Repository Agent Instructions

## Scope

This repository hosts independently deployable resource-access services and shared packages. Agent-generated changes must preserve service boundaries, tenant isolation, contract compatibility, auditability, and failure recovery.

## File/Media work

For any work under `services/file-media-stream-service/**` or related shared packages, read these files before editing:

1. `docs/architecture/file-media-stream-service/文件-音视频访问服务.png`
2. `docs/architecture/file-media-stream-service/architecture-baseline.md`
3. `docs/development/file-media-stream-service-vibe-coding-constraints.md`

The original architecture image is authoritative and must not be edited, redrawn, optimized, recompressed, or replaced.

## Mandatory behavior

- State the intended scope and non-goals before implementation.
- Keep Agent Gateway and business-service Unified Entry as separate interfaces.
- Route every operation through the Unified Entry authorization/policy/idempotency/audit pipeline.
- Bind all persistent resources and queries to `tenant_id + biz_domain`.
- Never accept client-controlled physical paths or final object keys.
- Keep original file/media payloads out of logs, audit records, JSON APIs, and message bodies.
- Use ports/adapters for object storage, media infrastructure, and processing providers.
- Add contract, tenant-isolation, idempotency, failure-injection, and secret-log tests for every relevant feature.
- Make small, reviewable changes. Do not perform unrelated refactors or dependency upgrades.
- Do not claim completion with placeholders, skipped tests, swallowed errors, or mocks that bypass the behavior under test.

## Current branch phase

The initial file/media branch is documentation-and-constraints only. Do not create implementation code until a later user instruction explicitly starts a development phase.
