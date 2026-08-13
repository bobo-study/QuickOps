# Changelog

All notable changes to QuickOps are documented here. The project follows [Semantic Versioning](https://semver.org/) while APIs may still evolve during the `0.x` series.

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
