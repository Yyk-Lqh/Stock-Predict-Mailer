# Security policy

English · [简体中文](#chinese) · [README](README.md)

## Supported scope

Security fixes target the current `main` branch and the current 0.5.x code line. Older snapshots are not maintained in parallel; reproduce against current code when practical. This is a local, single-user research tool. Bind services to loopback and do not expose them directly to the internet.

## Report a vulnerability

Do not post exploit details, credentials, private documents, or sensitive logs in public issues, discussions, or pull requests.

At the time of this policy refresh, GitHub private vulnerability reporting is **not enabled** for this repository, and no dedicated security email is published. Do not assume the advisory creation URL is a working private inbox. If a **Report a vulnerability** button becomes available in the [Security tab](https://github.com/Yyk-Lqh/Stock-Predict-Mailer/security), use that private channel. Otherwise, open a minimal [contact request](https://github.com/Yyk-Lqh/Stock-Predict-Mailer/issues/new/choose) asking the [maintainer](https://github.com/Yyk-Lqh) to provide a confidential channel. Include no vulnerability description, affected private identities, exploit, or secrets in that public request. Wait for a private channel before sending details.

Once a private channel is established, provide the affected commit/version and OS, minimal synthetic reproduction, expected/observed behavior, impact, and any mitigation. Redact real data and credentials. Coordinate disclosure with maintainers; this volunteer project has no guaranteed response or remediation SLA.

## Security boundaries

- Local session, Host/Origin and CSRF checks complement task/owner access controls; they do not turn the application into an internet multi-tenant service.
- Configuration secrets and retained document originals use encryption, but snippets, indexes, and some workspace outputs are plaintext. Protect the disk, backups, and keys separately.
- Models, MCP tools, A2A endpoints, and SMTP are configured trust boundaries. Remote transmission of private material requires the relevant explicit authorization.
- HTML/source text is untrusted. Path traversal, unsafe deserialization, cross-owner access, permission bypass, key leakage, and unintended sends or writes are reportable issues.
- Preserve immutable archive content, point-in-time checks, frozen mail and idempotency; never silently retry ambiguous delivery.
- GitHub secret scanning and push protection are not claimed as enabled. Contributors and maintainers must still inspect changes for secrets.

Poor forecast accuracy is not itself a vulnerability. A bypass of the documented security or data-integrity boundary can be, even if it involves a local research workflow. Do not test against other people's workspaces or publish private data to demonstrate impact.

<a id="chinese"></a>

## 简体中文

### 支持范围

安全修复面向当前 main 和 0.5.x 代码线，不并行维护旧快照。项目为本机单用户研究工具，服务只绑定回环地址，不直接暴露到公网。

### 报告安全问题

不要在公开 Issue、讨论或 PR 发布漏洞细节、凭据、私有文档和敏感日志。本次更新时，仓库**未启用 GitHub 私密漏洞报告**，也没有公布专用安全邮箱；不要把创建 advisory 的链接当作可用私密收件箱。

如果 [Security 页面](https://github.com/Yyk-Lqh/Stock-Predict-Mailer/security) 后续出现“Report a vulnerability”，使用该私密入口。否则，通过[最小联系请求](https://github.com/Yyk-Lqh/Stock-Predict-Mailer/issues/new/choose)请[维护者](https://github.com/Yyk-Lqh)提供私密渠道；公开请求不附漏洞描述、受影响私人身份、利用代码或密钥，等私密渠道确认后再发送细节。

私下提供版本/提交、系统、最小合成复现、预期与实际结果、影响和缓解方式，删除真实资料及凭据。与维护者协商披露；志愿项目不承诺响应或修复 SLA。

### 使用边界

本机会话、同源/CSRF 与 owner 权限不等于公网租户隔离；配置凭据和原件的加密不覆盖所有片段、索引及输出。分别保管磁盘、备份与密钥。模型、MCP/A2A 和 SMTP 是独立信任边界，远程传送私有资料需明确授权。

路径穿越、不安全反序列化、跨 owner 访问、权限绕过、密钥泄露和意外发送/写入均属报告范围。保留事前时点、不可覆盖档案、邮件冻结与幂等，不静默重试结果不确定的投递。不宣称仓库已启用 secret scanning 或 push protection，仍须人工检查变更。

预测不准确本身不是安全漏洞，但绕过已说明的数据完整性或权限门禁可能是。不要在他人的工作区验证，不公开真实数据作为证明。
