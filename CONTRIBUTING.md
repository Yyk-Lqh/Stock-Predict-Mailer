# 参与贡献

本项目采用 **公开仓库 + fork / Pull Request** 的协作方式。任何人都可以 fork、修改并提交 PR；合并由维护者执行。若你希望**不经过他人审核直接合并**，需要被授予 Write 权限（见文末"权限与合并"）。

提交前请先读 [README](README.md) 与 [阶段验收记录](docs/阶段验收记录.md)，本项目对"能不能宣称完成"有严格口径。

## 1 环境准备

```powershell
git clone https://github.com/Yyk-Lqh/Stock-Predict-Mailer.git
cd Stock-Predict-Mailer
uv sync --extra trees --extra dev
```

- Python 3.11+，依赖由 `uv.lock` 锁定，请勿手工改 `uv.lock` 以外的版本号。
- `--extra trees` 用来跑 LightGBM 相关测试。不装也能跑，但那部分测试会 skip，等于降低覆盖，PR 前请装。
- 不想装在主环境时，也可以用 `uvx ruff@0.17.2` 单独调 lint。

## 2 提交前必须通过的检查

```powershell
uv run ruff check src tests scripts
uv run python -m compileall -q src tests
uv run python -m unittest discover -s tests -q
python scripts/check_repo_hygiene.py
```

- 测试用标准库 **unittest**，项目没有 pytest 配置，请不要引入第二套测试框架。
- 当前基线为 **50 项测试通过**，耗时约 40 秒。新增行为必须配测试；修 bug 请先补一个能复现的用例。
- CI 在 `ubuntu-latest` 与 `windows-latest`、Python 3.11 与 3.13 上跑同一套测试。只在本机通过的改动不算通过——Windows 的文件替换、时区与路径行为都与 Linux 不同。

## 3 流程

1. Fork，并从 `main` 切分支：`feature/<主题>`、`fix/<问题>`、`docs/<主题>`。
2. 小步提交，提交信息沿用仓库风格：`feat:` / `fix:` / `docs:` / `chore:` + 中文正文（可用多行列表说明动机与影响）。
3. 推送后开 PR，填写模板中的检查项。
4. CI 变绿 + 至少 1 次 review 通过后再合并；合并方式用 **Squash** 或 **Rebase**，保持 `main` 线性历史。

## 4 代码约定

这些不是风格偏好，而是项目已验收的行为契约，改动前请先开 issue 讨论：

- **不使用 pickle 推理路径**。正式模型只走原生 JSON（线性模型）与 LightGBM 原生文本；新增算法必须提供等价的原生序列化格式。
- **任务契约是破坏性变更**。`contract_id` 由契约内容哈希得出，改特征顺序、股票池、标签周期或基准都会换 ID 并使旧模型不兼容。只能升 `schema_version`，不要原地改。
- **不要把 `principal` 当认证**。它是本机受信配置；上传服务只监听 `127.0.0.1`。若要让多人共用，必须引入真正的身份与会话层，而不是"让用户填 owner"。
- **平台训练授权不可绕过**。用户上传数据默认 `platform_training=false`；不要为了调试方便删掉 `dataset_auth` 的门禁，也不要让上传页面获得训练或模型执行入口。
- **个人产物只写 owner 命名空间**（`registry/personal/<owner_key>/`），平台目录 `registry/versions/` 不接受个人写入。
- **失败不得静默**：训练失败、取消、超时需要保留可解释的错误类别，且不得改写当前选择或覆盖旧版本。
- **成本诊断不是可交易回测**，报告与文档中不要升级表述。

## 5 文档同步要求

改动行为、命令、门禁或范围时，同一个 PR 内必须同步：

- `CHANGELOG.md`（按版本归组）；
- `docs/阶段验收记录.md`（新增/变化的验收口径与测试数量）；
- 相关专题文档（如 `docs/平台模型命令与验收.md`）；
- `README.md` 中受影响的命令或状态表。

只改代码不改文档的 PR 会被要求补充。

## 6 数据、密钥与隐私

- 真实行情、私有文档、模型包、签名私钥、运行数据库与日志**一律不进仓库**，`.gitignore` 已排除，但 PR 仍可能误带，CI 的 `check_repo_hygiene.py` 会拦截。
- 测试只能用合成数据（`demo-data`）或临时目录生成的数据，不要在测试里引用本地真实文件路径。
- 发现密钥泄露请按 [SECURITY.md](SECURITY.md) 走私密渠道，不要开公开 issue。

## 7 权限与合并

| 角色 | 能做 | 怎么获得 |
| --- | --- | --- |
| 外部贡献者 | fork、提 PR、评论 | 无需申请 |
| 协作者（Write） | 直接推分支、自行合并 PR（CI 必须绿） | 维护者邀请，通常先有 1–2 个被合并的 PR |
| 维护者（Admin） | 合并、发布 tag、调整规则 | 仓库所有方 |

`main` 分支由 Ruleset 保护：禁止直推、必须 PR、必须 CI 通过。即使有 Write 权限也不能绕过检查直接推 `main`。

## 8 行为准则

参与即表示同意 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。技术分歧请围绕可复现证据讨论，不要针对个人。
