/* ===== Office：办公区视图 =====
 *
 * 它不是第二个模拟器——事件全部来自 app.js 里那一次真实的运行队列
 * （与 /api/tasks/{id}/events 同形），这里只负责把事件翻译成「谁在做什么」：
 *
 *   begin(run)   运行开始：看板按 run.steps 重建阶段点，小鲸开始打字
 *   apply(item)  收到一条事件：小鱼走位 / 出图台 / 邮筒 / 状态灯 / 屏幕进度
 *   finish(fail) 运行结束：停打字、小鱼回待命区、屏幕落完成态
 *   reset()      清场
 *
 * 两台电脑、两个人：小鲸常驻 P1 负责规划与汇总，小鱼在 P2 做分支分析，
 * 没有分支任务时就待在待命区。所有进度都由同一份 done/total 推导，
 * 顶部看板、两块工位屏幕、铭牌进度条永远说的是同一个数。
 */
window.Office = (function () {
  "use strict";

  var NS = "http://www.w3.org/2000/svg";
  var SEAT_Y = 740;
  var scene = window.Scene;

  var mounted = false;
  var actors = null;
  var instant = false;
  var timers = [];
  var running = false;
  var startedAt = 0;
  var tickTimer = null;

  var order = ["main", "sub"];
  var actorLog = { main: [], sub: [] };
  var STEP_LABEL = {};

  /* 三个分支步骤都归小鱼；其余（规划 / 补数 / 分析 / 汇总 / 出图 / 投递）归小鲸 */
  var SUB_STEPS = { prediction: 1, risk: 1, advice: 1 };

  /* ---- 进度 ---- */
  var total = 0;
  var done = 0;
  var active = false;

  var STATUS_CN = {
    idle: "待命", dispatched: "已派发", queued: "排队中", walking: "前往工位",
    working: "工作中", thinking: "思考中", reviewing: "复核中",
    done: "已完成", degraded: "部分结果", failed: "失败"
  };

  var SCREEN_TEXT = {
    idle: "待命", walking: "入场中", working: "分析中",
    reviewing: "汇总中", done: "已完成", degraded: "部分结果", failed: "失败"
  };

  /* 看板上的短标签 */
  var SHORT = {
    plan: "规划", context: "补数", prediction: "预测", risk: "风险",
    advice: "建议", analysis: "分析", merge: "汇总", charts: "出图",
    summary: "汇总", report: "成文", mail: "投递"
  };

  var DIR_CN = { up: "上涨", down: "下跌", flat: "持平" };

  function $(id) { return document.getElementById(id); }

  function el(tag, attrs, kids) {
    var node = document.createElementNS(NS, tag);
    if (attrs) for (var k in attrs) if (attrs[k] !== null && attrs[k] !== undefined) node.setAttribute(k, attrs[k]);
    if (kids) for (var i = 0; i < kids.length; i++) if (kids[i]) node.appendChild(kids[i]);
    return node;
  }

  /* ---------- 进度 ---------- */

  function pctOf() {
    if (!total) return 0;
    return Math.round(((done + (active ? 0.45 : 0)) / total) * 100);
  }

  function paintProgress() {
    var pct = pctOf();
    scene.boardProgress(pct);
    scene.deskBar("main", pct);
    scene.deskBar("sub", pct);
    scene.screen("main", pct, SCREEN_TEXT[actors.main.status] || "待命",
      toneOf(actors.main.status));
    scene.screen("sub", pct, SCREEN_TEXT[actors.sub.status] || "待命",
      toneOf(actors.sub.status));
  }

  function toneOf(status) {
    if (status === "failed") return "danger";
    if (status === "degraded") return "warn";
    if (status === "done") return "ok";
    if (status === "working" || status === "reviewing") return "running";
    return "idle";
  }

  /* ---------- 气泡 ---------- */

  var bubbleTimer = {};

  function say(key, text, tone) {
    var actor = actors[key];
    if (!actor) return;
    var old = actor.node.querySelector(".bubble");
    if (old) old.parentNode.removeChild(old);
    if (bubbleTimer[key]) clearTimeout(bubbleTimer[key]);
    if (!text) return;
    var w = Math.max(62, text.length * 13.5 + 20);
    var g = el("g", { class: "bubble tone-" + (tone || "info") }, [
      el("rect", { x: -w / 2, y: -394, width: w, height: 28, rx: 14, class: "bubble-bg" }),
      el("path", { d: "M-6,-366 L0,-356 L6,-366 Z", class: "bubble-tail" })
    ]);
    var label = el("text", { x: 0, y: -375, "text-anchor": "middle", class: "bubble-text" });
    label.textContent = text;
    g.appendChild(label);
    actor.node.appendChild(g);
    bubbleTimer[key] = setTimeout(function () {
      if (g.parentNode) g.parentNode.removeChild(g);
    }, 2600);
  }

  /* ---------- 走位 ---------- */

  function statusOf(key, status) {
    scene.setStatus(actors[key], status);
    paintProgress();
  }

  function goDesk(key, done2) {
    var seat = scene.seatOf(key);
    scene.setSeatLabel(key);
    statusOf(key, "walking");
    say(key, "前往 " + seat.code + " 协作位", "accent");
    scene.walk(actors[key], seat.x, SEAT_Y, instant ? 0 : 1500, function () {
      /* 走位期间可能已经完成（快节奏队列），别把已完成又翻回工作中 */
      if (actors[key].status === "walking" || actors[key].status === "queued") statusOf(key, "working");
      scene.setTyping(actors[key], running);
      say(key, "", null);
      if (done2) done2();
    }, scene.SCALE);
  }

  function goLounge(key, after) {
    var target = scene.LAYOUT.lounge[key];
    var y = scene.LAYOUT.loungeY[key] || SEAT_Y;
    scene.setTyping(actors[key], false);
    scene.walk(actors[key], target, y, instant ? 0 : 1500, function () {
      statusOf(key, "idle");
      say(key, "", null);
      if (after) after();
    }, scene.LOUNGE_SCALE, false);
  }

  /* ---------- 协作位：只有小鱼会用 P2 ---------- */

  var subSeated = false;

  function summonSub() {
    if (subSeated) return;
    subSeated = true;
    goDesk("sub");
  }

  function dismissSub() {
    subSeated = false;
  }

  /* ---------- 出图台 ---------- */

  function plotter(state) {
    scene.parts.plotter.node.setAttribute("data-run",
      state === "generating" ? "1" : state === "done" ? "done" : "0");
  }

  /* ---------- 邮筒 ---------- */

  var MAIL_TEXT = {
    submitted: "已提交", uncertain: "结果未知", retry: "待重试",
    simulated: "模拟投递", skipped: "未投递", failed: "投递失败"
  };
  var MAIL_ICON = { submitted: "✓", uncertain: "?", retry: "↻", simulated: "◇", skipped: "–", failed: "✕" };

  function mailState(state, code) {
    var box = scene.parts.mailbox;
    box.node.setAttribute("data-mail", state || "idle");
    if (state === "sending" || !state) {
      box.badge.setAttribute("opacity", "0");
      box.badgeText.textContent = "";
      return;
    }
    box.badge.setAttribute("data-tone", state);
    box.badgeText.textContent = (MAIL_ICON[state] || "•") + " " + (MAIL_TEXT[state] || state) + (code ? " · " + code : "");
    box.badge.setAttribute("opacity", "1");
  }

  function flyEnvelope() {
    var svg = $("office-scene");
    var from = { x: scene.LAYOUT.seats.main.x, y: 600 };
    var to = { x: scene.LAYOUT.mailbox, y: 650 };
    var ctrl = { x: (from.x + to.x) / 2, y: 470 };
    var env = el("g", { class: "envelope" }, [
      el("rect", { x: -11, y: -7, width: 22, height: 14, rx: 1.5, class: "envelope-body" }),
      el("path", { d: "M-11,-7 L0,1 L11,-7", class: "envelope-fold" })
    ]);
    svg.appendChild(env);
    var start = performance.now(), DUR = 1100;
    (function frame(now) {
      var k = Math.min(1, (now - start) / DUR);
      var e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
      var x = (1 - e) * (1 - e) * from.x + 2 * (1 - e) * e * ctrl.x + e * e * to.x;
      var y = (1 - e) * (1 - e) * from.y + 2 * (1 - e) * e * ctrl.y + e * e * to.y;
      env.setAttribute("transform", "translate(" + x + "," + y + ") rotate(" + e * -8 + ")");
      if (k < 1) requestAnimationFrame(frame);
      else if (env.parentNode) env.parentNode.removeChild(env);
    })(performance.now());
  }

  /* ---------- 事件日志 ---------- */

  function nowClock() {
    var d = new Date();
    return [d.getHours(), d.getMinutes(), d.getSeconds()].map(function (n) {
      return (n < 10 ? "0" : "") + n;
    }).join(":");
  }

  function textOf(ev) {
    if (ev.label) return ev.label;
    if (ev.kind === "step") {
      var name = STEP_LABEL[ev.step] || ev.step;
      if (ev.status === "running") return name + " 开始";
      if (ev.status === "completed") return name + " 完成" + (ev.note ? " · " + ev.note : "");
      return name + " " + (STATUS_CN[ev.status] || ev.status) + (ev.note ? " · " + ev.note : "");
    }
    return ev.kind + " " + (ev.step || "");
  }

  function log(ev) {
    var list = $("office-log");
    if (!list) return;
    var empty = list.querySelector(".log-empty");
    if (empty) empty.parentNode.removeChild(empty);
    var row = document.createElement("li");
    row.className = "log-row";
    var clock = document.createElement("span");
    clock.className = "log-time";
    clock.textContent = ev.timestamp || "";
    var body = document.createElement("span");
    body.className = "log-body";
    body.textContent = textOf(ev);
    row.appendChild(clock);
    row.appendChild(body);
    row.setAttribute("data-tone", ev.status === "failed" ? "danger" : ev.kind === "step" ? "step" : "mute");
    list.appendChild(row);
    list.scrollTop = list.scrollHeight;
    while (list.children.length > 60) list.removeChild(list.firstChild);
  }

  /* ---------- 应用事件 ---------- */

  function ownerOf(ev) {
    if (ev.kind !== "step") return null;
    return SUB_STEPS[ev.step] ? "sub" : "main";
  }

  function applyEvent(ev) {
    ev.timestamp = ev.timestamp || nowClock();
    log(ev);
    var owner = ownerOf(ev);
    if (owner) {
      actorLog[owner].push(ev);
      while (actorLog[owner].length > 6) actorLog[owner].shift();
    }

    if (ev.kind === "event") {
      say("main", ev.label, ev.status === "failed" ? "danger" : "info");
      return;
    }
    if (ev.kind !== "step") return;

    var id = ev.step;
    var tone = ev.status === "failed" ? "danger" : ev.status === "degraded" ? "warn" : "ok";

    /* 进度：完成与部分完成才算翻页；失败不计入，运行中记半格 */
    if (ev.status === "running") {
      active = true;
    } else {
      active = false;
      if (ev.status !== "failed") done = Math.min(total, done + 1);
    }

    /* ---- 小鱼：分支分析 ---- */
    if (SUB_STEPS[id]) {
      if (ev.status === "running") {
        summonSub();
      } else {
        var ok = ev.status === "completed";
        statusOf("sub", ok ? "done" : "degraded");
        say("sub", ok ? "已完成" + (ev.note ? " · " + ev.note : "") : (ev.note || "部分结果"), tone);
      }
      scene.boardStage(id, ev.status);
      paintProgress();
      return;
    }

    /* ---- 出图 ---- */
    if (id === "charts") {
      if (ev.status === "running") plotter("generating");
      else if (ev.status === "completed") plotter("done");
      scene.boardStage(id, ev.status);
      paintProgress();
      return;
    }

    /* ---- 投递 ---- */
    if (id === "mail") {
      if (ev.status === "running") {
        mailState("sending");
        flyEnvelope();
      } else if (ev.status === "completed" || ev.status === "degraded") {
        mailState(ev.note || "submitted");
        say("main", "报告已交付 · " + (MAIL_TEXT[ev.note] || ev.note || ""), ev.note === "failed" ? "danger" : "ok");
      } else {
        mailState("failed", ev.note);
      }
      scene.boardStage(id, ev.status);
      paintProgress();
      return;
    }

    /* ---- 小鲸主导的阶段 ---- */
    scene.boardStage(id, ev.status);
    if (ev.status === "running") {
      if (actors.main.status !== "reviewing") statusOf("main", "working");
      if (id === "plan") say("main", "接到任务，开始规划", "info");
      paintProgress();
      return;
    }

    if (ev.status === "failed") {
      statusOf("main", "failed");
      say("main", ev.note || "失败", "danger");
      paintProgress();
      return;
    }

    if (id === "plan") {
      say("main", ev.note || "计划已生成", "info");
    } else if (id === "context") {
      say("main", ev.note || "上下文已就绪", "info");
    } else if (id === "summary") {
      statusOf("main", "reviewing");
      say("main", ev.note || "复核分支结果", "info");
    } else if (id === "analysis") {
      statusOf("main", "working");
    }
    paintProgress();
  }

  /* 统一入口：先落状态，再刷新抽屉 */
  function apply(item) {
    if (!mounted || !item) return;
    var ev;
    if (item.event) {
      ev = { kind: "event", label: item.event, status: item.status };
    } else if (item.step) {
      ev = { kind: "step", step: item.step, status: item.status, note: item.note };
    } else {
      return;
    }
    applyEvent(ev);
    if (openKey && actors[openKey]) renderDrawer(openKey);
  }

  /* ---------- 运行控制 ---------- */

  function statusText(text, tone) {
    var node = $("office-status");
    if (!node) return;
    node.textContent = text;
    node.setAttribute("data-tone", tone || "idle");
  }

  function reset() {
    if (!mounted) return;
    timers.forEach(clearTimeout);
    timers = [];
    if (tickTimer) clearInterval(tickTimer);
    tickTimer = null;
    running = false;
    subSeated = false;
    total = 0; done = 0; active = false;
    Object.keys(bubbleTimer).forEach(function (k) { clearTimeout(bubbleTimer[k]); });

    order.forEach(function (key) {
      var a = actors[key];
      a.node.classList.remove("is-walking");
      scene.setTyping(a, false);
      a.layer = "walk";
      $("office-scene").querySelector(".layer-actors-walk").appendChild(a.node);
      var atSeat = key === "main";
      scene.place(a, atSeat ? scene.LAYOUT.seats.main.x : scene.LAYOUT.lounge[key],
        atSeat ? SEAT_Y : scene.LAYOUT.loungeY[key],
        atSeat ? scene.SCALE : scene.LOUNGE_SCALE);
      a.scale = atSeat ? scene.SCALE : scene.LOUNGE_SCALE;
      if (window.Actors.setPose) window.Actors.setPose(a.node, atSeat ? "sit" : "stand");
      if (atSeat) scene.settle(key);
      statusOf(key, "idle");
      var b = a.node.querySelector(".bubble");
      if (b) b.parentNode.removeChild(b);
      if (a.tag) a.tag.node.setAttribute("opacity", atSeat ? "0" : "1");
    });
    scene.resetSeatLabel();
    scene.deskBar("main", 0);
    scene.deskBar("sub", 0);
    scene.screen("main", 0, "待命", "idle");
    scene.screen("sub", 0, "待命", "idle");

    scene.setStages(scene.STAGES);
    scene.STAGES.forEach(function (s) { scene.boardStage(s.id, "pending"); });
    scene.boardHead("等待任务", "小鲸常驻 P1，小鱼在 P2 与待命区之间往返");
    scene.boardProgress(0);
    scene.boardTag(false);
    scene.boardFooter("已用 00:00  ·  预算 $0.000");
    plotter("idle");
    mailState(null);
    var list = $("office-log");
    if (list) {
      list.replaceChildren();
      var hint = document.createElement("li");
      hint.className = "log-empty";
      hint.textContent = "尚无执行事件。点「开始分析」，或去分析台提交一次。";
      list.appendChild(hint);
    }
    order.forEach(function (k) { actorLog[k] = []; });
    STEP_LABEL = {};
    statusText("待命", "idle");
    if (openKey) renderDrawer(openKey);
  }

  function fmt(ms) {
    var s = Math.floor(ms / 1000);
    return ("0" + Math.floor(s / 60)).slice(-2) + ":" + ("0" + (s % 60)).slice(-2);
  }

  function begin(run) {
    reset();
    if (!run) return;
    running = true;
    startedAt = performance.now();

    total = run.steps.length;
    done = 0;
    active = false;

    STEP_LABEL = {};
    run.steps.forEach(function (s) { STEP_LABEL[s.id] = s.label; });
    scene.setStages(run.steps.map(function (s) {
      return { id: s.id, short: SHORT[s.id] || s.label };
    }));
    run.steps.forEach(function (s) { scene.boardStage(s.id, "pending"); });

    var input = run.input || {};
    var UNIT_CN = { trading_days: "交易日", calendar_days: "自然日", hours: "小时" };
    var amount = input.horizonValue || 5;
    var unit = input.horizonUnit || "trading_days";
    var horizon = unit === "trading_days" ? "T+" + amount : amount + " " + (UNIT_CN[unit] || unit);
    scene.boardHead(
      (input.subject || "DEMO.SZ") + "  ·  " + (DIR_CN[input.direction] || "方向未定") + "  ·  " + horizon,
      run.scenario && run.scenario.name ? run.scenario.name : "运行中"
    );
    scene.boardTag(true);

    statusText("执行中", "running");
    statusOf("main", "working");
    scene.setTyping(actors.main, true);
    say("main", "开始分析", "accent");
    paintProgress();

    tickTimer = setInterval(function () {
      if (!running) return;
      var ms = performance.now() - startedAt;
      scene.boardFooter("已用 " + fmt(ms) + "  ·  预算 $" + (ms / 1000 * 0.0024).toFixed(3));
    }, 500);
  }

  function finish(info) {
    if (!mounted) return;
    var failed = !!(info && info.failed);
    var cancelled = !!(info && info.cancelled);
    running = false;
    active = false;
    if (tickTimer) clearInterval(tickTimer);
    tickTimer = null;
    /* 收场：先作废还挂着的定时器，避免晚到的 goDesk 又把人送到工位 */
    timers.forEach(clearTimeout);
    timers = [];
    statusText(cancelled ? "已取消" : failed ? "任务失败" : "已完成",
      cancelled ? "idle" : failed ? "danger" : "ok");

    /* 打字同步停：手回到静止坐姿 */
    scene.setTyping(actors.main, false);
    scene.setTyping(actors.sub, false);

    if (!failed && !cancelled) { done = total; }
    scene.boardProgress(failed || cancelled ? pctOf() : 100);

    if (failed) {
      statusOf("main", "failed");
      say("main", "任务终止", "danger");
    } else if (cancelled) {
      statusOf("main", "idle");
      say("main", "已取消，不撤回已产生的外部效果", "warn");
    } else {
      statusOf("main", "done");
      say("main", "本轮结束", "ok");
    }

    scene.resetSeatLabel();

    if (subSeated) {
      /* 小鱼回待命区；走回去之后再清协作位标记 */
      setTimeout(function () {
        if (running) return;
        scene.cancelWalk(actors.sub);
        goLounge("sub", dismissSub);
      }, 900);
    } else {
      statusOf("sub", "idle");
    }

    if (!failed && !cancelled) {
      setTimeout(function () { if (!running) scene.boardFooter("已完成  ·  报告见分析台"); }, 600);
    }
    paintProgress();
  }

  /* ---------- 抽屉 ---------- */

  var openKey = null;

  function openDrawer(key) {
    openKey = key;
    renderDrawer(key);
    var drawer = $("office-drawer");
    drawer.hidden = false;
    drawer.querySelector(".drawer-close").focus();
  }

  function renderDrawer(key) {
    var v = window.Actors.VARIANTS[key];
    var seat = scene.seatOf(key);
    var a = actors[key];
    var drawer = $("office-drawer");
    if (!drawer || !a) return;
    drawer.querySelector(".drawer-num").textContent = seat.code;
    drawer.querySelector(".drawer-name").textContent = v.name;
    drawer.querySelector(".drawer-role").textContent = v.role + " · " + v.code;
    var pills = drawer.querySelector(".drawer-status");
    pills.textContent = STATUS_CN[a.status] || a.status;
    pills.setAttribute("data-status", a.status);
    drawer.querySelector(".drawer-avatar").replaceChildren(window.Actors.avatar(key, 56));
    var rows = drawer.querySelector(".drawer-events");
    rows.replaceChildren();
    var recent = actorLog[key].slice(-4);
    if (!recent.length) {
      var empty = document.createElement("li");
      empty.className = "drawer-empty";
      empty.textContent = "尚无该角色的执行记录";
      rows.appendChild(empty);
    } else {
      recent.forEach(function (ev) {
        var row = document.createElement("li");
        row.className = "log-row";
        row.setAttribute("data-tone", ev.status === "failed" ? "danger" : "step");
        var clock = document.createElement("span");
        clock.className = "log-time";
        clock.textContent = ev.timestamp || "";
        var body = document.createElement("span");
        body.className = "log-body";
        body.textContent = textOf(ev);
        row.appendChild(clock);
        row.appendChild(body);
        rows.appendChild(row);
      });
    }
  }

  function closeDrawer() {
    openKey = null;
    var drawer = $("office-drawer");
    if (drawer) drawer.hidden = true;
  }

  /* ---------- 挂载 ---------- */

  function mount() {
    if (mounted) return;
    var svg = $("office-scene");
    if (!svg) return;
    var built = scene.mount(svg);
    actors = built.actors;
    mounted = true;

    order.forEach(function (key) {
      var node = actors[key].node;
      node.setAttribute("role", "button");
      node.setAttribute("aria-label", window.Actors.VARIANTS[key].name + "，" +
        window.Actors.VARIANTS[key].role + "，工位 " + scene.seatOf(key).code);
      node.addEventListener("click", function () { openDrawer(key); });
      node.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          openDrawer(key);
        }
      });
    });

    var close = $("office-drawer").querySelector(".drawer-close");
    close.addEventListener("click", closeDrawer);
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeDrawer();
    });

    instant = /(^|[?&])instant=1/.test(location.search);
    reset();

    var q = new URLSearchParams(location.search);
    if (q.get("open") && actors[q.get("open")]) setTimeout(function () { openDrawer(q.get("open")); }, 200);
  }

  return {
    mount: mount, begin: begin, apply: apply, finish: finish, reset: reset,
    isMounted: function () { return mounted; }
  };
})();
