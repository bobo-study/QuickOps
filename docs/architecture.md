# QuickOps Harness Agent architecture

## Current local development slice

```text
React UI
  -> QuickOps product API
    -> Agno AgentOS / Agent / OpenAIChat
      -> QuickOps Harness Agent
        -> ReadOnlyOperationsToolkit + ManagedOperationsToolkit
          -> LocalHostAdapter
            -> real macOS / Linux / Windows observations
        -> Agno streaming + HITL confirmation / continuation

    -> Product persistence (SQLAlchemy + SQLite)
      -> sessions / messages / model configs / settings
      -> agent runs / replayable events / branches / audit events

    -> AI: ControlledCommandExecutor -> policy -> argv-only subprocess
    -> Manual: ManualCommandExecutor -> native platform shell
```

The current target is the machine running QuickOps. Its id is derived from the runtime platform
(`local-macos`, `local-linux`, or `local-windows`), and host cards/signals are collected by the
server rather than fixtures.

## What Agno owns

- Agent and model orchestration
- OpenAI-compatible provider adaptation through `OpenAIChat`
- Tool schemas, tool invocation, streaming events, HITL confirmation/continuation, tracing,
  retries, and event persistence
- Agent session/run history through `SqliteDb`
- AgentOS runtime and inspection APIs

QuickOps does not recreate those capabilities. Product-specific host and risk rules are exposed as
Agno `Toolkit` functions; Agno itself owns the tool lifecycle and confirmation pause.

## What QuickOps owns

- Host identity, authorization, collection, and transport policy
- Product sessions that combine AI messages and complete manual Shell input/output
- Background run ownership, durable SSE replay, and branching through a selected message
- Provider/model registry and server-only credential projection
- Command risk classification and permission-mode enforcement
- Operator approval UX and AI-only immutable command audit events

## Permission semantics

- The initial mode is `approval`.
- `readonly`: the agent receives observation tools only.
- `approval`: read-only observation and directory navigation run directly; mutations require
  explicit confirmation.
- `delegated_approval`: clearly safe operations may execute with audit; recognized risky
  operations pause for approval.
- `full_access`: AI commands execute without QuickOps confirmation or policy restriction and are
  still subject to the target operating-system account's native permissions.

The server classifies the actual operation rather than trusting the tool name selected by the
model. Malformed or compound control syntax is rejected before execution. These restrictions do
not apply to the operator-owned manual terminal.

These rules apply only to AI-selected commands. The manual composer is an operator-owned terminal
transport: it forwards text to the platform's native shell and preserves the full exchange in
session context without AI permission or audit gates. It retains a duration and output bound so a
terminal request cannot exhaust the API process.

Agent runs are detached from the request connection. Agno reasoning, content, tool, pause, and
completion events are persisted and replayed over SSE, so switching sessions does not cancel work.
On the first user input, a separate tool-free Agno agent generates the session title with provider
thinking explicitly disabled.

## Persistence and secrets

Agno and QuickOps share the local SQLite file while retaining separate tables and ownership. The
database is owner-readable/writable only (`0600`). API responses expose `has_api_key`, never the
secret value. For a multi-user or hosted deployment, provider keys must move to an OS keychain or
dedicated secret manager before production rollout.

## Current runtime

- Agent: `quickops-harness`
- Framework: Agno AgentOS
- Model: `deepseek-ai/DeepSeek-V4-Flash`
- Provider: SiliconFlow OpenAI-compatible endpoint
- Host: current macOS/Linux/Windows machine
- Tools: `system_status`, `process_list`, `journal_search`, plus permission-bound command tools
- Manual Shell: native platform terminal pass-through, outside the AI permission/audit path

## Production expansion boundary

Remote hosts should implement the existing `HostAdapter` contract through an authenticated agent,
SSH bastion, Kubernetes API, or other managed transport. The local adapter must not be generalized
into an arbitrary remote-command proxy.
