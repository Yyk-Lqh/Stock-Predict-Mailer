(function () {
  "use strict";

  var SVGNS = "http://www.w3.org/2000/svg";

  function h(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function s(tag, attrs) {
    var node = document.createElementNS(SVGNS, tag);
    Object.keys(attrs).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    return node;
  }

  var DIRECTION = { up: "上涨", down: "下跌", flat: "持平" };
  var HORIZON = { trading_days: "交易日", calendar_days: "自然日", hours: "小时" };

  var ROLE = { main: "主 Agent", prediction: "预测分析", risk: "风险分析", advice: "建议生成" };

  var CHILD_STATUS = { completed: "完成", degraded: "降级", failed: "失败", working: "运行中", canceled: "已取消" };

  var MAIL = {
    simulated: { label: "模拟投递", tone: "neutral" },
    submitted: { label: "已提交服务器", tone: "ok" },
    retry: { label: "等待重试", tone: "warn" },
    uncertain: { label: "结果不确定", tone: "warn" },
    failed: { label: "投递失败", tone: "danger" },
    pending: { label: "排队中", tone: "neutral" },
    sending: { label: "发送中", tone: "neutral" }
  };

  var TASK = {
    submitted: { label: "已提交", tone: "info" },
    working: { label: "运行中", tone: "info" },
    completed: { label: "已完成", tone: "ok" },
    failed: { label: "任务失败", tone: "danger" },
    canceled: { label: "已取消", tone: "neutral" }
  };

  function pill(text, tone) {
    return h("span", "pill pill-" + (tone || "neutral"), text);
  }

  function formatTime(value) {
    if (!value) return "—";
    var date = new Date(value);
    if (isNaN(date.getTime())) return String(value);
    var mm = String(date.getMonth() + 1).padStart(2, "0");
    var dd = String(date.getDate()).padStart(2, "0");
    var hh = String(date.getHours()).padStart(2, "0");
    var mi = String(date.getMinutes()).padStart(2, "0");
    return mm + "-" + dd + " " + hh + ":" + mi;
  }

  function formatValue(value, unit) {
    if (value === null || value === undefined) return "—";
    var text = String(value);
    return unit ? text + " " + unit : text;
  }

  function emptyState() {
    var box = h("div", "empty-state");
    box.appendChild(h("h2", null, "还没有分析结果"));
    box.appendChild(
      h(
        "p",
        null,
        "左侧填好预测和事实后提交。任务运行时会流式显示执行计划，完成后按“结论—依据”的顺序展开报告。"
      )
    );

    var steps = h("ol", "empty-steps");
    [
      ["填写预测", "标的、方向、周期、有效期。置信度可以留空，留空表示上游未提供。"],
      ["补充客观事实", "每条事实都带来源与可用时间，报告会逐条引用。"],
      ["提交并阅读", "事实、推断、限制、风险、建议分列，点击编号可互相对照。"]
    ].forEach(function (item, index) {
      var li = h("li");
      li.appendChild(h("span", "n", String(index + 1).padStart(2, "0")));
      var body = h("div");
      body.appendChild(h("b", null, item[0]));
      body.appendChild(h("span", null, item[1]));
      li.appendChild(body);
      steps.appendChild(li);
    });

    box.appendChild(steps);
    return box;
  }

  function runBlock(run) {
    var wrap = h("div");
    var plan = h("div", "plan-block");
    var head = h("div", "plan-head");
    head.appendChild(h("h3", null, "执行计划"));
    var tail = h("div");
    tail.style.display = "flex";
    tail.style.alignItems = "center";
    tail.style.gap = "10px";
    var elapsed = h("span", "elapsed", "00:00");
    var toggle = h("button", "plan-toggle", "收起");
    toggle.type = "button";
    tail.appendChild(elapsed);
    tail.appendChild(toggle);
    head.appendChild(tail);
    plan.appendChild(head);

    var list = h("ol", "plan-list");
    var rows = {};

    run.steps.forEach(function (step) {
      var li = h("li");
      li.dataset.status = "pending";
      li.appendChild(h("span", "dot"));
      li.appendChild(h("span", "plabel", step.label));
      var meta = h("span", "pmeta", "等待");
      li.appendChild(meta);
      list.appendChild(li);
      rows[step.id] = { li: li, meta: meta };
    });

    plan.appendChild(list);

    var events = h("div", "events");
    events.appendChild(h("h4", null, "执行时间线"));
    var log = h("ol");
    events.appendChild(log);
    plan.appendChild(events);

    wrap.appendChild(plan);

    function setCollapsed(value) {
      plan.dataset.collapsed = String(value);
      toggle.textContent = value ? "展开" : "收起";
    }

    toggle.addEventListener("click", function () {
      setCollapsed(plan.dataset.collapsed !== "true");
    });

    return {
      el: wrap,
      elapsed: elapsed,
      collapse: function () { setCollapsed(true); },
      setStep: function (id, status, note) {
        var row = rows[id];
        if (!row) return;
        row.li.dataset.status = status;
        row.meta.textContent = note || (status === "running" ? "运行中" : "完成");
      },
      addEvent: function (text, status, at) {
        var li = h("li", null, (at || StockPredictMailerMock.stamp(new Date())) + "  " + text);
        if (status) li.dataset.status = status;
        log.appendChild(li);
        events.scrollTop = events.scrollHeight;
      },
      stepLabel: function (id) {
        return rows[id] ? rows[id].li.querySelector(".plabel").textContent : id;
      }
    };
  }

  function chartFigure(chart) {
    var figure = h("figure", "chart");
    var width = 560;
    var height = 210;
    var pad = { top: 16, right: 14, bottom: 26, left: 46 };

    var labels = chart.labels;
    var all = chart.history.concat(chart.forecast);
    var lows = chart.history.concat(chart.lower);
    var highs = chart.history.concat(chart.upper);

    var min = Math.min.apply(null, lows);
    var max = Math.max.apply(null, highs);
    var span = max - min || 1;
    min -= span * 0.15;
    max += span * 0.15;

    var innerW = width - pad.left - pad.right;
    var innerH = height - pad.top - pad.bottom;
    var stepX = innerW / (all.length - 1);

    var x = function (index) { return pad.left + index * stepX; };
    var y = function (value) { return pad.top + innerH - ((value - min) / (max - min)) * innerH; };

    var svg = s("svg", {
      viewBox: "0 0 " + width + " " + height,
      width: "100%",
      role: "img",
      "aria-label": "上游预测路径与区间示意"
    });
    svg.appendChild(s("title", {})).textContent = "预测路径与区间";

    [0, 0.5, 1].forEach(function (ratio) {
      var value = min + (max - min) * (1 - ratio);
      var gy = pad.top + innerH * ratio;
      svg.appendChild(
        s("line", {
          x1: pad.left,
          y1: gy,
          x2: width - pad.right,
          y2: gy,
          stroke: "rgba(255,255,255,0.09)",
          "stroke-width": 1,
          "stroke-dasharray": ratio === 1 ? "0" : "3 4"
        })
      );
      var label = s("text", {
        x: pad.left - 8,
        y: gy + 3,
        "text-anchor": "end",
        "font-size": 10,
        fill: "#5f7182",
        "font-family": "Consolas, monospace"
      });
      label.textContent = value.toFixed(2);
      svg.appendChild(label);
    });

    var splitIndex = chart.history.length - 1;
    var forecastStart = splitIndex + 1;

    var bandTop = [];
    var bandBottom = [];
    for (var i = 0; i < chart.forecast.length; i++) {
      bandTop.push(x(forecastStart + i) + "," + y(chart.upper[i]));
      bandBottom.unshift(x(forecastStart + i) + "," + y(chart.lower[i]));
    }

    svg.appendChild(
      s("polygon", {
        points: bandTop.concat(bandBottom).join(" "),
        fill: "#16d3e6",
        "fill-opacity": "0.16",
        stroke: "none"
      })
    );

    var historyPath = chart.history
      .map(function (value, index) { return (index ? "L" : "M") + x(index) + " " + y(value); })
      .join(" ");
    svg.appendChild(s("path", { d: historyPath, fill: "none", stroke: "#7e8b99", "stroke-width": 1.6 }));

    var anchor = "M" + x(splitIndex) + " " + y(chart.history[chart.history.length - 1]);
    var forecastPath =
      anchor +
      chart.forecast
        .map(function (value, index) {
          return "L" + x(forecastStart + index) + " " + y(value);
        })
        .join(" ");
    svg.appendChild(
      s("path", {
        d: forecastPath,
        fill: "none",
        stroke: "#16d3e6",
        "stroke-width": 2,
        "stroke-dasharray": "5 3"
      })
    );

    chart.forecast.forEach(function (value, index) {
      svg.appendChild(s("circle", { cx: x(forecastStart + index), cy: y(value), r: 2.6, fill: "#16d3e6" }));
    });

    chart.history.forEach(function (value, index) {
      svg.appendChild(s("circle", { cx: x(index), cy: y(value), r: 2, fill: "#5f7182" }));
    });

    svg.appendChild(
      s("line", {
        x1: x(splitIndex),
        y1: pad.top,
        x2: x(splitIndex),
        y2: pad.top + innerH,
        stroke: "rgba(255,255,255,0.24)",
        "stroke-width": 1,
        "stroke-dasharray": "2 4"
      })
    );

    labels.forEach(function (label, index) {
      var text = s("text", {
        x: x(forecastStart + index),
        y: height - 8,
        "text-anchor": "middle",
        "font-size": 10,
        fill: "#5f7182",
        "font-family": "Consolas, monospace"
      });
      text.textContent = label;
      svg.appendChild(text);
    });

    figure.appendChild(svg);
    figure.appendChild(
      h(
        "figcaption",
        null,
        "历史为浅灰实线；虚线为上游预测路径，浅色带为上游给出的区间。区间宽度不换算为置信度。"
      )
    );
    return figure;
  }

  function section(index, title, count) {
    var node = h("section", "report-section");
    var head = h("h3");
    head.appendChild(h("span", "idx", index));
    head.appendChild(h("span", null, title));
    if (count !== undefined) head.appendChild(h("span", "count", count));
    node.appendChild(head);
    return node;
  }

  function report(task) {
    var analysis = task.artifacts[0].parts[0].data;
    var prediction = analysis.prediction;
    var wrap = h("div", "report");

    var mast = h("div", "report-mast");
    var quote = h("div", "mast-quote");
    quote.appendChild(h("h2", null, prediction.subject));
    var dir = h("span", "dir dir-" + prediction.direction, DIRECTION[prediction.direction] || prediction.direction);
    quote.appendChild(dir);
    mast.appendChild(quote);

    var meta = h("div", "mast-meta");
    [
      ["周期", prediction.horizon.value + " " + (HORIZON[prediction.horizon.unit] || prediction.horizon.unit)],
      ["模型", prediction.model_version],
      ["生成", formatTime(prediction.generated_at)],
      ["有效至", formatTime(prediction.valid_until)],
      ["编号", analysis.analysis_id]
    ].forEach(function (pair) {
      var item = h("span");
      item.appendChild(document.createTextNode(pair[0] + " "));
      item.appendChild(h("b", null, pair[1]));
      meta.appendChild(item);
    });
    if (prediction.synthetic) meta.appendChild(h("span", null, "SYNTHETIC / 合成数据"));
    mast.appendChild(meta);

    var statusRow = h("div", "status-row");
    var taskState = TASK[task.status.state] || { label: task.status.state, tone: "neutral" };
    statusRow.appendChild(pill("任务 " + taskState.label, taskState.tone));
    var analysisTone = analysis.status === "ok" ? "ok" : "warn";
    statusRow.appendChild(pill("分析 " + (analysis.status === "ok" ? "正常" : "降级"), analysisTone));
    if (analysis.mail) {
      var mailMeta = MAIL[analysis.mail.status] || { label: analysis.mail.status, tone: "neutral" };
      statusRow.appendChild(pill("邮件 " + mailMeta.label, mailMeta.tone));
    } else {
      statusRow.appendChild(pill("未选择通知", "neutral"));
    }
    mast.appendChild(statusRow);
    wrap.appendChild(mast);

    var predSection = section("01", "上游预测", "Prediction");
    var grid = h("div", "pred-grid");

    var dirCell = h("div", "pred-cell");
    dirCell.appendChild(h("span", null, "方向"));
    var dirStrong = h("strong", "dir-" + prediction.direction, DIRECTION[prediction.direction] || "—");
    dirCell.appendChild(dirStrong);
    grid.appendChild(dirCell);

    var confCell = h("div", "pred-cell");
    confCell.appendChild(h("span", null, "置信度"));
    if (prediction.confidence === null || prediction.confidence === undefined) {
      confCell.appendChild(h("span", "empty-slot", "上游未提供"));
    } else {
      confCell.appendChild(h("strong", "num", Number(prediction.confidence).toFixed(2)));
    }
    grid.appendChild(confCell);

    var horizonCell = h("div", "pred-cell");
    horizonCell.appendChild(h("span", null, "周期"));
    horizonCell.appendChild(
      h("strong", null, prediction.horizon.value + " " + (HORIZON[prediction.horizon.unit] || prediction.horizon.unit))
    );
    grid.appendChild(horizonCell);

    var modelCell = h("div", "pred-cell");
    modelCell.appendChild(h("span", null, "模型版本"));
    modelCell.appendChild(h("strong", "mono", prediction.model_version));
    grid.appendChild(modelCell);

    predSection.appendChild(grid);
    if (analysis.chart) predSection.insertBefore(chartFigure(analysis.chart), predSection.querySelector(".pred-grid").nextSibling);
    wrap.appendChild(predSection);

    var factSection = section("02", "客观事实", analysis.facts.length + " 条");
    var cards = h("div", "fact-cards");
    var factNodes = {};

    analysis.facts.forEach(function (fact) {
      var card = h("div", "fact-card");
      card.dataset.factId = fact.id;
      card.appendChild(h("div", "fid", fact.id));
      card.appendChild(h("div", "fname", fact.name));
      card.appendChild(h("div", "fval", formatValue(fact.value, fact.unit)));
      var fm = h("div", "fmeta");
      fm.appendChild(h("span", "fsrc", fact.source));
      fm.appendChild(document.createTextNode(" 观测 " + formatTime(fact.observed_at) + " · 可用 " + formatTime(fact.available_at)));
      card.appendChild(fm);
      cards.appendChild(card);
      factNodes[fact.id] = card;
    });

    factSection.appendChild(cards);
    wrap.appendChild(factSection);

    var inferSection = section("03", "推断与依据", analysis.inferences.length + " 条推断");
    var inferenceNodes = [];

    analysis.inferences.forEach(function (inference) {
      var item = h("div", "inference");
      var head = h("div", "ihead");
      head.appendChild(h("span", "code", inference.code));
      item.appendChild(head);
      item.appendChild(h("p", null, inference.text));
      var row = h("div", "ev-row");
      row.appendChild(h("span", "ev-label", "依据"));
      inference.evidence_ids.forEach(function (id) {
        var chip = h("button", "ev", id);
        chip.type = "button";
        chip.addEventListener("click", function () { highlight(id); });
        row.appendChild(chip);
      });
      item.appendChild(row);
      inferSection.appendChild(item);
      inferenceNodes.push({ el: item, ids: inference.evidence_ids });
    });

    wrap.appendChild(inferSection);

    var limitSection = section("04", "限制与不确定性", analysis.limitations.length + " 条");
    var limitList = h("ul", "limits");
    analysis.limitations.forEach(function (item) { limitList.appendChild(h("li", null, item.text)); });
    limitSection.appendChild(limitList);
    wrap.appendChild(limitSection);

    var riskSection = section("05", "风险", analysis.risks.length + " 条");
    var riskList = h("ul", "risks");
    analysis.risks.forEach(function (item) { riskList.appendChild(h("li", null, item.text)); });
    riskSection.appendChild(riskList);
    wrap.appendChild(riskSection);

    var adviceSection = section("06", "建议", analysis.recommendations.length + " 条");
    var adviceList = h("ul", "advice");
    analysis.recommendations.forEach(function (item) { adviceList.appendChild(h("li", null, item.text)); });
    adviceSection.appendChild(adviceList);
    wrap.appendChild(adviceSection);

    var collabSection = section("07", "协作与冲突", analysis.children.length ? analysis.children.length + " 条分支分析" : "未委派");
    if (!analysis.children.length) {
      collabSection.appendChild(
        h("p", "prose muted", "简单任务由小鲸直接完成，本轮没有派出分支分析。")
      );
    }
    var rows = h("div", "child-rows");
    analysis.children.forEach(function (child) {
      var row = h("div", "child-row");
      var roleCell = h("div");
      roleCell.appendChild(h("b", null, ROLE[child.role] || child.role));
      roleCell.appendChild(h("span", "role-en", child.role + " · depth " + child.depth));
      row.appendChild(roleCell);

      var statusCell = h("div");
      var tone = child.status === "completed" ? "ok" : child.status === "degraded" ? "warn" : child.status === "failed" ? "danger" : "neutral";
      statusCell.appendChild(pill(CHILD_STATUS[child.status] || child.status, tone));
      row.appendChild(statusCell);

      var detail = h("div", "detail");
      if (child.result) {
        var parts = [];
        parts.push("结论 " + ((child.result.conclusions || []).join("、") || "无"));
        if (child.result.evidence_ids && child.result.evidence_ids.length) {
          parts.push("依据 " + child.result.evidence_ids.join("、"));
        }
        if (child.result.uncertainty && child.result.uncertainty.length) {
          parts.push("不确定 " + child.result.uncertainty.join("、"));
        }
        detail.textContent = parts.join(" · ");
      } else if (child.error) {
        detail.textContent = child.error.code + " · " + child.error.message;
      } else {
        detail.textContent = "未参与本轮";
      }
      row.appendChild(detail);
      rows.appendChild(row);
    });
    if (analysis.children.length) collabSection.appendChild(rows);

    if (analysis.conflicts.length) {
      var conflicts = h("div", "conflicts");
      var heading = h("p");
      heading.appendChild(h("b", null, "已排除的冲突"));
      conflicts.appendChild(heading);
      analysis.conflicts.forEach(function (conflict) {
        conflicts.appendChild(h("p", null, conflict.role + " · " + conflict.code + " — " + conflict.reason));
      });
      collabSection.appendChild(conflicts);
    }

    var usage = h("div", "usage-line");
    [
      ["调用次数", analysis.usage.calls],
      ["费用预留", "$" + Number(analysis.usage.reserved_usd).toFixed(2)],
      ["预算上限", "$" + Number(analysis.usage.budget_usd).toFixed(2)]
    ].forEach(function (pair) {
      var item = h("span");
      item.appendChild(document.createTextNode(pair[0] + " "));
      item.appendChild(h("b", null, pair[1]));
      usage.appendChild(item);
    });
    collabSection.appendChild(usage);
    wrap.appendChild(collabSection);

    var mailSection = section("08", "通知与投递", "Mail");
    if (analysis.mail) {
      var receipt = h("div", "receipt");
      var top = h("div", "receipt-top");
      top.appendChild(h("h4", null, "投递回执"));
      var mm = MAIL[analysis.mail.status] || { label: analysis.mail.status, tone: "neutral" };
      top.appendChild(pill(mm.label, mm.tone));
      receipt.appendChild(top);

      var dl = h("dl", "receipt-grid");
      [
        ["邮件 ID", analysis.mail.id],
        ["状态码", analysis.mail.status],
        ["尝试次数", String(analysis.mail.attempts || 1)],
        ["下次重试", analysis.mail.next_attempt ? formatTime(analysis.mail.next_attempt) : "—"]
      ].forEach(function (pair) {
        dl.appendChild(h("dt", null, pair[0]));
        var dd = h("dd");
        if (pair[0] === "邮件 ID" || pair[0] === "状态码") dd.className = "mono";
        dd.textContent = pair[1];
        dl.appendChild(dd);
      });
      receipt.appendChild(dl);

      if (analysis.mail.error) {
        var err = h("p", "receipt-note");
        err.textContent = analysis.mail.error.code + " · " + analysis.mail.error.message;
        receipt.appendChild(err);
      }

      var note = h("p", "receipt-note");
      note.textContent =
        analysis.mail.status === "simulated"
          ? "simulated 表示邮件写入本地文件或由 Mock 工具接收，不代表真实邮箱已经收到。"
          : analysis.mail.status === "uncertain"
            ? "uncertain 表示可能已经产生外部效果。不要自动重发，先核对邮箱与工具日志再决定。"
            : analysis.mail.status === "submitted"
              ? "submitted 只表示邮件服务器已接受，不保证最终到达收件人。"
              : "retry 表示仍在重试窗口内，等待下一轮投递。";
      receipt.appendChild(note);
      mailSection.appendChild(receipt);
    } else {
      mailSection.appendChild(h("p", "prose muted", "本次任务未选择通知，因此没有投递结果。"));
    }
    wrap.appendChild(mailSection);

    var raw = h("details", "raw-json");
    raw.appendChild(h("summary", null, "结构化任务结果（调试用）"));
    var pre = h("pre");
    pre.textContent = JSON.stringify(task, null, 2);
    raw.appendChild(pre);
    wrap.appendChild(raw);

    function highlight(id) {
      var on = factNodes[id] && factNodes[id].dataset.evidence !== "on";
      Object.keys(factNodes).forEach(function (key) { delete factNodes[key].dataset.evidence; });
      inferenceNodes.forEach(function (node) { delete node.el.dataset.evidence; });
      if (!on) return;
      if (factNodes[id]) factNodes[id].dataset.evidence = "on";
      inferenceNodes.forEach(function (node) {
        if (node.ids.indexOf(id) !== -1) node.el.dataset.evidence = "on";
      });
    }

    Object.keys(factNodes).forEach(function (id) {
      factNodes[id].addEventListener("click", function () { highlight(id); });
      factNodes[id].style.cursor = "pointer";
    });

    return wrap;
  }

  function failure(task) {
    var error = (task.metadata && task.metadata.error) || { code: "INTERNAL_ERROR", message: "任务失败" };
    var card = h("div", "fail-card");
    card.appendChild(h("h2", null, "任务没有产生结果"));
    card.appendChild(h("span", "code", error.code || "ERROR"));
    card.appendChild(h("p", null, error.message || "任务终止。"));

    var next = h("div", "fail-next");
    var tips = {
      CALL_TIMEOUT: "检查模型服务地址与网络，或把超时从 20 秒上调后重试。",
      AUTH_FAILED: "检查模型服务凭据是否有效；凭据保存在服务端，不在页面回显。",
      BUDGET_EXHAUSTED: "本轮费用触及预算上限，调整上限或减少委派后重试。",
      STALE_RESULT: "预测已过期，向上游获取新的结果后再提交。"
    };
    next.textContent = "下一步：" + (tips[error.code] || "查看结构化结果中的错误码后决定是否重试。");
    card.appendChild(next);

    var note = h("p", "stale-note");
    note.textContent =
      "失败的任务没有 artifacts，也不会自动重跑。日志中不含预测原文、密钥或工具返回内容。";
    card.appendChild(note);

    var wrap = h("div");
    wrap.appendChild(card);

    var raw = h("details", "raw-json");
    raw.appendChild(h("summary", null, "结构化任务结果（调试用）"));
    var pre = h("pre");
    pre.textContent = JSON.stringify(task, null, 2);
    raw.appendChild(pre);
    wrap.appendChild(raw);
    return wrap;
  }

  window.StockPredictMailerRender = {
    h: h,
    emptyState: emptyState,
    runBlock: runBlock,
    report: report,
    failure: failure,
    formatTime: formatTime
  };
})();
