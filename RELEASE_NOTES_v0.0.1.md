# QuickOps 快维 v0.0.1

首个公开预览版本。The first public preview release.

QuickOps combines an Agno-powered operations agent, persistent per-conversation terminal, real host telemetry, four permission levels, HITL approvals, durable SQLite history, optional toolkits, and a Chinese/English interface.

## Installation

Download both assets, verify the checksum, and run the installer on Linux x86_64:

```bash
sha256sum -c quickops-linux-x86_64-offline-v0.0.1.run.sha256
chmod +x quickops-linux-x86_64-offline-v0.0.1.run
sudo ./quickops-linux-x86_64-offline-v0.0.1.run
```

The installer is self-contained and does not require Python, pip, Nginx, Docker, a package manager, or internet access on the target server.

## Important

- This is an early preview. Test in a controlled environment first.
- Use a dedicated non-root operating-system account.
- Keep the service on a trusted intranet or behind your own secure access layer.
- Verify the SHA-256 checksum before running the installer.
- Start with approval-required mode and review all mutations.

See the repository README, CHANGELOG, and SECURITY policy for details.
