# 小马办公室空闲小游戏重构实施计划

> **For agentic workers:** 按此清单逐项实施，先写并运行针对性测试，再更新模块与生成 bundle。

**Goal:** 把四个循环像素画面和绘图动画改成可重复、规则一致、随空闲时钟连续推进的小型 SVG 场景。

**Architecture:** 在 `pony-screen.js` 内为每个小游戏提供纯函数模拟结果，以角色空闲时钟和稳定 seed 派生状态，不引入计时器、状态数据库或依赖。渲染器只消费这些结果；任务屏幕优先级、真实任务事件和 Subagent 启用规则保持不变。

**Tech Stack:** 原生 JavaScript、SVG、Node.js `node:test` 风格的 `assert`/`vm` 测试。

**Spec:** [小马办公室动画与任务联动设计](../../pony-office-animation-design.md)；范围对应其中“游戏/绘图为连续视觉动画、与键鼠动作配合、任务抢占后恢复”的屏幕约定。

## Global Constraints

- 遵循 `src/stock_predict_mailer/control/web/modules/pony-screen.js` 的现有单模块和自包含 SVG 字符串模式。
- `PonyScreen.render(actor, time, connected)` 保持向后兼容；`time` 继续供屏保和任务结果使用，闲置小游戏采用暂停的 `actor.idleClock`。
- 游戏不创建 Agent/Subagent、不发送网络请求、不注册定时器；场景结果为相同模式、时间与 seed 的纯确定性输出。
- 任务、断线及终态画面优先级不变；游戏切回由当前已保存的 `idleClock` 决定，不消耗任务期间的空闲时间。
- 生成 `memory.js` 必须使用 `scripts/build_console.py`，保持现有四资源 HTTP 契约。

---

### Task 1: 定义游戏规则的确定性回归

**Files:**
- Create: `tests/test_pony_games.cjs`
- Modify: `src/stock_predict_mailer/control/web/modules/pony-screen.js`

**Interfaces:**
- `PonyScreen.simulate(mode, elapsed, seed)` 返回 JSON 可序列化的纯场景对象：snake `{body, food, direction, score}`；mines `{width,height,mines,cells,revealed}`；tetris `{board,piece,score,phase}`；breakout `{ball,paddle,bricks,score}`；drawing `{points,stroke}`。
- 无效模式返回 `null`；`elapsed` 为负数时以零计算。

- [x] 写入用 Node `vm` 加载 `pony-screen.js` 的测试，覆盖确定性 seed、不同角色布局和跨多个采样时间的推进；首次运行在实现前按预期因 `simulate` 尚不存在而失败。
- [x] 验证贪吃蛇转角连续、只在吃到食物后增长计分且食物不重叠；扫雷数字正确、只揭安全格并逐步插旗；俄罗斯方块落块不重叠；打砖块反弹、计分和漏接重开；绘图轨迹增长并有上限。
- [x] 运行 `node tests/test_pony_games.cjs`，实现前确认测试失败，实现后通过。
- [x] 增加统一时间量化 helper 和四款小游戏/绘图的纯场景函数，运行测试至通过。

### Task 2: 用规则场景渲染显示器

**Files:**
- Modify: `src/stock_predict_mailer/control/web/modules/pony-screen.js`
- Modify: `tests/test_pony_games.cjs`

**Interfaces:**
- `render` 计算所选空闲游戏的本地播放时间 `actor.idleClock % 33`，调用 `simulate(mode, localTime, actor.seed)`。
- 每个画面保持 96×58 的屏幕范围，标题与关键元素使用现有 `rect`/`text` helper 和角色配色。

- [x] 逐个模式渲染模拟对象，保留蛇节/食物、扫雷未开格/旗标/数量、掉落方块/固定格、打砖球/球拍/砖块、绘图轨迹。
- [x] 测试五种空闲画面模式、`task`/`disconnected`/`result` 优先级和完成/失败/取消的结果标签。
- [x] 屏幕文本沿用统一 `escape` helper；对所有场景采样验证关键图元保持在 96×58 屏幕区域。
- [x] 运行 `node tests/test_pony_games.cjs`、`node tests/test_pony_rig.cjs`、`node tests/test_pony_lifecycle.cjs`。

### Task 3: 更新 bundle 并浏览器验收

**Files:**
- Modify: `src/stock_predict_mailer/control/web/memory.js`（生成）
- Modify: `docs/pony-office-validation.md`

- [x] 执行 `python scripts/build_console.py`，随后执行 `python scripts/build_console.py --check` 和 `node --check src/stock_predict_mailer/control/web/memory.js`。
- [ ] 使用 gstack browse 检查五种游戏的实际屏幕截图和游戏/任务画面抢占；**受环境阻塞**：gstack Playwright 找不到 `chromium_headless_shell-1208`。尝试指定系统 Chrome 后仍由隔离浏览器进程解析到缺失的 Playwright Chromium；未伪称浏览器验收通过。
- [x] 更新验收记录，分别记录自动化场景验证与实际浏览器验证状态，并说明剩余限制。
- [x] 运行 `node tests/test_pony_games.cjs`、`node tests/test_pony_rig.cjs`、`node tests/test_pony_lifecycle.cjs`、`python scripts/build_console.py --check`、`git diff --check`。
