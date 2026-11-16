# Contributing to Stock-Predict-Mailer

English · [简体中文](#chinese) · [README](README.md)

Contributions are welcome through issues and pull requests. Start with a reproducible problem, the expected behavior, and a focused change. For sensitive reports follow [SECURITY.md](SECURITY.md); participation follows our [Code of Conduct](CODE_OF_CONDUCT.md).

## Set up a development environment

```shell
git clone https://github.com/Yyk-Lqh/Stock-Predict-Mailer.git
cd Stock-Predict-Mailer
uv sync --all-extras --locked
git switch -c codex/describe-your-change
```

External contributors can fork first. `codex/` is the default for agent-created branches; human feature/fix/docs branches are also welcome. Python 3.11+ is required. Node.js is needed for browser-script syntax and the existing `.cjs` checks. Modify dependency declarations with the corresponding lockfile update; do not edit the lockfile by hand.

## Validate your change

```shell
uv run ruff check src/stock_predict_mailer src/mcp_server tests scripts
uv run python -m compileall -q src tests scripts
uv run python -m unittest discover -s tests -v
uv run python scripts/build_schema_catalog.py --check
uv run python scripts/build_console.py --check
uv run python scripts/check_repo_hygiene.py
uv run python scripts/check_naming.py
node --check src/stock_predict_mailer/control/web/app.js
node --check src/stock_predict_mailer/control/web/memory.js
git diff --check
```

Run the relevant `tests/test_*.cjs` scripts when changing their browser modules. Edit `control/web/modules/*.js`, then run `uv run python scripts/build_console.py` to regenerate `memory.js`. Prefer a small regression that fails before a bug fix; documentation-only edits need links, examples, diagrams, and naming checked rather than invented behavior tests. Report optional-dependency or OS-privilege skips accurately. Current results belong to the exact CI run, not a permanent test-count promise.

## Preserve the project contracts

- Separate upstream facts from inferences, missing evidence, synthetic data, and investment uncertainty.
- Keep schemas strict, numbers finite, and point-in-time rules explicit. Preview must not silently become a write.
- Enforce task/owner permissions, tool allowlists, and budgets. A local principal is not an internet authentication system.
- Preserve frozen mail content, idempotency, endpoint binding, and explicit review of uncertain delivery.
- Do not bypass training authorization or load untrusted pickle artifacts. Keep optional research behavior separate from the default result-consumer flow.
- Use temporary workspaces and synthetic fixtures. Never commit live data, private documents, model weights, keys, databases, logs, or local configuration.
- Keep platform-native behavior covered on Linux and Windows; locks, paths, file replacement, and process cleanup differ.

## Naming and documentation

Use **Stock-Predict-Mailer** in prose, `stock-predict-mailer` for distribution/CLI, and `stock_predict_mailer` for imports. Environment variables begin with `STOCK_PREDICT_MAILER_`. The source of truth is [naming.py](src/stock_predict_mailer/naming.py).

Keep [README.md](README.md) and [README.zh-CN.md](README.zh-CN.md) aligned. Link detailed behavior to its manual. Update changelog/acceptance records when behavior changes; do not rewrite historical validation as if it described the present. For workflow assets, update both language diagrams and [their explanation](docs/runtime-flow.md).

## Pull requests and merge

1. Branch from current `main`; keep unrelated changes separate.
2. Use meaningful commits. Chinese summaries match this repository's current history; concise English summaries are also accepted.
3. Describe the trigger, resulting behavior, scope, and actual verification in the PR template.
4. Wait for the applicable checks. Maintainers should review before merging; repository protection settings remain the authoritative enforcement.
5. Do not bypass protected-branch requirements, force-push shared history, or claim local success proves every platform works.

By contributing, you agree to make your contribution available under the project's [MIT license](LICENSE), subject to retained third-party notices. No separate CLA is required by this guide.

<a id="chinese"></a>

## 简体中文

欢迎通过 Issue 和 PR 贡献。先说明可复现问题、预期行为与改动范围；敏感问题遵循[安全策略](SECURITY.md#chinese)，社区互动遵循[行为准则](CODE_OF_CONDUCT.md#chinese)。

### 环境与验证

按上方命令安装 `uv sync --all-extras --locked`，外部贡献者可先 Fork。Agent 分支默认使用 `codex/`；人工分支可用 feature/fix/docs。Python 需 3.11+，浏览器脚本检查需 Node.js。依赖声明变化时同步更新锁文件，不手工修改锁文件。

执行上方 lint、编译、unittest、结构目录、生成脚本、命名、仓库卫生及 diff 检查；改动对应浏览器模块时运行相关 `.cjs` 检查。编辑 `control/web/modules/*.js` 后重新生成 `memory.js`。修复应有能先复现失败的回归；纯文档改动检查链接、示例和图表即可。准确说明系统权限或可选依赖导致的跳过，不把某次测试数量当成永久基线。

### 行为边界

- 区分事实、推断、证据缺失、合成资料与投资不确定性，不捏造置信度。
- 保留严格 schema、有限数字及事前/可用时点校验，预览不得隐式写入。
- 不绕过任务/owner 权限、工具白名单、预算、训练授权和邮件不确定状态确认。
- 不加载不可信 pickle；默认预测消费入口与可选研究能力分开。
- 测试使用临时工作区和合成资料，不提交真实数据、私有文档、权重、密钥、数据库、日志或本地配置。
- 同时考虑 Linux/Windows 锁、路径、替换和进程回收差异。

### 命名、文档与合并

正文使用 **Stock-Predict-Mailer**，发行/CLI 为 `stock-predict-mailer`，导入为 `stock_predict_mailer`，环境变量以 `STOCK_PREDICT_MAILER_` 开头；以 naming.py 为准。同步中英文 README、相关手册和适用的变更/验收记录；历史记录保留当时语义，流程图需同步两种语言。

从最新 main 建分支，按有效范围提交，在 PR 说明问题、结果和实际验证。中文提交摘要沿用仓库习惯，也接受简洁英文。适用检查通过后由维护者审查合并，不绕过平台保护、不强推共享历史，不把本地通过等同于跨平台通过。

贡献按项目 [MIT 许可](LICENSE) 提供，保留第三方声明；本指南不要求额外 CLA。
