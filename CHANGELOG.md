# Changelog

All notable changes to QuickOps are documented here. The project follows [Semantic Versioning](https://semver.org/) while APIs may still evolve during the `0.x` series.

## [0.0.2] - 2026-09-21

### Added

- Host asset center with per-service status, event and document spaces; complete CRUD; immediate probes; mounted-asset retrieval; operator guard policies; transition monitoring; and read-only automatic incident triage.
- Downloadable, authenticated session reports in Markdown, text, HTML, JSON, DOCX and PDF, plus an offline user manual.
- Multimodal image paste/upload with thumbnails, durable message attachments, model capability checks and asset-document archiving.
- Dark/light themes, clearer light-theme contrast and in-product document preview.
- Structured operator-choice cards with an inline `其他` answer and same-run continuation.
- Optional Agno CSV analysis and Airflow toolkits.

### Changed

- Reworked long-session context into append-only epochs with a 90% context checkpoint, rolling Agno summaries, 55% tool-result compression, bounded fallback excerpts and explicit compaction status.
- Stabilized provider-cache prefixes by moving changing runtime data into append-only snapshots and placing request time at the end of the prompt.
- Expanded the host-asset toolkit so 小维 can inspect, create, update, delete, mount, unmount, probe and maintain service knowledge directly.
- Clarified the four permission modes: `替我审批` now automatically admits classified safe work and asks the operator only for elevated operations.
- Kept approval/feedback continuation inside the original assistant response and preserved complete ordered text, tool, approval and feedback events across reloads.
- Improved session branching names, non-blocking title fallback, background-run indicators and cross-session run continuity.

### Fixed

- Prevented assistant execution chains, pending approvals and answered choice cards from disappearing, duplicating or rolling back after navigation or reload.
- Preserved conversational recovery context after provider failures, interruptions and empty upstream responses, including when switching to a newly selected model.
- Corrected approval ordering so each approval result remains attached to its exact tool call before later operations.
- Prevented message-width overflow, collapsed transcript content, trailing user-message whitespace and IME Enter mis-submission.
- Fixed image attachments remaining in the composer after send and added visual thumbnails instead of filename-only chips.
- Added actionable provider error normalization for rate limits, insufficient balance, empty errors and unknown-model failures.
- Raised the default per-run tool-call circuit breaker to 32 so ordinary diagnostics do not fail as a normal quota.
- Made the session-ID copy action functional and accessible.

### Security

- Asset document previews render untrusted text as inert content; model and database secrets remain server-side.
- Background asset monitoring remains read-only by default; any corrective action continues through the same server-side permission and HITL policy.
- Report downloads and document previews are authenticated and session/asset scoped.

## [0.0.1] - 2026-08-13

### Added

- Agno-powered AI operations agent with streaming, tools, sessions, summaries, and HITL continuation.
- Four-level AI permission policy and impact-based command classification.
- One persistent shared shell per conversation for AI and manual operations.
- Cross-platform local host identity and live signals for macOS, Linux, and Windows.
- Durable SQLite sessions, messages, branches, approvals, audit events, settings, and model registry.
- Server-side login authentication, rate limiting, and HttpOnly session cookies.
- Optional Agno toolkits and session-scoped database connection parameters.
- Chinese/English application UI.
- Self-contained offline Linux x86_64 installer with in-place upgrade and SQLite backup.

### Security

- Model secrets remain server-side and are excluded from public APIs.
- AI command admission and audit are enforced server-side.
- Public repository excludes local environments, databases, logs, caches, and deployment credentials.
