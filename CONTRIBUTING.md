# Contributing to QuickOps 快维

感谢你帮助改进 QuickOps。Thank you for helping improve QuickOps.

## 开始之前 / Before you start

- 对较大功能先创建 Issue，说明场景、安全边界和预期行为。
- For substantial changes, open an issue first and describe the use case, security boundary, and expected behavior.
- 不要在 Issue、PR、日志或测试数据中提交真实主机信息、凭据、API Key 或客户数据。
- Never submit real host information, credentials, API keys, or customer data in issues, pull requests, logs, or fixtures.

## Development workflow

```bash
npm ci
uv sync --dev
cp .env.example .env
npm run build
npm run test:sites
npm run test:backend
npm run lint:backend
```

Use a focused branch and keep pull requests small enough to review. Include tests for permission policy, HITL, authentication, persistence, terminal behavior, or provider adapters whenever those areas change.

## Commit and pull request guidance

- Explain what changed, why it changed, and how it was verified.
- Call out security or backward-compatibility impact explicitly.
- UI changes should include screenshots when practical.
- New dependencies must have a clear reason and compatible open-source license.

## License

By submitting a contribution, you agree that it is licensed under the Apache License 2.0.
