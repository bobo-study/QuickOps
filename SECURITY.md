# Security Policy

## Supported versions

QuickOps is currently an early-preview project. Security fixes are provided for the latest published `0.x` release and the current `main` branch.

## Reporting a vulnerability

请不要为未修复的漏洞创建公开 Issue。Please do not open a public issue for an unpatched vulnerability.

Use GitHub's **Report a vulnerability** private reporting feature on this repository. Include:

- affected version and platform;
- reproduction steps or a minimal proof of concept;
- expected impact;
- suggested mitigation, if known.

Please avoid accessing data that is not yours, modifying production systems, or performing destructive tests. We will acknowledge a complete report as soon as practical and coordinate disclosure after a fix is available.

## Deployment security baseline

- Set a unique `QUICKOPS_AUTH_USERNAME` and a long random `QUICKOPS_AUTH_PASSWORD`.
- Keep model and database credentials server-side; never place them in frontend code or public logs.
- Run QuickOps as a dedicated non-root OS account.
- Expose the HTTP service only on a trusted intranet or behind an operator-managed secure reverse proxy/VPN.
- Start with `审批执行` / approval-required mode and review commands before approval.
- Back up SQLite before upgrading and verify release checksums before installation.
