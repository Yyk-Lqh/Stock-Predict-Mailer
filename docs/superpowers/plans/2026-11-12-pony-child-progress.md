# 小马办公室子任务返回状态联动计划

**Goal:** 子 Agent 的真实运行、完成、失败和取消事件都能及时更新对应小马，并让主小马准确显示仍在等待的子任务或已进入汇总阶段。

**Architecture:** 新增纯 JS `PonyChildren` 跟踪器，用角色 ID 维护当前任务的活动子任务映射。`PonyOffice.sync` 仍以现有后端事件为唯一状态来源；开始事件登记 childId，终态事件移除，主小马文案由剩余等待项派生。任务 reset 时清空跟踪器，不新增 API、模型调用或轮询。

**Files:** 新增 `pony-children.js` 和 `tests/test_pony_children.cjs`；修改 `pony-office.js`、`tests/browser_pony_lifecycle.js`、`scripts/build_console.py`、生成的 `memory.js` 和验收文档。

## Steps

- [x] 先写纯 tracker 回归，覆盖单个子任务完成、多个子任务部分完成、失败/取消、重复开始、无效角色和 reset；确认实现前失败。
- [x] 实现 childId 状态映射与主屏幕摘要，所有文案只由真实 step 事件推进。
- [x] 集成 `PonyOffice.sync`：孩子开始显示等待队列；仍有孩子时持续显示准确等待项；最后一个返回后显示汇总/失败/取消结果；主任务终态优先。
- [x] 扩展生命周期夹具，检查真实 DOM 中的主屏幕状态；并行任务中保留失败/取消反馈，直到 reset。
- [x] 重建 `memory.js`，运行 tracker、导航、生命周期、骨架、小游戏及 bundle/语法/diff 检查；更新验收文档。
- [ ] 使用 gstack `/browse` 执行本地事件演示；未完成：浏览器 daemon 缺少 `chromium_headless_shell-1208`，启动失败。未把 fixture 测试描述为浏览器验证。

## Acceptance

- 一个子任务运行时，主小马显示等待该角色；成功返回后及时切为汇总。
- 多个子任务并行时，一个返回后只移除其等待项，仍显示其余任务。
- 子任务失败或取消不会继续显示“等待返回”，并能区分结果。
- 主任务完成/失败/取消的最终反馈覆盖子任务摘要；reset 后不残留旧 childId 或等待项。

## 验收限制

tracker 回归、生命周期 DOM fixture、现有导航/动画仿真和 bundle 检查均已完成。gstack `/browse` 调用报告缺少 `chromium_headless_shell-1208`，未能运行本地事件演示或生成截图；真实浏览器视觉验收待运行时可用后补做。
