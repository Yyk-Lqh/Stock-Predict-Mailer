(function () {
  "use strict";

  var now = function () { return new Date(); };

  var iso = function (date) { return date.toISOString(); };

  var pad = function (n) { return String(n).padStart(2, "0"); };

  var stamp = function (date) {
    return pad(date.getHours()) + ":" + pad(date.getMinutes()) + ":" + pad(date.getSeconds());
  };

  var FACTS_ALL = [
    {
      id: "F-01",
      name: "成交量温和放大",
      value: 1.28,
      unit: "倍",
      source: "上游行情快照",
      observed_at: "",
      available_at: ""
    },
    {
      id: "F-02",
      name: "板块主力资金净流入",
      value: 3.6,
      unit: "亿元",
      source: "上游行业资金流",
      observed_at: "",
      available_at: ""
    },
    {
      id: "F-03",
      name: "换手率",
      value: 4.2,
      unit: "%",
      source: "上游行情快照",
      observed_at: "",
      available_at: ""
    },
    {
      id: "F-04",
      name: "近 20 日振幅",
      value: 5.8,
      unit: "%",
      source: "上游统计口径",
      observed_at: "",
      available_at: ""
    }
  ];

  var SCENARIOS = [
    {
      key: "ok",
      name: "正常完成",
      hint: "复杂任务、小鱼独立分析、无置信度、邮件模拟投递",
      confidence: null,
      status: "ok",
      mail: "simulated",
      factCount: 4
    },
    {
      key: "confidence",
      name: "带置信度",
      hint: "置信度 0.62，正常渲染为数值而非进度条",
      confidence: 0.62,
      status: "ok",
      mail: "submitted",
      factCount: 4
    },
    {
      key: "degraded",
      name: "分析降级",
      hint: "风险角色超时，主分析采用降级结果",
      confidence: null,
      status: "degraded",
      mail: "retry",
      factCount: 2
    },
    {
      key: "conflict",
      name: "方向冲突",
      hint: "风险角色与主结论相反，冲突被排除",
      confidence: 0.55,
      status: "ok",
      mail: "simulated",
      factCount: 4
    },
    {
      key: "uncertain",
      name: "邮件不确定",
      hint: "外部工具已产生效果但未确认，禁止自动重发",
      confidence: null,
      status: "ok",
      mail: "uncertain",
      factCount: 4
    },
    {
      key: "failed",
      name: "任务失败",
      hint: "外部模型超时，任务终止且没有产物",
      confidence: null,
      status: "failed",
      mail: null,
      factCount: 4
    }
  ];

  function factSet(count) {
    var base = now();
    return FACTS_ALL.slice(0, count).map(function (fact, index) {
      var observed = new Date(base.getTime() - (45 + index * 3) * 60000);
      return Object.assign({}, fact, {
        observed_at: iso(observed),
        available_at: iso(new Date(observed.getTime() + 5 * 60000))
      });
    });
  }

  function horizonLabel(value, unit) {
    var names = { trading_days: "个交易日", calendar_days: "个自然日", hours: "小时" };
    return value + names[unit];
  }

  function buildAnalysis(scenario, input) {
    var facts = input.facts && input.facts.length ? input.facts : factSet(scenario.factCount);
    var factsUsed = facts.map(function (f) { return f.id; });
    var first = factsUsed[0] || null;
    var second = factsUsed[1] || first;
    var third = factsUsed[2] || second || first;

    var inferences = [
      {
        code: "INF-01",
        text: "短期动能延续，" + horizonLabel(input.horizonValue, input.horizonUnit) + "内偏强的可能性略高于回落，但幅度受板块整体节奏约束。",
        evidence_ids: [first, second].filter(Boolean)
      },
      {
        code: "INF-02",
        text: "板块资金集中度上升，个股弹性可能被放大；这种放大在回落时同样成立。",
        evidence_ids: [second, third].filter(function (id, index, arr) { return id && arr.indexOf(id) === index; })
      }
    ];

    var recommendations = [
      {
        code: "REC-01",
        text: "以观察为主，等第二个交易日的量能确认后再决定是否加仓。",
        evidence_ids: first ? [first] : []
      },
      {
        code: "REC-02",
        text: "若出现放量滞涨，优先降低仓位，而不是用补仓摊低成本。",
        evidence_ids: third ? [third] : []
      }
    ];

    var limitations = [
      { code: "LIM-01", text: "事实只覆盖当日半日交易，不足以支持跨周判断。" },
      { code: "LIM-03", text: "未接入公告、宏观与行业政策数据，无法评估事件冲击。" }
    ];

    if (input.confidence === null) {
      limitations.unshift({ code: "LIM-02", text: "上游未提供置信度，本报告不对概率做任何量化或折算。" });
    }

    var risks = [
      { code: "RSK-01", text: "放量后次日缩量回落，短期动能可能快速衰减。" },
      { code: "RSK-02", text: "板块资金流入若由单一标的驱动，扩散性不足。" }
    ];

    var children = [
      {
        id: "child-prediction",
        role: "prediction",
        status: "completed",
        depth: 1,
        tools: [],
        data_fields: ["prediction", "facts"],
        result: { conclusions: ["SHORT_TERM_STRENGTH"], evidence_ids: [first, second].filter(Boolean), uncertainty: ["LIM-01"] }
      },
      {
        id: "child-risk",
        role: "risk",
        status: "completed",
        depth: 1,
        tools: [],
        data_fields: ["prediction", "facts"],
        result: { conclusions: ["DRAWDOWN_RISK"], evidence_ids: [third].filter(Boolean), uncertainty: ["LIM-01"] }
      },
      {
        id: "child-advice",
        role: "advice",
        status: "completed",
        depth: 1,
        tools: [],
        data_fields: ["prediction", "facts"],
        result: { conclusions: ["OBSERVE_FIRST"], evidence_ids: [first].filter(Boolean), uncertainty: [] }
      }
    ];

    var conflicts = [];

    if (scenario.key === "degraded") {
      children[1] = {
        id: "child-risk",
        role: "risk",
        status: "failed",
        depth: 1,
        tools: [],
        data_fields: ["prediction", "facts"],
        error: { code: "CALL_TIMEOUT", message: "小鱼 20 秒内未返回" }
      };
      limitations.unshift({ code: "LIM-04", text: "小鱼的风险分析超时，本报告的风险段落来自小鲸的保守估计。" });
      risks = [{ code: "RSK-01", text: "缺少小鱼的独立风险判断，风险覆盖可能不完整。" }];
    }

    if (scenario.key === "conflict") {
      children[1] = {
        id: "child-risk",
        role: "risk",
        status: "degraded",
        depth: 1,
        tools: [],
        data_fields: ["prediction", "facts"],
        result: { conclusions: ["DIRECTION_DOWN"], evidence_ids: [factsUsed[factsUsed.length - 1] || first].filter(Boolean), uncertainty: ["LIM-01"] }
      };
      conflicts = [
        {
          role: "risk",
          code: "DIRECTION_CONFLICT",
          reason: "风险角色认为周期太短、证据不足，给出反向判断；主 Agent 按证据强度排除该结论。"
        }
      ];
      limitations.unshift({ code: "LIM-05", text: "分支结论之间存在方向冲突，冲突结论已排除但不代表其依据无效。" });
    }

    var mail = null;

    if (scenario.mail) {
      mail = {
        id: "mail_" + Math.random().toString(36).slice(2, 10),
        status: scenario.mail,
        attempts: scenario.mail === "retry" ? 2 : 1,
        next_attempt: scenario.mail === "retry" ? iso(new Date(Date.now() + 300000)) : null,
        error:
          scenario.mail === "uncertain"
            ? { code: "TOOL_UNCERTAIN", message: "外部工具调用后连接中断，可能已经产生发送效果" }
            : null
      };
    }

    var chart = {
      unit: "CNY",
      labels: ["T+1", "T+2", "T+3", "T+4", "T+5"],
      history: [12.02, 12.16, 12.28, 12.35, 12.41],
      forecast: [12.55, 12.63, 12.58, 12.72, 12.66],
      lower: [12.31, 12.36, 12.29, 12.4, 12.31],
      upper: [12.79, 12.9, 12.87, 13.04, 13.01]
    };

    return {
      schema_version: "1",
      analysis_id: "an_" + Math.random().toString(36).slice(2, 10),
      generated_at: iso(now()),
      status: scenario.status,
      mode: "deterministic",
      prediction: {
        subject: input.subject,
        model_version: input.modelVersion,
        direction: input.direction,
        confidence: input.confidence,
        horizon: { value: input.horizonValue, unit: input.horizonUnit },
        generated_at: input.generatedAt,
        valid_until: input.validUntil,
        synthetic: input.synthetic
      },
      facts: facts,
      inferences: inferences,
      recommendations: recommendations,
      limitations: limitations,
      risks: risks,
      children: input.complexity === "simple" ? [] : children,
      conflicts: input.complexity === "simple" ? [] : conflicts,
      usage: {
        calls: input.complexity === "simple" ? 3 : 7,
        reserved_usd: 0,
        budget_usd: 0.1
      },
      mail: mail,
      chart: chart
    };
  }

  function buildRun(key, input) {
    var scenario = SCENARIOS.filter(function (s) { return s.key === key; })[0] || SCENARIOS[0];
    var simple = input.complexity === "simple";
    var notify = input.notify && scenario.mail;

    var steps = [{ id: "plan", label: "小鲸 · 规划任务" },
                 { id: "context", label: "小鲸 · 读取上下文" }];

    if (!simple) {
      steps.push({ id: "prediction", label: "小鱼 · 预测分析" });
      steps.push({ id: "risk", label: "小鱼 · 风险分析" });
      steps.push({ id: "advice", label: "小鱼 · 建议生成" });
    } else {
      steps.push({ id: "analysis", label: "小鲸 · 直接分析" });
    }

    steps.push({ id: "charts", label: "小鲸 · 生成图表" });
    steps.push({ id: "summary", label: "小鲸 · 汇总与冲突排除" });

    if (notify) {
      steps.push({ id: "mail", label: "小鲸 · 投递邮件" });
    }

    var queue = [];
    var push = function (delay, item) {
      queue.push(Object.assign({ delay: delay }, item));
    };

    push(120, { step: "plan", status: "running" });
    push(520, { step: "plan", status: "completed", note: simple ? "简单任务，不委派" : "派遣小鱼做分支分析" });
    push(140, { step: "context", status: "running" });
    push(520, { step: "context", status: "completed", note: (input.facts || []).length + " 条事实，校验通过" });

    if (scenario.key === "failed") {
      push(220, { step: "prediction", status: "running" });
      push(900, { step: "prediction", status: "failed", note: "CALL_TIMEOUT" });
      push(120, { event: "外部模型 20 秒内未返回，任务终止", status: "failed" });
      steps = steps.slice(0, 3);
      return { scenario: scenario, steps: steps, queue: queue, input: input };
    }

    if (simple) {
      push(200, { step: "analysis", status: "running" });
      push(900, { step: "analysis", status: "completed" });
    } else {
      push(160, { step: "prediction", status: "running" });
      push(650, { step: "prediction", status: "completed", note: "1 条结论" });
      push(120, { step: "risk", status: "running" });

      if (scenario.key === "degraded") {
        push(1400, { step: "risk", status: "failed", note: "CALL_TIMEOUT" });
        push(100, { event: "风险角色超时，主分析降级", status: "degraded" });
      } else if (scenario.key === "conflict") {
        push(700, { step: "risk", status: "degraded", note: "方向与主结论冲突" });
        push(100, { event: "检测到方向冲突，进入排除流程", status: "degraded" });
      } else {
        push(700, { step: "risk", status: "completed", note: "1 条结论" });
      }

      push(120, { step: "advice", status: "running" });
      push(650, { step: "advice", status: "completed", note: "2 条建议" });
    }

    push(140, { step: "charts", status: "running" });
    push(480, { step: "charts", status: "completed", note: "1 张预测路径图" });
    push(140, { step: "summary", status: "running" });
    push(
      560,
      { step: "summary", status: "completed", note: scenario.key === "conflict" ? "排除 1 条冲突" : "无冲突" }
    );

    if (notify) {
      push(160, { step: "mail", status: "running" });
      push(
        700,
        {
          step: "mail",
          status: scenario.mail === "retry" ? "degraded" : scenario.mail === "uncertain" ? "degraded" : "completed",
          note: scenario.mail
        }
      );
    }

    return { scenario: scenario, steps: steps, queue: queue, input: input };
  }

  function buildTask(run) {
    var analysis = buildAnalysis(run.scenario, run.input);
    var failed = run.scenario.key === "failed";

    return {
      id: "task_" + Math.random().toString(36).slice(2, 10),
      contextId: "ctx_" + Math.random().toString(36).slice(2, 8),
      status: {
        state: failed ? "failed" : "completed",
        timestamp: iso(now())
      },
      metadata: failed
        ? { error: { code: "CALL_TIMEOUT", message: "外部模型 20 秒内未返回", retryable: true } }
        : {},
      artifacts: failed ? [] : [{ parts: [{ data: analysis }] }]
    };
  }

  window.StockPredictMailerMock = {
    scenarios: SCENARIOS,
    factDefaults: function () { return factSet(3); },
    buildRun: buildRun,
    buildTask: buildTask,
    stamp: stamp
  };
})();
