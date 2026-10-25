## 这个 PR 做了什么

<!-- 一两句说明动机；关联 issue 用 "Closes #12" -->

## 变更类型

- [ ] 缺陷修复
- [ ] 新功能
- [ ] 文档
- [ ] 重构或测试（不改变行为）
- [ ] 破坏性变更（任务契约、模型格式、目录结构）

## 验证

- [ ] `uv run ruff check src tests scripts` 通过
- [ ] `uv run python -m compileall -q src tests` 通过
- [ ] `uv run python -m unittest discover -s tests -q` 通过（当前基线 50 项）
- [ ] `python scripts/check_repo_hygiene.py` 通过
- [ ] 新增或修改的行为有对应测试

## 边界自查

- [ ] 未提交真实行情、私有文档、模型包、签名私钥、运行数据库或日志
- [ ] 未引入 pickle 或其他任意反序列化推理路径
- [ ] 未绕过 `dataset_auth` 的平台训练授权门禁
- [ ] 未把 `principal` 当作登录身份，未把上传服务暴露到非回环地址
- [ ] 个人产物仍只写入 `registry/personal/<owner_key>/`
- [ ] 任务契约如有变动，已升 `schema_version` 而不是原地修改
- [ ] 未把成本诊断表述为可交易回测，未把 synthetic 结果表述为实盘结论

## 文档

- [ ] `CHANGELOG.md` 已更新（行为变化时）
- [ ] `docs/阶段验收记录.md` 已更新（新增验收口径或测试数量时）
- [ ] 相关专题文档与 README 命令/状态已同步
