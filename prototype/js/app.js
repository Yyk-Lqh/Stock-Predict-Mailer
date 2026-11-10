(function () {
  "use strict";

  var R = window.StockPredictMailerRender;
  var M = window.StockPredictMailerMock;
  var $ = function (id) { return document.getElementById(id); };
  var pad = function (n) { return String(n).padStart(2, "0"); };

  var state = {
    scenario: "ok",
    running: false,
    ticker: null,
    task: null,
    runView: null,
    direction: "up"
  };

  var STATUS_TEXT = { running: "开始", completed: "完成", failed: "失败", degraded: "降级" };

  /* 运行事件对外的出口：办公区、后续的看板都从这里订阅，避免各自再模拟一遍。
   * 事件沿用 /api/tasks/{id}/events 的语义：step / event 两类。 */
  var listeners = {};

  function emit(name, payload) {
    (listeners[name] || []).forEach(function (fn) {
      try {
        fn(payload);
      } catch (error) {
        if (window.console) console.error(error);
      }
    });
  }

  function setControls(running) {
    $("submit-btn").disabled = running;
    $("cancel-btn").hidden = !running;
    var start = $("office-start");
    if (start) {
      start.disabled = running;
      start.textContent = running ? "执行中…" : "开始分析";
    }
  }

  function dtLocal(date) {
    return (
      date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate()) +
      "T" + pad(date.getHours()) + ":" + pad(date.getMinutes())
    );
  }

  function fromLocal(value) {
    if (!value) return null;
    var date = new Date(value);
    return isNaN(date.getTime()) ? null : date.toISOString();
  }

  function factBlock(fact) {
    var block = R.h("div", "fact-block");
    block.dataset.factId = fact.id;

    var head = R.h("div", "fact-block-head");
    var tag = R.h("span", "tag", fact.id);
    head.appendChild(tag);
    var remove = R.h("button", null, "删除");
    remove.type = "button";
    remove.addEventListener("click", function () {
      block.remove();
      renumber();
    });
    head.appendChild(remove);
    block.appendChild(head);

    var grid = R.h("div", "fact-grid");

    function field(key, label, options) {
      options = options || {};
      var wrapper = R.h("label", options.wide ? "span-2" : null, label);
      var input = document.createElement("input");
      var raw = fact[key];
      if (raw && /_at$/.test(key) && typeof raw === "string") raw = raw.slice(0, 16);
      input.value = raw === undefined || raw === null ? "" : raw;
      input.dataset.key = key;
      if (options.number) {
        input.type = "number";
        input.step = "any";
      }
      wrapper.appendChild(input);
      grid.appendChild(wrapper);
      return input;
    }

    field("name", "名称", { wide: true });
    field("value", "数值", { number: true });
    field("unit", "单位");
    field("source", "来源", { wide: true });
    field("observed_at", "观测时间（ISO）");
    field("available_at", "可用时间（ISO）");

    block.appendChild(grid);
    return block;
  }

  function renumber() {
    Array.prototype.forEach.call($("facts").querySelectorAll(".fact-block"), function (block, index) {
      var id = "F-" + pad(index + 1);
      block.dataset.factId = id;
      block.querySelector(".tag").textContent = id;
    });
  }

  function renderFacts(facts) {
    var host = $("facts");
    host.replaceChildren();
    facts.forEach(function (fact) { host.appendChild(factBlock(fact)); });
  }

  function readFacts() {
    return Array.prototype.map.call($("facts").querySelectorAll(".fact-block"), function (block, index) {
      var fact = { id: block.dataset.factId || "F-" + pad(index + 1) };
      Array.prototype.forEach.call(block.querySelectorAll("input[data-key]"), function (input) {
        var value = input.value.trim();
        if (/_at$/.test(input.dataset.key) && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) {
          value = new Date(value).toISOString();
        }
        fact[input.dataset.key] = value;
      });
      return fact;
    });
  }

  function readInput() {
    var confidence = $("f-confidence").value;
    var facts = readFacts();
    return {
      subject: $("f-subject").value.trim() || "DEMO.SZ",
      modelVersion: $("f-model").value.trim() || "mock-v1",
      direction: state.direction,
      horizonValue: Number($("f-horizon").value) || 5,
      horizonUnit: $("f-horizon-unit").value,
      confidence: confidence === "" ? null : Number(confidence),
      generatedAt: fromLocal($("f-generated").value),
      validUntil: fromLocal($("f-valid").value),
      synthetic: $("f-synthetic").checked,
      complexity: $("f-complexity").value,
      effort: $("f-effort").value,
      goal: $("f-goal").value,
      notify: $("f-notify").checked,
      recipient: $("f-recipient").value.trim(),
      facts: facts
    };
  }

  function buildRequest(input) {
    return {
      prediction: {
        schema_version: "1",
        prediction_id: "proto-" + Date.now(),
        subject: input.subject,
        generated_at: input.generatedAt,
        valid_until: input.validUntil,
        horizon: { value: input.horizonValue, unit: input.horizonUnit },
        direction: input.direction,
        confidence: input.confidence,
        model_version: input.modelVersion,
        synthetic: input.synthetic,
        metrics: {}
      },
      context: input.facts.length ? { facts: input.facts } : null,
      complexity: input.complexity,
      effort: input.effort || null,
      goal: input.goal,
      notify: input.notify,
      recipient: input.notify ? input.recipient || null : null,
      depth: 0
    };
  }

  function notice(text, tone) {
    var banner = R.h("div", "banner banner-" + (tone || "info"));
    banner.appendChild(R.h("strong", null, text));
    var host = $("result");
    host.insertBefore(banner, host.firstChild);
    setTimeout(function () {
      if (banner.parentNode) banner.parentNode.removeChild(banner);
    }, 5000);
  }

  function stopTicker() {
    if (state.ticker) {
      clearInterval(state.ticker);
      state.ticker = null;
    }
  }

  function finish(run) {
    stopTicker();
    state.running = false;
    state.task = M.buildTask(run);
    var failed = state.task.status.state === "failed";
    if (!failed && state.runView) state.runView.collapse();
    var view = failed ? R.failure(state.task) : R.report(state.task);
    $("result").appendChild(view);
    setControls(false);
    $("topbar-state").textContent = failed ? "任务失败" : "已完成 · " + R.formatTime(state.task.status.timestamp);
    emit("finish", { failed: failed, task: state.task });
    if (view.scrollIntoView) view.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function play() {
    if (state.running) return;
    var input = readInput();
    var run = M.buildRun(state.scenario, input);

    state.runView = R.runBlock(run);
    $("result").replaceChildren(state.runView.el);
    state.running = true;
    setControls(true);
    $("topbar-state").textContent = "运行中 · " + run.scenario.name;
    emit("start", run);

    var started = Date.now();
    stopTicker();
    state.ticker = setInterval(function () {
      var seconds = Math.floor((Date.now() - started) / 1000);
      state.runView.elapsed.textContent = pad(Math.floor(seconds / 60)) + ":" + pad(seconds % 60);
    }, 400);

    var index = 0;

    function apply(item) {
      emit("item", item);
      if (item.step) {
        state.runView.setStep(item.step, item.status, item.note);
        if (item.status === "running") {
          state.runView.addEvent(state.runView.stepLabel(item.step) + " 开始", "running");
        } else if (item.status !== "completed") {
          state.runView.addEvent(state.runView.stepLabel(item.step) + " " + (STATUS_TEXT[item.status] || item.status), item.status);
        }
      }
      if (item.event) state.runView.addEvent(item.event, item.status);
    }

    function tick() {
      if (!state.running) return;
      if (index >= run.queue.length) {
        finish(run);
        return;
      }
      var item = run.queue[index];
      index += 1;
      apply(item);
      setTimeout(tick, item.delay);
    }

    tick();
  }

  function cancel() {
    if (!state.running) return;
    state.running = false;
    stopTicker();
    setControls(false);
    $("topbar-state").textContent = "已取消";
    emit("finish", { failed: false, cancelled: true });
    if (state.runView) {
      state.runView.addEvent("用户取消，停止在途工作；已发生的邮件效果无法撤回", "degraded");
    }
    notice("已取消。取消不会撤回已经产生的外部效果。", "warn");
  }

  function bindDirection() {
    var host = $("f-direction");
    Array.prototype.forEach.call(host.querySelectorAll("button"), function (button) {
      button.addEventListener("click", function () {
        state.direction = button.dataset.value;
        Array.prototype.forEach.call(host.querySelectorAll("button"), function (other) {
          other.setAttribute("aria-pressed", String(other === button));
        });
      });
    });
  }

  function syncJsonFromForm() {
    $("json-area").value = JSON.stringify(buildRequest(readInput()), null, 2);
  }

  /* ---------- 新增图形的同步 ----------
   * 只读已有控件的值、只写图形属性，不参与任何提交逻辑：
   * 置信度环形仪表、周期进度条、时间跨度轴。
   */

  var HORIZON_MAX = { trading_days: 250, calendar_days: 365, hours: 720 };

  function syncGauge() {
    var wrap = $("f-confidence-wrap");
    var arc = $("f-confidence-arc");
    if (!wrap || !arc) return;
    var raw = $("f-confidence").value;
    var value = raw === "" ? null : Number(raw);
    var filled = value !== null && !isNaN(value);
    wrap.dataset.filled = String(filled);
    var pct = filled ? Math.max(0, Math.min(1, value)) : 0;
    arc.style.strokeDashoffset = String(100 - pct * 100);
  }

  function syncHorizon() {
    var bar = $("f-horizon-bar");
    if (!bar) return;
    var value = Number($("f-horizon").value) || 0;
    var max = HORIZON_MAX[$("f-horizon-unit").value] || 365;
    var pct = Math.max(0, Math.min(1, value / max));
    var width = value > 0 ? Math.max(pct * 100, 6) : 0;
    bar.style.width = width.toFixed(1) + "%";
  }

  function humanSpan(ms) {
    var minutes = Math.round(ms / 60000);
    if (minutes < 60) return minutes + " min";
    var hours = Math.floor(minutes / 60);
    if (hours < 48) return hours + "h";
    var days = Math.floor(hours / 24);
    if (days < 60) return days + "d" + (hours % 24 ? " " + (hours % 24) + "h" : "");
    return Math.round(days / 30) + " mo";
  }

  function syncSpan() {
    var chip = $("span-label");
    if (!chip) return;
    var from = $("f-generated").value;
    var to = $("f-valid").value;
    if (!from || !to) {
      chip.textContent = "跨度 ——";
      chip.dataset.tone = "";
      return;
    }
    var a = new Date(from).getTime();
    var b = new Date(to).getTime();
    if (isNaN(a) || isNaN(b)) {
      chip.textContent = "跨度 ——";
      chip.dataset.tone = "";
      return;
    }
    if (b < a) {
      chip.textContent = "有效期早于生成时间";
      chip.dataset.tone = "invalid";
      return;
    }
    chip.dataset.tone = "ok";
    chip.textContent = "跨度 " + humanSpan(b - a);
  }

  function syncViz() {
    syncGauge();
    syncHorizon();
    syncSpan();
  }

  function bindViz() {
    ["input", "change"].forEach(function (name) {
      $("f-confidence").addEventListener(name, syncGauge);
      $("f-horizon").addEventListener(name, syncHorizon);
      $("f-generated").addEventListener(name, syncSpan);
      $("f-valid").addEventListener(name, syncSpan);
    });
    $("f-horizon-unit").addEventListener("change", syncHorizon);
    syncViz();
  }

  function applyJsonToForm() {
    var raw = $("json-area").value;
    var value;
    try {
      value = JSON.parse(raw);
    } catch (error) {
      notice("JSON 解析失败：" + error.message, "danger");
      return;
    }
    if (!value || typeof value !== "object" || !value.prediction) {
      notice("JSON 里没有 prediction 字段", "danger");
      return;
    }
    var p = value.prediction;
    if (p.subject) $("f-subject").value = p.subject;
    if (p.model_version) $("f-model").value = p.model_version;
    if (p.direction) {
      state.direction = p.direction;
      Array.prototype.forEach.call($("f-direction").querySelectorAll("button"), function (button) {
        button.setAttribute("aria-pressed", String(button.dataset.value === p.direction));
      });
    }
    if (p.horizon) {
      $("f-horizon").value = p.horizon.value;
      $("f-horizon-unit").value = p.horizon.unit;
    }
    $("f-confidence").value = p.confidence === null || p.confidence === undefined ? "" : p.confidence;
    if (p.generated_at) $("f-generated").value = dtLocal(new Date(p.generated_at));
    if (p.valid_until) $("f-valid").value = dtLocal(new Date(p.valid_until));
    $("f-synthetic").checked = !!p.synthetic;

    var facts = (value.context && value.context.facts) || [];
    renderFacts(
      facts.map(function (fact, index) {
        return Object.assign({ id: "F-" + pad(index + 1) }, fact);
      })
    );

    if (value.complexity) $("f-complexity").value = value.complexity;
    if (value.goal) $("f-goal").value = value.goal;
    syncViz();
    notice("已应用到表单", "info");
  }

  function reset() {
    var start = new Date();
    start.setMinutes(0, 0, 0);
    $("f-generated").value = dtLocal(start);
    $("f-valid").value = dtLocal(new Date(start.getTime() + 86400000));
    $("f-confidence").value = "";
    $("f-notify").checked = false;
    $("f-recipient").value = "";
    $("f-recipient").disabled = true;
    renderFacts(M.factDefaults());
    syncJsonFromForm();
    $("result").replaceChildren(R.emptyState());
    $("topbar-state").textContent = "空闲";
    stopTicker();
    state.running = false;
    state.task = null;
    setControls(false);
    syncViz();
    emit("reset");
  }

  /* 场景是全局的：分析台的原型面板与办公区顶部的下拉都指向同一份 state */
  function chooseScenario(key, runNow) {
    state.scenario = key;
    Array.prototype.forEach.call($("probe-scenarios").querySelectorAll("button"), function (button) {
      button.dataset.active = String(button.dataset.key === key);
    });
    var select = $("office-scenario");
    if (select) select.value = key;
    emit("scenario", key);
    if (runNow && !state.running) play();
  }

  function buildProbe() {
    var host = $("probe-scenarios");
    M.scenarios.forEach(function (scenario) {
      var button = R.h("button", null, scenario.name);
      button.type = "button";
      button.title = scenario.hint;
      button.dataset.key = scenario.key;
      button.dataset.active = String(scenario.key === state.scenario);
      button.addEventListener("click", function () {
        chooseScenario(scenario.key, true);
      });
      host.appendChild(button);
    });
  }

  var VIEWS = {
    conversations: {
      kicker: "Next · P3",
      title: "会话记录",
      lede:
        "后端已有 GET /api/conversations 与记忆条目接口，可以做真实的「会话 → 轮次 → 续问」。任务历史列表目前没有接口，只能用浏览器本地缓存最近的 task id，这一点会在页面上说明清楚，不假装成服务端历史。"
    },
    settings: {
      kicker: "Next · P2",
      title: "设置",
      lede:
        "模型服务、外部能力、协作与授权、邮件投递、记忆策略拆成二级标签页；JSON 字段收进高级折叠；保存仍是完整对象的 PUT，不丢未展示字段。本原型聚焦分析台，这一块留到下一阶段。"
    }
  };

  function switchView(view) {
    var isDesk = view === "desk";
    var isOffice = view === "office";
    $("view-desk").hidden = !isDesk;
    $("view-office").hidden = !isOffice;
    $("view-placeholder").hidden = isDesk || isOffice;
    /* 分析台的标题区跟着视图走，办公区有自己的一行标题 */
    $("desk-head").hidden = !isDesk;
    $("topbar-title").textContent = isDesk ? "分析台" : isOffice ? "办公区" : "控制台";
    $("topbar-hint").textContent = isDesk
      ? "提交预测与事实，阅读可核查的结论"
      : isOffice
        ? "进度可视化：谁在做什么，做到哪一步"
        : "这一块留到后续阶段";
    document.querySelectorAll(".shell-nav button").forEach(function (button) {
      if (button.dataset.view === view) {
        button.setAttribute("aria-current", "page");
      } else {
        button.removeAttribute("aria-current");
      }
    });
    if (!isDesk && !isOffice) {
      var meta = VIEWS[view];
      $("ph-kicker").textContent = meta.kicker;
      $("ph-title").textContent = meta.title;
      $("ph-lede").textContent = meta.lede;
    }
    /* 办公区的 SVG 在隐藏时也能挂载，尺寸靠 viewBox 撑开 */
    if (isOffice && window.Office) window.Office.mount();
    emit("view", view);
  }

  function init() {
    var start = new Date();
    start.setMinutes(0, 0, 0);
    $("f-generated").value = dtLocal(start);
    $("f-valid").value = dtLocal(new Date(start.getTime() + 86400000));

    renderFacts(M.factDefaults());
    syncJsonFromForm();
    $("result").replaceChildren(R.emptyState());
    buildProbe();
    bindDirection();
    bindViz();

    /* 办公区：场景下拉与分析台的原型面板共用同一份 state */
    var officeSelect = $("office-scenario");
    M.scenarios.forEach(function (scenario) {
      var option = document.createElement("option");
      option.value = scenario.key;
      option.textContent = scenario.name;
      option.title = scenario.hint;
      officeSelect.appendChild(option);
    });
    officeSelect.value = state.scenario;
    officeSelect.addEventListener("change", function () {
      chooseScenario(officeSelect.value, true);
    });
    $("office-start").addEventListener("click", function () {
      if (!state.running) play();
    });
    $("office-reset").addEventListener("click", reset);
    $("office-drawer").querySelector(".drawer-link").addEventListener("click", function (event) {
      event.preventDefault();
      switchView("desk");
    });

    if (window.Office) {
      var office = window.Office;
      office.mount();
      window.StockPredictMailerApp.on("start", function (run) { office.begin(run); });
      window.StockPredictMailerApp.on("item", function (item) { office.apply(item); });
      window.StockPredictMailerApp.on("finish", function (info) { office.finish(info); });
      window.StockPredictMailerApp.on("reset", function () { office.reset(); });
    }

    $("task-form").addEventListener("submit", function (event) {
      event.preventDefault();
      if (state.running) return;
      play();
    });

    $("cancel-btn").addEventListener("click", cancel);
    $("reset-btn").addEventListener("click", reset);
    $("probe-replay").addEventListener("click", function () { if (!state.running) play(); });
    $("probe-clear").addEventListener("click", reset);
    $("json-from-form").addEventListener("click", syncJsonFromForm);
    $("json-apply").addEventListener("click", applyJsonToForm);

    $("add-fact").addEventListener("click", function () {
      var index = $("facts").querySelectorAll(".fact-block").length + 1;
      var now = new Date();
      var fact = {
        id: "F-" + pad(index),
        name: "",
        value: "",
        unit: "",
        source: "",
        observed_at: now.toISOString(),
        available_at: now.toISOString()
      };
      $("facts").appendChild(factBlock(fact));
    });

    $("f-notify").addEventListener("change", function () {
      var on = $("f-notify").checked;
      $("f-recipient").disabled = !on;
      if (on && !$("f-recipient").value) $("f-recipient").value = "preview@example.invalid";
    });

    document.querySelectorAll(".shell-nav button").forEach(function (button) {
      button.addEventListener("click", function () { switchView(button.dataset.view); });
    });

    $("probe-toggle").addEventListener("click", function () {
      var body = $("probe-body");
      var collapsed = body.hidden;
      body.hidden = !collapsed;
      $("probe-toggle").textContent = collapsed ? "−" : "+";
    });

    if (window.innerWidth < 860) {
      $("probe-body").hidden = true;
      $("probe-toggle").textContent = "+";
    }

    var query = new URLSearchParams(location.search);
    var view = query.get("view");
    if (view === "desk" || view === "office") switchView(view);

    /* 便于演示与截图：?notify=1 勾上通知，这样运行队列里才有投递这一步 */
    if (query.get("notify") === "1") {
      $("f-notify").checked = true;
      $("f-notify").dispatchEvent(new Event("change"));
      syncJsonFromForm();
    }

    /* ?confidence=0.72&horizon=20 用来核对环形仪表与周期条的填充效果 */
    if (query.get("confidence") !== null) {
      $("f-confidence").value = query.get("confidence");
    }
    if (query.get("horizon") !== null) {
      $("f-horizon").value = query.get("horizon");
    }
    syncViz();
    syncJsonFromForm();

    var preset = query.get("scenario");
    if (preset && M.scenarios.some(function (item) { return item.key === preset; })) {
      chooseScenario(preset, true);
    }
  }

  /* 对外的最小接口：办公区从这里订阅运行事件，不重新实现一遍流程 */
  window.StockPredictMailerApp = {
    on: function (name, fn) {
      (listeners[name] = listeners[name] || []).push(fn);
      return fn;
    },
    play: play,
    reset: reset,
    cancel: cancel,
    show: switchView,
    setScenario: function (key) { chooseScenario(key, false); },
    scenario: function () { return state.scenario; },
    isRunning: function () { return state.running; }
  };

  document.addEventListener("DOMContentLoaded", init);
})();
