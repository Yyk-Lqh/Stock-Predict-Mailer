# 小马办公室真实任务进度 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 让小马电脑按后端最终执行计划、步骤完成事件和耗时展示真实任务进度；没有明确总量时不显示百分比。

**Architecture:** 后端在委派决策完成后发送一次 `finalized` 计划事件，其中列出基础步骤、实际子 Agent 步骤和可选汇总步骤。前端 `PonyTaskProgress.Tracker` 只按该事件建立百分比总量，并从真实 `step` 事件计算完成数；计划确定前和没有计划事件时只显示当前阶段与耗时。主小马显示全任务进度，专属 Agent 小马显示自己在最终计划中的步骤进度。

**Tech Stack:** Python 3.11 后端事件、浏览器端纯 JavaScript 模块、SVG 电脑屏幕、Node.js `node:test` 风格断言脚本。

**Spec:** 本对话中的“小马办公室”任务状态联动要求；当前验收记录见 `docs/pony-office-validation.md`。

## Global Constraints

- 进度总量和已完成步骤只能来自后端 `plan` 与 `step` 事件，不得从预算上限或动画帧推测。
- 后端动态决定委派角色后，必须在子任务启动前发送完整最终计划。
- 每个 step ID 在总量中只计一次；失败和取消步骤不计为完成。
- 空闲动画不得启动 Agent、模型或工具调用。
- `memory.js` 由 `scripts/build_console.py` 生成，不直接手工修改。

---

### Task 1: 后端最终计划事件与进度跟踪器

**Files:**
- Create: `src/stock_predict_mailer/control/web/modules/pony-progress.js`
- Create: `tests/test_pony_progress.cjs`
- Modify: `src/stock_predict_mailer/control/orchestrator.py`
- Modify: `scripts/build_console.py`

**Interfaces:**
- `new PonyTaskProgress.Tracker()` 提供 `reset()`、`update(event)` 和 `snapshot()`。
- `update(event)` 接受现有事件结构；只接受 `kind:'plan', finalized:true` 的计划作为总量，并接受 `kind:'step'` 的 running/completed/failed/canceled 状态。
- `snapshot()` 返回 `finalized`、`total`、`completed`、`percent` 和每个已计划 Agent 角色的计数。总量未定时 `percent` 为 `null`。
- 后端最终计划使用 `steps:[{id,label}]`，包括实际计划委派的角色及其 `merge` 汇总步骤。

- [x] **Step 1: 写 RED 回归用例**

```js
tracker.update({kind:'plan',finalized:false,steps:[{id:'validate'}]});
tracker.update({kind:'step',step:'validate',status:'completed'});
assert.equal(tracker.snapshot().percent,null); // 最终计划未定，不得假报百分比
tracker.update({kind:'plan',finalized:true,steps:[
  {id:'validate'},{id:'main'},{id:'risk'},{id:'merge'}
]});
assert.deepEqual(
  [tracker.snapshot().total,tracker.snapshot().completed,tracker.snapshot().percent],
  [4,1,25]
);
```

- [x] **Step 2: 运行 tracker、后端计划和屏幕 RED 用例；tracker 因模块缺失、后端因没有 final plan、屏幕因没有百分比输出而按预期失败。**
- [x] **Step 3: 实现 Tracker，按唯一 step ID 记录最终计划与已完成项；把计划事件生成放在后端委派决策之后、子 Agent 启动之前。**
- [x] **Step 4: 运行 Node 脚本并通过重复完成事件、角色进度、失败不计完成、reset 和无最终计划用例；后端复杂与简单任务的最终计划单测通过。**

### Task 2: 小马电脑显示真实进度

**Files:**
- Modify: `src/stock_predict_mailer/control/web/modules/pony-office.js`
- Modify: `src/stock_predict_mailer/control/web/modules/pony-screen.js`
- Modify: `scripts/build_console.py`
- Regenerate: `src/stock_predict_mailer/control/web/memory.js`
- Modify: `tests/browser_pony_lifecycle.js`

**Interfaces:**
- `PonyOffice.sync()` 把每个真实事件交给 Tracker，并将全局进度写到主 Agent、角色计数写到对应 Subagent 小马；每台显示器以 `data-office-role` 标记所属角色，验收读取屏幕实际 DOM 内容。
- `PonyScreen.render()` 在最终计划已知时显示 `完成/总数`、百分比和耗时进度条；计划未定时显示阶段、已完成步数与耗时，不显示百分比或填充进度条。

- [x] **Step 1: 扩展生命周期夹具，断言最终计划为 8 步且完成 1 步时主屏显示 13%，Subagent 屏显示该角色的 0/1。**
- [x] **Step 2: 以 `test_pony_games.cjs` 先验证屏幕任务进度行为；缺少实现时断言按预期失败。浏览器夹具本身因 gstack Chromium 缺失无法在真实浏览器运行。**
- [x] **Step 3: 集成 Tracker 与屏幕渲染；百分比只在 `finalized:true` 且总步数大于零时输出。**
- [x] **Step 4: 运行 Node Tracker、导航/生命周期/关节/小游戏测试和浏览器夹具语法检查；重建并检查 bundle。真实浏览器 DOM 验收仍受 Chromium 阻塞。**

### Task 3: 记录验收并交付

**Files:**
- Modify: `docs/pony-office-validation.md`
- Modify: `docs/superpowers/plans/2026-11-12-pony-task-progress.md`

- [x] 记录事件规则、测试结果和浏览器验收限制。
- [x] 运行 `git diff --check` 与完整相关 Node 测试。
- [ ] 将功能代码与验收文档分为两次提交，并按此前授权推送到 GitHub。

## Acceptance

- 计划尚未最终确定或后端未提供计划时，屏幕展示阶段和耗时但不显示百分比。
- 最终计划包含主流程、真实委派角色及汇总步骤；进度值严格由已完成的唯一 step ID 计算。
- 多次收到同一完成事件不会重复计数；失败、取消不能被算作完成。
- 主电脑显示全任务进度；Subagent 电脑显示对应角色进度；reset 后不残留上个任务的计数。
