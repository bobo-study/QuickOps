# QuickOps 快维 v0.0.2

v0.0.2 is a substantial testing-preview update focused on making QuickOps a dependable long-running operations workspace rather than a short-lived chat interface.

## Highlights

- **Host assets**: manage each service as an isolated operational knowledge space with status probes, historical events, documents, guard policies and Agent-accessible CRUD.
- **Long-session Harness context**: append-only epochs, 90% checkpoint compaction, Agno rolling summaries, bounded tool-result compression and an explicit `正在压缩会话上下文` state.
- **Reliable continuation**: streamed text, tools, approvals and operator choices survive navigation, reload, provider failures and pause/resume without reordering or disappearing.
- **Correct permission semantics**: read-only, approval-required, risk-based delegated approval and full access are enforced server-side from the operation's real impact.
- **Reports and attachments**: create authenticated Markdown, text, HTML, JSON, DOCX or PDF downloads; paste and preview images for multimodal models; preview asset documents in-product.
- **Operator experience**: improved light theme, clearer text contrast, IME-safe input, bounded message layout, meaningful branch titles and functional session-ID copy.

## Install or upgrade

Download both files from this release, then verify and run the installer:

```bash
sha256sum -c quickops-linux-x86_64-offline-v0.0.2.run.sha256
chmod +x quickops-linux-x86_64-offline-v0.0.2.run
sudo ./quickops-linux-x86_64-offline-v0.0.2.run
```

The Linux x86_64 installer is self-contained and does not require internet access, system Python, pip, Docker or Nginx on the target host.

Rerunning the installer over an existing QuickOps installation performs an in-place upgrade. It creates an online SQLite backup and preserves durable sessions, settings and server-side secrets. Restarting the API invalidates existing login cookies, so sign in again after the upgrade.

## Compatibility and safety

- This remains a single-node, single-operator testing preview. Evaluate it on a test machine or controlled intranet before production use.
- Existing SQLite data is migrated automatically. Keep the installer-created backup until the upgraded service has been verified.
- Start with `审批执行`. `替我审批` automatically executes only operations classified as safe and still asks for elevated work.
- Automatic host-asset diagnosis is read-only by default. Corrective actions require an explicit guard policy and remain constrained by server-side risk classification.

See [CHANGELOG.md](CHANGELOG.md) for the complete change list and [docs/QuickOps快维用户使用手册.md](docs/QuickOps快维用户使用手册.md) for the user guide.
