/* ===== Scene：办公区场景装配（深空科技风） =====
 *
 * 一层一层往上叠：
 *   backdrop   深空底 + 网格 + 地平线 + 透视线（伪造纵深）
 *   board      任务进度看板（放大、霓虹、按 run.steps 现画阶段点）
 *   plotter    出图台        lounge  待命区
 *   deskBack   椅子 / 显示器 / 桌面物件（键盘在人物之前，所以手能压在键盘上）
 *   actorsSeated  落座角色
 *   actorsWalk    走位角色（压在桌面之后，走过去会被桌子挡住）
 *   deskFront  桌面 + 桌裙 + 铭牌（挡住落座角色的下半身）
 *   foreground 前景摆件 + 暗角
 */
window.Scene = (function () {
  "use strict";

  var NS = "http://www.w3.org/2000/svg";
  var VIEW_W = 1600, VIEW_H = 900, FLOOR = 740, ACTOR_SCALE = 1, LOUNGE_SCALE = 0.92;
  var ACCENT = "#16D3E6";

  function el(tag, attrs, kids) {
    var node = document.createElementNS(NS, tag);
    if (attrs) for (var k in attrs) if (attrs[k] !== null && attrs[k] !== undefined) node.setAttribute(k, attrs[k]);
    if (kids) for (var i = 0; i < kids.length; i++) if (kids[i]) node.appendChild(kids[i]);
    return node;
  }
  function t(x, y, str, attrs) {
    var a = { x: x, y: y };
    if (attrs) for (var k in attrs) a[k] = attrs[k];
    var node = el("text", a);
    node.textContent = str;
    return node;
  }

  /* 两台电脑：小鲸常驻 P1，小鱼在 P2 与待命区之间往返 */
  var LAYOUT = {
    floor: FLOOR,
    seats: {
      main: { x: 470, code: "P1", name: "小鲸", w: 500 },
      sub: { x: 1010, code: "P2", name: "小鱼", w: 500 }
    },
    lounge: { main: 490, sub: 1400 },
    loungeY: { main: FLOOR, sub: FLOOR },
    mailbox: 740,
    board: { x: 410, y: 36, w: 780, h: 268 },
    plotter: { x: 148, y: 352 }
  };

  var STAGES = [
    { id: "plan", label: "规划" },
    { id: "context", label: "补数" },
    { id: "prediction", label: "预测" },
    { id: "risk", label: "风险" },
    { id: "charts", label: "出图" },
    { id: "summary", label: "汇总" },
    { id: "mail", label: "投递" }
  ];

  var root = null;
  var layers = {};
  var actors = {};
  var parts = { board: null, plotter: null, mailbox: null, desks: {} };

  /* ---------------- 背景 ---------------- */

  function buildBackdrop() {
    var g = el("g", { class: "layer-backdrop" });

    g.appendChild(el("rect", { x: 0, y: 0, width: VIEW_W, height: FLOOR, fill: "url(#wallGrad)" }));
    /* 顶部冷光晕：把视线压到中间 */
    g.appendChild(el("ellipse", { cx: 800, cy: -120, rx: 820, ry: 460, fill: "url(#glowTop)" }));
    g.appendChild(el("ellipse", { cx: 180, cy: 640, rx: 320, ry: 260, fill: "url(#glowLeft)" }));
    g.appendChild(el("ellipse", { cx: 1430, cy: 660, rx: 320, ry: 260, fill: "url(#glowRight)" }));

    /* 低饱和网格 */
    g.appendChild(el("rect", {
      x: 0, y: 0, width: VIEW_W, height: FLOOR,
      fill: "url(#gridPat)", mask: "url(#gridMask)"
    }));

    /* 地平线 + 地台 */
    g.appendChild(el("rect", { x: 0, y: FLOOR, width: VIEW_W, height: VIEW_H - FLOOR, fill: "url(#floorGrad)" }));
    g.appendChild(el("rect", { x: 0, y: FLOOR - 20, width: VIEW_W, height: 20, fill: "#0C1320" }));
    g.appendChild(el("rect", { x: 0, y: FLOOR - 21, width: VIEW_W, height: 1, fill: "rgba(255,255,255,0.06)" }));
    g.appendChild(el("rect", { x: 0, y: FLOOR - 2, width: VIEW_W, height: 18, fill: "url(#horizonGlow)" }));
    g.appendChild(el("rect", { x: 0, y: FLOOR - 1, width: VIEW_W, height: 2, fill: ACCENT, opacity: "0.55" }));

    /* 地面透视：向消失点收敛的线 + 几条横线 */
    var vx = 800, vy = FLOOR;
    var floorLines = el("g", { class: "floor-mesh" });
    for (var x = -600; x <= 2200; x += 200) {
      floorLines.appendChild(el("path", {
        d: "M" + vx + "," + vy + " L" + x + "," + VIEW_H,
        stroke: ACCENT, "stroke-width": "0.8", opacity: "0.045"
      }));
    }
    [756, 776, 802, 836, 880].forEach(function (y, i) {
      floorLines.appendChild(el("path", {
        d: "M0," + y + " L" + VIEW_W + "," + y,
        stroke: ACCENT, "stroke-width": "0.8", opacity: (0.09 - i * 0.012).toFixed(3)
      }));
    });
    g.appendChild(floorLines);

    /* 看板往下打的一团柔光：把看板与工位连起来，墙不至于空 */
    g.appendChild(el("ellipse", { cx: 800, cy: 560, rx: 470, ry: 330, fill: "url(#lightCone)" }));

    /* 工位在地面上的冷色反光 */
    [470, 1010].forEach(function (x) {
      g.appendChild(el("ellipse", { cx: x, cy: FLOOR + 10, rx: 250, ry: 34, fill: "url(#deskReflect)" }));
      /* 桌面在地面的倒影：一条被拉长的冷光 */
      g.appendChild(el("ellipse", { cx: x, cy: FLOOR + 26, rx: 190, ry: 12, fill: "url(#deskReflect)" }));
    });

    /* 极淡的漂浮粒子 */
    var dots = el("g", { class: "bg-dots" });
    [[120, 300, 1.6], [300, 180, 1.2], [1330, 240, 1.5], [1480, 420, 1.2], [640, 120, 1.1],
     [980, 330, 1.4], [1420, 130, 1.0], [180, 520, 1.3]].forEach(function (d, i) {
      dots.appendChild(el("circle", {
        cx: d[0], cy: d[1], r: d[2], fill: ACCENT, opacity: "0.28",
        class: "dust d" + (i % 4)
      }));
    });
    g.appendChild(dots);

    return g;
  }

  /* ---------------- 任务看板 ---------------- */

  function clearStages(g) {
    Array.prototype.slice.call(g.querySelectorAll(".stage, .stage-link")).forEach(function (n) {
      n.parentNode.removeChild(n);
    });
  }

  function createStages(g, list) {
    clearStages(g);
    var x0 = 40, x1 = 740, n = list.length;
    var step = n > 1 ? Math.min(116, (x1 - x0) / (n - 1)) : 0;
    var start = n > 1 ? 800 / 2 - (step * (n - 1)) / 2 : 400;

    return list.map(function (s, i) {
      var x = start + i * step;
      var node = el("g", { class: "stage", "data-stage": s.id, transform: "translate(" + x + ",140)" }, [
        i < n - 1 ? el("path", { d: "M14,0 L" + (step - 14) + ",0", class: "stage-link" }) : null,
        el("circle", { class: "stage-halo", cx: 0, cy: 0, r: 15 }),
        el("circle", { class: "stage-ring", cx: 0, cy: 0, r: 9 }),
        el("circle", { class: "stage-dot", cx: 0, cy: 0, r: 4 }),
        t(0, 34, s.short || s.label, { class: "stage-label", "text-anchor": "middle" })
      ]);
      g.appendChild(node);
      return node;
    });
  }

  function buildBoard() {
    var b = LAYOUT.board;
    var g = el("g", { class: "layer-board", transform: "translate(" + b.x + "," + b.y + ")" });

    /* 外发光壳 */
    g.appendChild(el("rect", { x: -6, y: -6, width: b.w + 12, height: b.h + 12, rx: 22, class: "board-aura" }));
    g.appendChild(el("rect", { x: 0, y: 0, width: b.w, height: b.h, rx: 18, class: "board-shell" }));
    g.appendChild(el("rect", { x: 1, y: 1, width: b.w - 2, height: b.h - 2, rx: 17, class: "board-inner" }));

    /* 四角科技括号 */
    [[16, 16, 1, 1], [b.w - 16, 16, -1, 1], [16, b.h - 16, 1, -1], [b.w - 16, b.h - 16, -1, -1]]
      .forEach(function (c) {
        g.appendChild(el("path", {
          d: "M" + c[0] + "," + (c[1] + 16 * c[3]) + " L" + c[0] + "," + c[1] + " L" + (c[0] + 16 * c[2]) + "," + c[1],
          fill: "none", stroke: ACCENT, "stroke-width": "1.6", opacity: "0.55"
        }));
      });

    g.appendChild(t(28, 38, "TASK  PROGRESS", { class: "board-kicker" }));

    var title = t(28, 70, "等待任务", { class: "board-title" });
    g.appendChild(title);
    var sub = t(28, 94, "小鲸常驻 P1，小鱼在 P2 与待命区之间往返", { class: "board-sub" });
    g.appendChild(sub);

    var pct = t(b.w - 28, 62, "0%", { class: "board-pct", "text-anchor": "end" });
    g.appendChild(pct);
    g.appendChild(t(b.w - 28, 80, "COMPLETE", { class: "board-pct-label", "text-anchor": "end" }));

    /* 进度轨 */
    g.appendChild(el("rect", { x: 40, y: 138.5, width: 720, height: 3, rx: 1.5, class: "board-track" }));
    var trackFill = el("rect", { x: 40, y: 138.5, width: 0, height: 3, rx: 1.5, class: "board-track-fill" });
    g.appendChild(trackFill);

    var stages = createStages(g, STAGES);

    g.appendChild(el("rect", { x: 40, y: 206, width: 720, height: 1, class: "board-rule" }));
    var footer = t(40, 236, "已用 00:00  ·  预算 $0.000", { class: "board-foot" });
    g.appendChild(footer);
    var crew = t(b.w - 40, 236, "小鲸 + 小鱼  ·  双人协作", { class: "board-foot", "text-anchor": "end" });
    g.appendChild(crew);

    return {
      node: g, stages: stages, footer: footer, title: title, sub: sub, pct: pct,
      trackFill: trackFill, crew: crew
    };
  }

  /* ---------------- 出图台 ---------------- */

  function buildPlotter() {
    var p = LAYOUT.plotter;
    var g = el("g", { class: "layer-plotter", transform: "translate(" + p.x + "," + p.y + ")" });
    g.appendChild(el("defs", null, [
      el("clipPath", { id: "paperClip" }, [
        el("rect", { class: "paper-clip", x: -70, y: 128, width: 140, height: 0 })
      ])
    ]));
    g.appendChild(el("rect", { x: -96, y: 0, width: 192, height: 132, rx: 10, class: "plotter-body" }));
    g.appendChild(el("rect", { x: -88, y: 10, width: 176, height: 1, class: "plotter-edge" }));
    g.appendChild(el("rect", { x: -82, y: 20, width: 164, height: 48, rx: 4, class: "plotter-screen" }));
    g.appendChild(t(0, 50, "PLOTTER", { class: "plotter-title", "text-anchor": "middle" }));
    g.appendChild(el("circle", { cx: 74, cy: 108, r: 4, class: "plotter-led" }));
    g.appendChild(el("rect", { x: -72, y: 112, width: 144, height: 10, rx: 4, class: "plotter-slot" }));

    var paper = el("g", { class: "plotter-paper", "clip-path": "url(#paperClip)" }, [
      el("rect", { x: -70, y: 120, width: 140, height: 170, rx: 2, class: "paper-sheet" }),
      el("path", { d: "M-56,150 L10,150 L34,132 L56,150 L-56,150", class: "paper-chart" }),
      el("path", { d: "M-56,168 L-30,158 L-4,168 L22,150 L48,160", class: "paper-chart thin" }),
      el("rect", { x: -56, y: 190, width: 84, height: 3, rx: 1.5, class: "thumb" }),
      el("rect", { x: -56, y: 200, width: 108, height: 3, rx: 1.5, class: "thumb" }),
      el("rect", { x: -56, y: 210, width: 62, height: 3, rx: 1.5, class: "thumb" })
    ]);
    g.appendChild(paper);
    var scan = el("rect", { x: -70, y: 120, width: 140, height: 2, class: "plotter-scan" });
    g.appendChild(scan);
    var caption = t(0, 306, "图表由已校验数据确定性渲染", { class: "plotter-caption", "text-anchor": "middle" });
    g.appendChild(caption);
    return { node: g, paper: paper, scan: scan, caption: caption };
  }

  /* ---------------- 邮筒 ---------------- */

  function buildMailbox() {
    var x = LAYOUT.mailbox;
    var g = el("g", { class: "layer-mailbox", transform: "translate(" + x + ",0)" });
    g.appendChild(el("rect", { x: -28, y: 636, width: 56, height: 104, rx: 8, class: "mailbox-body" }));
    g.appendChild(el("rect", { x: -28, y: 636, width: 56, height: 16, rx: 8, class: "mailbox-cap" }));
    g.appendChild(el("rect", { x: -16, y: 660, width: 32, height: 5, rx: 2.5, class: "mailbox-slot" }));
    g.appendChild(el("circle", { cx: 0, cy: 692, r: 7, class: "mailbox-lens" }));
    g.appendChild(el("rect", { x: -34, y: 736, width: 68, height: 8, rx: 3, class: "mailbox-base" }));

    var ripples = el("g", { class: "mail-ripples" });
    for (var i = 0; i < 3; i++) {
      ripples.appendChild(el("circle", { cx: 0, cy: 662, r: 10, class: "ripple r" + i }));
    }
    g.appendChild(ripples);

    var badge = el("g", { class: "mail-badge", opacity: "0" }, [
      el("rect", { x: -54, y: 596, width: 108, height: 24, rx: 12, class: "mail-badge-bg" }),
      t(0, 613, "", { class: "mail-badge-text", "text-anchor": "middle" })
    ]);
    g.appendChild(badge);

    return { node: g, ripples: ripples, badge: badge, badgeText: badge.querySelector(".mail-badge-text") };
  }

  /* ---------------- 待命区 ---------------- */

  function buildLounge() {
    var g = el("g", { class: "layer-lounge", transform: "translate(1400,0)" });
    g.appendChild(el("ellipse", { cx: 0, cy: FLOOR + 16, rx: 160, ry: 26, class: "rug" }));
    g.appendChild(el("ellipse", { cx: 0, cy: FLOOR + 16, rx: 122, ry: 16, class: "rug-inner" }));
    /* 边几 + 杯 */
    g.appendChild(el("ellipse", { cx: 166, cy: FLOOR - 52, rx: 26, ry: 8, class: "table-top" }));
    g.appendChild(el("rect", { x: 162, y: FLOOR - 52, width: 6, height: 52, class: "table-leg" }));
    g.appendChild(el("rect", { x: 190, y: FLOOR - 52, width: 6, height: 52, class: "table-leg" }));
    g.appendChild(el("rect", { x: 174, y: FLOOR - 70, width: 12, height: 18, rx: 2, class: "mug" }));
    g.appendChild(t(0, FLOOR + 62, "待命区 · STANDBY", { class: "lounge-label", "text-anchor": "middle" }));
    return g;
  }

  /* ---------------- 工位 ---------------- */

  /* 显示器屏幕：标题 / 进度条 / 滚动数据 / 状态 */
  function buildScreen(mid, w, h, name) {
    var g = el("g", { class: "screen" });
    g.appendChild(el("defs", null, [
      el("clipPath", { id: "sc-" + mid }, [
        el("rect", { x: -w / 2 + 10, y: 40, width: w - 20, height: 52 })
      ])
    ]));
    g.appendChild(el("rect", { x: -w / 2 + 6, y: 6, width: w - 12, height: h - 12, rx: 3, class: "screen-face" }));

    var nameNode = t(-w / 2 + 12, 22, name, { class: "screen-name" });
    g.appendChild(nameNode);
    var pct = t(w / 2 - 12, 22, "0%", { class: "screen-pct", "text-anchor": "end" });
    g.appendChild(pct);

    g.appendChild(el("rect", { x: -w / 2 + 10, y: 30, width: w - 20, height: 5, rx: 2.5, class: "screen-track" }));
    var bar = el("rect", { x: -w / 2 + 10, y: 30, width: 0, height: 5, rx: 2.5, class: "screen-bar" });
    g.appendChild(bar);

    /* 滚动数据：一整组方块往上走，裁剪窗只露三行 */
    var rows = el("g", { class: "screen-rows", "clip-path": "url(#sc-" + mid + ")" });
    var inner = el("g", { class: "screen-rows-inner" });
    [[1, 3], [0.72, 3], [0.86, 3], [0.58, 3], [0.9, 3], [0.66, 3], [0.8, 3], [0.5, 3]].forEach(function (r, i) {
      inner.appendChild(el("rect", {
        x: -w / 2 + 10, y: 42 + i * 9, width: (w - 20) * r[0], height: r[1], rx: 1.5,
        class: i % 3 === 0 ? "screen-row hot" : "screen-row"
      }));
    });
    rows.appendChild(inner);
    g.appendChild(rows);

    var status = t(-w / 2 + 12, h - 16, "IDLE", { class: "screen-status" });
    g.appendChild(status);

    return { node: g, bar: bar, pct: pct, status: status, nameNode: nameNode, barW: w - 20, rowsInner: inner };
  }

  function buildDesk(key) {
    var seat = LAYOUT.seats[key];
    var w = seat.w, hw = w / 2;
    var xf = "translate(" + seat.x + "," + FLOOR + ")";

    var back = el("g", { class: "desk desk-back", "data-seat": key, transform: xf });

    /* 屏幕打在墙上的溢光：把工位从深空底里拎出来 */
    back.appendChild(el("ellipse", { cx: 40, cy: -150, rx: 300, ry: 210, fill: "url(#deskGlow)" }));
    /* 地面投影 */
    back.appendChild(el("ellipse", { cx: 0, cy: 4, rx: 240, ry: 16, class: "desk-shadow" }));

    /* 椅子 */
    back.appendChild(el("rect", { x: -56, y: -196, width: 112, height: 96, rx: 16, class: "chair-back" }));
    back.appendChild(el("rect", { x: -60, y: -104, width: 120, height: 14, rx: 6, class: "chair-seat" }));
    back.appendChild(el("path", { d: "M-52,-92 L-52,0", class: "chair-post" }));
    back.appendChild(el("path", { d: "M52,-92 L52,0", class: "chair-post" }));

    /* 显示器 */
    var mx = 172, mw = 150, mh = 116, mtop = -272;
    back.appendChild(el("rect", { x: mx - 7, y: mtop + mh, width: 14, height: 22, class: "monitor-neck" }));
    back.appendChild(el("rect", { x: mx - 30, y: -132, width: 60, height: 8, rx: 3, class: "monitor-foot" }));
    back.appendChild(el("rect", { x: mx - mw / 2 - 4, y: mtop - 4, width: mw + 8, height: mh + 8, rx: 9, class: "monitor-shell" }));
    back.appendChild(el("rect", { x: mx - mw / 2, y: mtop, width: mw, height: mh, rx: 6, class: "monitor-glass" }));
    var screen = buildScreen(key, mw, mh, seat.code + " · " + seat.name);
    screen.node.setAttribute("transform", "translate(" + mx + "," + mtop + ")");
    back.appendChild(screen.node);
    back.appendChild(el("rect", { x: mx - mw / 2, y: mtop - 4, width: mw, height: 2, rx: 1, class: "monitor-glow" }));

    /* 鼠标留在远侧，键盘改到桌面之前画（见 desk-front） */
    back.appendChild(el("rect", { x: -92, y: -140, width: 18, height: 7, rx: 2, class: "mouse" }));

    /* 桌面小物 */
    back.appendChild(el("rect", { x: -hw + 40, y: -160, width: 16, height: 20, rx: 3, class: "mug" }));
    back.appendChild(el("path", { d: "M" + (-hw + 56) + ",-154 C" + (-hw + 62) + ",-154 " + (-hw + 62) + ",-146 " + (-hw + 56) + ",-146", class: "mug-handle" }));
    back.appendChild(el("rect", { x: -hw + 66, y: -152, width: 30, height: 18, rx: 2, class: "notepad" }));
    back.appendChild(el("path", { d: "M" + (-hw + 72) + ",-146 L" + (-hw + 90) + ",-146", class: "notepad-line" }));
    back.appendChild(el("path", { d: "M" + (-hw + 72) + ",-141 L" + (-hw + 84) + ",-141", class: "notepad-line" }));

    /* 桌面：正面看就是一条带厚度的板 + 挡板 */
    var front = el("g", { class: "desk desk-front", "data-seat": key, transform: xf });
    front.appendChild(el("rect", { x: -hw, y: -136, width: w, height: 18, rx: 4, class: "desk-top" }));
    /* 键位条：一条带青蓝背光的窄条，紧贴角色手的下方，作用等同于「键盘在发光」 */
    front.appendChild(el("rect", { x: -66, y: -137, width: 132, height: 7, rx: 2, class: "keyboard" }));
    for (var i = 0; i < 13; i++) {
      front.appendChild(el("path", { d: "M" + (-56 + i * 9) + ",-135 L" + (-56 + i * 9) + ",-132.4", class: "key-line" }));
    }
    front.appendChild(el("rect", { x: -hw, y: -136, width: w, height: 2.4, class: "desk-top-edge" }));
    front.appendChild(el("rect", { x: -hw + 14, y: -118, width: 14, height: 118, class: "desk-leg" }));
    front.appendChild(el("rect", { x: hw - 28, y: -118, width: 14, height: 118, class: "desk-leg" }));
    front.appendChild(el("rect", { x: -hw + 28, y: -118, width: w - 56, height: 86, rx: 3, class: "desk-apron" }));
    front.appendChild(el("rect", { x: -hw + 28, y: -118, width: w - 56, height: 1.4, class: "desk-apron-edge" }));
    /* 桌裙上的细横刻线，读作「金属面板」 */
    [-96, -74, -52].forEach(function (y) {
      front.appendChild(el("path", { d: "M" + (-hw + 40) + "," + y + " L" + (hw - 40) + "," + y, class: "desk-score" }));
    });

    /* 铭牌：名字 + 状态灯 + 角色进度条 */
    var plaque = el("g", { class: "plaque" }, [
      el("rect", { x: -86, y: -112, width: 172, height: 30, rx: 4, class: "plaque-bg" }),
      el("circle", { cx: -70, cy: -97, r: 4, class: "status-lamp" })
    ]);
    var nameText = t(-58, -97, seat.name + " · " + seat.code, { class: "plaque-name" });
    plaque.appendChild(nameText);
    plaque.appendChild(el("rect", { x: -58, y: -92, width: 130, height: 2.6, rx: 1.3, class: "bar-track" }));
    var barFill = el("rect", { x: -58, y: -92, width: 0, height: 2.6, rx: 1.3, class: "bar-fill" });
    plaque.appendChild(barFill);
    front.appendChild(plaque);

    return {
      node: front, back: back, front: front, bar: barFill, label: seat.name,
      nameText: nameText, screen: screen, screenNode: screen.node,
      plaque: plaque
    };
  }

  /* ---------------- 前景 ---------------- */

  function buildForeground() {
    var g = el("g", { class: "layer-foreground" });
    /* 左下角盆栽：低多边形，深灰 + 青边 */
    g.appendChild(el("path", { d: "M22,742 L74,742 L68,806 L28,806 Z", class: "pot" }));
    g.appendChild(el("path", { d: "M48,742 L48,700", class: "plant-stem" }));
    [[30, 706, -34], [66, 702, 30], [40, 682, -16], [58, 676, 18], [48, 662, 0]].forEach(function (p) {
      g.appendChild(el("path", {
        d: "M48,706 L" + p[0] + "," + p[1] + " L" + (p[0] + 16) + "," + (p[1] + 10) + " Z",
        class: "leaf", transform: "rotate(" + p[2] + " 48 706)"
      }));
    });
    g.appendChild(el("path", { d: "M1468,806 L1560,806 L1548,742 L1480,742 Z", class: "pot" }));
    g.appendChild(el("path", { d: "M1506,742 L1506,690", class: "plant-stem" }));
    [[1480, 700, -28], [1534, 698, 26], [1506, 672, 0]].forEach(function (p) {
      g.appendChild(el("path", {
        d: "M1506,742 L" + p[0] + "," + p[1] + " L" + (p[0] + 18) + "," + (p[1] + 12) + " Z",
        class: "leaf", transform: "rotate(" + p[2] + " 1506 742)"
      }));
    });
    /* 暗角 */
    g.appendChild(el("rect", { x: 0, y: 0, width: VIEW_W, height: VIEW_H, fill: "url(#vignette)", "pointer-events": "none" }));
    return g;
  }

  /* 待命区名签 */
  function buildTag(key) {
    var v = window.Actors.VARIANTS[key];
    var w = 28 + v.name.length * 14;
    var g = el("g", { class: "actor-tag", "data-key": key });
    g.appendChild(el("rect", { x: -w / 2, y: 0, width: w, height: 22, rx: 11, class: "actor-tag-bg" }));
    g.appendChild(el("circle", { cx: -w / 2 + 13, cy: 11, r: 3.6, class: "actor-tag-dot" }));
    g.appendChild(t(-w / 2 + 22, 15.5, v.name, { class: "actor-tag-text" }));
    return { node: g };
  }

  /* ---------------- defs ---------------- */

  function buildDefs() {
    return el("defs", null, [
      el("linearGradient", { id: "wallGrad", x1: "0", y1: "0", x2: "0.2", y2: "1" }, [
        el("stop", { offset: "0", "stop-color": "#101A29" }),
        el("stop", { offset: "0.5", "stop-color": "#0C1422" }),
        el("stop", { offset: "1", "stop-color": "#080D16" })
      ]),
      el("linearGradient", { id: "floorGrad", x1: "0", y1: "0", x2: "0", y2: "1" }, [
        el("stop", { offset: "0", "stop-color": "#080C14" }),
        el("stop", { offset: "1", "stop-color": "#04060B" })
      ]),
      el("radialGradient", { id: "glowTop", cx: "0.5", cy: "0.5", r: "0.5" }, [
        el("stop", { offset: "0", "stop-color": ACCENT, "stop-opacity": "0.14" }),
        el("stop", { offset: "1", "stop-color": ACCENT, "stop-opacity": "0" })
      ]),
      el("radialGradient", { id: "glowLeft", cx: "0.5", cy: "0.5", r: "0.5" }, [
        el("stop", { offset: "0", "stop-color": "#1E5FA8", "stop-opacity": "0.16" }),
        el("stop", { offset: "1", "stop-color": "#1E5FA8", "stop-opacity": "0" })
      ]),
      el("radialGradient", { id: "glowRight", cx: "0.5", cy: "0.5", r: "0.5" }, [
        el("stop", { offset: "0", "stop-color": "#2A3FA0", "stop-opacity": "0.14" }),
        el("stop", { offset: "1", "stop-color": "#2A3FA0", "stop-opacity": "0" })
      ]),
      el("radialGradient", { id: "lightCone", cx: "0.5", cy: "0.5", r: "0.5" }, [
        el("stop", { offset: "0", "stop-color": ACCENT, "stop-opacity": "0.09" }),
        el("stop", { offset: "0.5", "stop-color": ACCENT, "stop-opacity": "0.045" }),
        el("stop", { offset: "1", "stop-color": ACCENT, "stop-opacity": "0" })
      ]),
      el("radialGradient", { id: "deskGlow", cx: "0.5", cy: "0.5", r: "0.5" }, [
        el("stop", { offset: "0", "stop-color": ACCENT, "stop-opacity": "0.13" }),
        el("stop", { offset: "0.55", "stop-color": ACCENT, "stop-opacity": "0.05" }),
        el("stop", { offset: "1", "stop-color": ACCENT, "stop-opacity": "0" })
      ]),
      el("radialGradient", { id: "deskReflect", cx: "0.5", cy: "0.5", r: "0.5" }, [
        el("stop", { offset: "0", "stop-color": ACCENT, "stop-opacity": "0.18" }),
        el("stop", { offset: "0.6", "stop-color": ACCENT, "stop-opacity": "0.06" }),
        el("stop", { offset: "1", "stop-color": ACCENT, "stop-opacity": "0" })
      ]),
      el("linearGradient", { id: "horizonGlow", x1: "0", y1: "0", x2: "0", y2: "1" }, [
        el("stop", { offset: "0", "stop-color": ACCENT, "stop-opacity": "0.18" }),
        el("stop", { offset: "0.6", "stop-color": ACCENT, "stop-opacity": "0.06" }),
        el("stop", { offset: "1", "stop-color": ACCENT, "stop-opacity": "0" })
      ]),
      el("radialGradient", { id: "vignette", cx: "0.5", cy: "0.48", r: "0.72" }, [
        el("stop", { offset: "0.6", "stop-color": "#000000", "stop-opacity": "0" }),
        el("stop", { offset: "1", "stop-color": "#000000", "stop-opacity": "0.38" })
      ]),
      el("pattern", { id: "gridPat", width: "44", height: "44", patternUnits: "userSpaceOnUse" }, [
        el("path", { d: "M44,0 L0,0 L0,44", fill: "none", stroke: ACCENT, "stroke-width": "1", opacity: "0.09" })
      ]),
      el("linearGradient", { id: "gridFade", x1: "0", y1: "0", x2: "0", y2: "1" }, [
        el("stop", { offset: "0", "stop-color": "#FFFFFF", "stop-opacity": "0.9" }),
        el("stop", { offset: "0.55", "stop-color": "#FFFFFF", "stop-opacity": "0.55" }),
        el("stop", { offset: "1", "stop-color": "#FFFFFF", "stop-opacity": "0.1" })
      ]),
      el("mask", { id: "gridMask" }, [
        el("rect", { x: 0, y: 0, width: VIEW_W, height: FLOOR, fill: "url(#gridFade)" })
      ])
    ]);
  }

  /* ---------------- 装配 ---------------- */

  function mount(svg) {
    root = svg;
    root.setAttribute("viewBox", "0 0 " + VIEW_W + " " + VIEW_H);
    root.setAttribute("preserveAspectRatio", "xMidYMid meet");
    root.setAttribute("role", "img");
    root.setAttribute("aria-label", "办公区：小鲸与小鱼的两台工位与实时任务进度");

    root.appendChild(buildDefs());

    layers.backdrop = buildBackdrop();
    layers.board = buildBoard();
    layers.plotter = buildPlotter();
    layers.lounge = buildLounge();
    layers.mailbox = buildMailbox();
    parts.board = layers.board;
    parts.plotter = layers.plotter;
    parts.mailbox = layers.mailbox;

    layers.deskBack = el("g", { class: "layer-desk-back" });
    layers.actorsSeated = el("g", { class: "layer-actors-seated" });
    layers.actorsWalk = el("g", { class: "layer-actors-walk" });
    layers.deskFront = el("g", { class: "layer-desk-front" });
    layers.tags = el("g", { class: "layer-tags" });
    layers.foreground = buildForeground();

    ["main", "sub"].forEach(function (key) {
      var desk = buildDesk(key);
      parts.desks[key] = desk;
      layers.deskBack.appendChild(desk.back);
      layers.deskFront.appendChild(desk.front);
    });

    /* 走位层放在桌面之后、桌裙之前：走过去时人被桌子挡住，落座后再浮出来 */
    [layers.backdrop, layers.board.node, layers.plotter.node, layers.lounge,
      layers.deskBack, layers.actorsSeated, layers.actorsWalk, layers.deskFront,
      layers.tags, layers.mailbox.node, layers.foreground].forEach(function (l) { root.appendChild(l); });

    ["main", "sub"].forEach(function (key) {
      var built = window.Actors.build(key);
      var node = built.node;
      var x = LAYOUT.lounge[key];
      var y = LAYOUT.loungeY[key];
      var tag = buildTag(key);
      actors[key] = {
        key: key, node: node, variant: built.variant, tag: tag,
        status: "idle", x: x, y: y, layer: "walk",
        scale: key === "main" ? ACTOR_SCALE : LOUNGE_SCALE
      };
      node.setAttribute("transform", "translate(" + x + "," + y + ") scale(" + actors[key].scale + ")");
      tag.node.setAttribute("transform", "translate(" + x + "," + (y + 6) + ")");
      if (key === "main") tag.node.setAttribute("opacity", "0");
      layers.actorsWalk.appendChild(node);
      layers.tags.appendChild(tag.node);
    });

    return { actors: actors, parts: parts, layout: LAYOUT };
  }

  /* ---------------- 行为 ---------------- */

  var walkToken = {};

  function seatKey(key) { return key === "main" ? "main" : "sub"; }
  function seatOf(key) { return LAYOUT.seats[seatKey(key)]; }

  function setSeatLabel(key) {
    var v = window.Actors.VARIANTS[key];
    if (!v || !parts.desks.sub) return;
    parts.desks.sub.nameText.textContent = v.name + " · " + LAYOUT.seats.sub.code;
    parts.desks.sub.node.setAttribute("data-occupant", key);
    parts.desks.sub.screen.nameNode.textContent = LAYOUT.seats.sub.code + " · " + v.name;
  }

  function resetSeatLabel() {
    if (!parts.desks.sub) return;
    parts.desks.sub.nameText.textContent = LAYOUT.seats.sub.name + " · " + LAYOUT.seats.sub.code;
    parts.desks.sub.node.removeAttribute("data-occupant");
    parts.desks.sub.screen.nameNode.textContent = LAYOUT.seats.sub.code + " · " + LAYOUT.seats.sub.name;
  }

  function place(actor, x, y, scale) {
    actor.x = x; actor.y = y;
    var s = scale === undefined ? (actor.scale || ACTOR_SCALE) : scale;
    actor.node.setAttribute("transform", "translate(" + x + "," + y + ") scale(" + s + ")");
    if (actor.tag) actor.tag.node.setAttribute("transform", "translate(" + x + "," + (y + 6) + ")");
  }

  function settle(key) { layerOf(actors[key], "seated"); }

  function layerOf(actor, name) {
    if (actor.layer !== name) {
      actor.layer = name;
      layers[name === "walk" ? "actorsWalk" : "actorsSeated"].appendChild(actor.node);
    }
    /* 落座后名签交给桌面铭牌 */
    if (actor.tag) actor.tag.node.setAttribute("opacity", name === "seated" ? "0" : "1");
  }

  /* seated=false 表示「走到待命区」：落点留在行走层，名签保留 */
  function walk(actor, targetX, targetY, duration, done, targetScale, seated) {
    var token = (walkToken[actor.key] = (walkToken[actor.key] || 0) + 1);
    var fromX = actor.x, fromY = actor.y, start = performance.now();
    var fromScale = actor.scale || ACTOR_SCALE;
    var toScale = targetScale || ACTOR_SCALE;
    var arriveSeated = seated !== false;
    actor.scale = toScale;
    layerOf(actor, "walk");
    actor.node.classList.add("is-walking");
    if (window.Actors.setPose) window.Actors.setPose(actor.node, "stand");
    if (actor.tag) actor.tag.node.setAttribute("opacity", "0");
    if (actor.raf) cancelAnimationFrame(actor.raf);

    function frame(now) {
      if (walkToken[actor.key] !== token) return;
      var k = duration <= 0 ? 1 : Math.min(1, (now - start) / duration);
      var e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
      place(actor, fromX + (targetX - fromX) * e, fromY + (targetY - fromY) * e,
        fromScale + (toScale - fromScale) * e);
      if (k < 1) {
        actor.raf = requestAnimationFrame(frame);
      } else {
        actor.raf = null;
        actor.node.classList.remove("is-walking");
        if (window.Actors.setPose) window.Actors.setPose(actor.node, arriveSeated ? "sit" : "stand");
        layerOf(actor, arriveSeated ? "seated" : "walk");
        if (done) done();
      }
    }
    actor.raf = requestAnimationFrame(frame);
  }

  function cancelWalk(actor) {
    walkToken[actor.key] = (walkToken[actor.key] || 0) + 1;
    if (actor.raf) cancelAnimationFrame(actor.raf);
    actor.raf = null;
    actor.node.classList.remove("is-walking");
    if (window.Actors.setPose) window.Actors.setPose(actor.node, "sit");
  }

  function setStatus(actor, status) {
    actor.status = status;
    actor.node.setAttribute("data-status", status);
    var desk = parts.desks[seatKey(actor.key)];
    if (desk) desk.node.setAttribute("data-status", status);
  }

  function setTyping(actor, on) {
    if (window.Actors.setTyping) window.Actors.setTyping(actor.node, on);
    var desk = parts.desks[seatKey(actor.key)];
    if (desk) {
      desk.node.setAttribute("data-typing", on ? "1" : "0");
      desk.front.setAttribute("data-typing", on ? "1" : "0");
    }
  }

  /* 工位屏幕联动：pct 0-100，label 状态文案，tone 色调 */
  function screen(key, pct, label, tone) {
    var desk = parts.desks[seatKey(key)];
    if (!desk || !desk.screen) return;
    var s = desk.screen;
    var v = Math.max(0, Math.min(100, pct || 0));
    s.bar.setAttribute("width", (s.barW * v / 100).toFixed(1));
    s.pct.textContent = Math.round(v) + "%";
    if (label) s.status.textContent = label;
    desk.node.setAttribute("data-tone", tone || "idle");
    desk.screenNode.setAttribute("data-tone", tone || "idle");
  }

  function deskBar(key, pct) {
    var desk = parts.desks[seatKey(key)];
    if (desk && desk.bar) desk.bar.setAttribute("width", (130 * Math.max(0, Math.min(100, pct)) / 100).toFixed(1));
  }

  function boardStage(id, status) {
    var node = parts.board.node.querySelector('.stage[data-stage="' + id + '"]');
    if (node) node.setAttribute("data-stage-status", status);
  }

  function setStages(list) {
    if (!parts.board) return;
    parts.board.stages = createStages(parts.board.node, list);
  }

  function boardHead(title, sub) {
    parts.board.title.textContent = title;
    if (sub) parts.board.sub.textContent = sub;
  }

  function boardFooter(text) { parts.board.footer.textContent = text; }

  function boardProgress(pct) {
    var v = Math.max(0, Math.min(100, pct || 0));
    parts.board.pct.textContent = Math.round(v) + "%";
    parts.board.trackFill.setAttribute("width", (720 * v / 100).toFixed(1));
  }

  function boardTag(show) {
    parts.board.node.setAttribute("data-active", show ? "1" : "0");
  }

  return {
    mount: mount, walk: walk, place: place, settle: settle, setStatus: setStatus,
    cancelWalk: cancelWalk, setTyping: setTyping, screen: screen, deskBar: deskBar,
    boardStage: boardStage, boardFooter: boardFooter, boardTag: boardTag, boardProgress: boardProgress,
    setStages: setStages, boardHead: boardHead,
    seatKey: seatKey, seatOf: seatOf, setSeatLabel: setSeatLabel, resetSeatLabel: resetSeatLabel,
    SCALE: ACTOR_SCALE, LOUNGE_SCALE: LOUNGE_SCALE,
    LAYOUT: LAYOUT, STAGES: STAGES, FLOOR: FLOOR,
    get actors() { return actors; },
    get parts() { return parts; }
  };
})();
