/* ===== Actors：办公区角色 · 矢量分层骨骼 =====
 *
 * 对照原画 docs/character-sheet.jpg（05 CHIBI BLUE MAID 正面图）逐部件复刻：
 *   ① 深蓝→浅天蓝的渐变长发，波浪外缘，两根侧发垂到胯部
 *   ② 白色荷叶边发带 + 浅蓝蝴蝶结（画面右侧）
 *   ③ 两侧鳍状耳，扇形，带深浅分层
 *   ④ 藏青长袖连衣裙，白色蕾丝袖口，白色圆领 + 藏青领结
 *   ⑤ 白色荷叶边围裙，围裙上有一枚小鲸刺绣
 *   ⑥ 裙摆下缘一道印花样饰带 + 白色蕾丝花边
 *   ⑦ 白袜 + 藏青玛丽珍鞋
 *   ⑧ 一条鲸尾从身后偏右伸出
 *
 * 为什么不用位图：位图只能整体平移，做不出「手在键盘上敲」。
 * 这里用分层矢量骨骼，代价是质感比原画弱，换来真的骨骼动画：
 *
 *   .actor
 *     .a-body
 *       .a-tail          鲸尾（最后面）
 *       .a-hair-back     后发
 *       .a-legs          双腿（落座时淡出）
 *       .a-torso         呼吸 / 打字微晃
 *         <裙与上衣>
 *         .a-hair-side   侧发（压在肩前）
 *         .a-arm × 2     肩为轴旋转
 *           .a-arm-art
 *             <上臂>
 *             .a-fore    肘为轴（落座时折到桌面上）
 *               <前臂 + 手>
 *               .a-hand  腕为轴，点击
 *         .a-head        脸 / 眼 / 刘海 / 发带 / 鳍耳
 *
 * 旋转原点：SVG 里给 <g> 做 CSS rotate，默认原点不是肩点。这里给每个旋转组塞
 * 一个透明的「bbox 栓」矩形让包围盒关于枢轴对称，再用
 * transform-box: fill-box + transform-origin: 50% 0% 把原点锁死。
 *
 * 坐标约定：脚底 y=0，向上为负，全身高约 356（呆毛到 378）。
 */
window.Actors = (function () {
  "use strict";

  var NS = "http://www.w3.org/2000/svg";
  var UNIT = 360;

  /* 两位角色造型完全一致，只换发色与强调色：
   * 小鲸 = 原画那套靛蓝 / 小鱼 = 夜潮紫青，便于在场景里区分 */
  var VARIANTS = {
    main: {
      key: "main", name: "小鲸", code: "WHALE-01", role: "主 Agent · 规划与汇总", seat: "P1",
      accent: "#16D3E6",
      hair: ["#33427F", "#4A63A8", "#8FBCE2"], hairDeep: "#202A55", hairLite: "#BBDCF2",
      dress: "#232E5C", dressDeep: "#141B39", dressLite: "#33417A",
      lace: "#FFFFFF", laceShade: "#DCE6F4",
      ribbon: "#6FB8E8", ribbonDeep: "#4187BE", tie: "#1B2547", tieLite: "#2A3768",
      skin: "#FCE6DA", skinShade: "#EDBFAC",
      eye: ["#2C5F9E", "#4E9BD8", "#A8E8FA"], pupil: "#16324F",
      fin: "#5C6C9A", finLite: "#8291B8", finEdge: "#3F4B70",
      shoe: "#1E2A55", shoeLite: "#32437D",
      blush: "#F0A9B3"
    },
    sub: {
      key: "sub", name: "小鱼", code: "FISH-02", role: "协作 Agent · 分支分析", seat: "P2",
      accent: "#8A7BFF",
      hair: ["#3E3878", "#5C56A8", "#A79EDC"], hairDeep: "#26244F", hairLite: "#CFC8F0",
      dress: "#262C55", dressDeep: "#161936", dressLite: "#38406F",
      lace: "#FFFFFF", laceShade: "#E2E2F4",
      ribbon: "#8A7BFF", ribbonDeep: "#6656E0", tie: "#1C1D44", tieLite: "#2E2F66",
      skin: "#FCE6DA", skinShade: "#EDBFAC",
      eye: ["#4A4E9E", "#7B78D8", "#D8D4FF"], pupil: "#221F4E",
      fin: "#6E67A2", finLite: "#9990C6", finEdge: "#4B4478",
      shoe: "#23255A", shoeLite: "#383F80",
      blush: "#F0A9B3"
    }
  };

  function el(tag, attrs, kids) {
    var node = document.createElementNS(NS, tag);
    if (attrs) {
      for (var k in attrs) {
        if (Object.prototype.hasOwnProperty.call(attrs, k) && attrs[k] !== null && attrs[k] !== undefined) {
          node.setAttribute(k, attrs[k]);
        }
      }
    }
    if (kids) for (var i = 0; i < kids.length; i++) if (kids[i]) node.appendChild(kids[i]);
    return node;
  }

  /* ---------- 渐变：userSpaceOnUse，锚在整身坐标上，
   * 这样后发、刘海、侧发共用同一段「越往下越浅」的过渡，不会各画各的 ---------- */

  function defs(v) {
    var id = v.key;
    return el("defs", null, [
      el("linearGradient", {
        id: "hairGrad-" + id, gradientUnits: "userSpaceOnUse", x1: "0", y1: "-356", x2: "0", y2: "-60"
      }, [
        el("stop", { offset: "0", "stop-color": v.hair[0] }),
        el("stop", { offset: "0.58", "stop-color": v.hair[1] }),
        el("stop", { offset: "0.9", "stop-color": v.hair[2] }),
        el("stop", { offset: "1", "stop-color": v.hairLite })
      ]),
      el("linearGradient", {
        id: "hairGrad2-" + id, gradientUnits: "userSpaceOnUse", x1: "0", y1: "-350", x2: "0", y2: "-250"
      }, [
        el("stop", { offset: "0", "stop-color": v.hair[0] }),
        el("stop", { offset: "0.62", "stop-color": v.hair[1] }),
        el("stop", { offset: "1", "stop-color": v.hair[1] })
      ]),
      el("linearGradient", {
        id: "dressGrad-" + id, gradientUnits: "userSpaceOnUse", x1: "-40", y1: "-182", x2: "40", y2: "-46"
      }, [
        el("stop", { offset: "0", "stop-color": v.dressLite }),
        el("stop", { offset: "0.5", "stop-color": v.dress }),
        el("stop", { offset: "1", "stop-color": v.dressDeep })
      ]),
      el("linearGradient", {
        id: "apronGrad-" + id, gradientUnits: "userSpaceOnUse", x1: "0", y1: "-180", x2: "0", y2: "-50"
      }, [
        el("stop", { offset: "0", "stop-color": "#FFFFFF" }),
        el("stop", { offset: "0.72", "stop-color": "#FBFDFF" }),
        el("stop", { offset: "1", "stop-color": v.laceShade })
      ]),
      el("linearGradient", {
        id: "finGrad-" + id, gradientUnits: "userSpaceOnUse", x1: "0", y1: "-254", x2: "0", y2: "-224"
      }, [
        el("stop", { offset: "0", "stop-color": v.finLite }),
        el("stop", { offset: "1", "stop-color": v.fin })
      ]),
      el("linearGradient", {
        id: "tailGrad-" + id, gradientUnits: "userSpaceOnUse", x1: "20", y1: "-100", x2: "150", y2: "-30"
      }, [
        el("stop", { offset: "0", "stop-color": v.dressDeep }),
        el("stop", { offset: "0.55", "stop-color": v.dress }),
        el("stop", { offset: "1", "stop-color": v.dressLite })
      ]),
      el("radialGradient", { id: "skinGrad-" + id, cx: "0.42", cy: "0.34", r: "0.72" }, [
        el("stop", { offset: "0", "stop-color": "#FFF6EF" }),
        el("stop", { offset: "0.62", "stop-color": v.skin }),
        el("stop", { offset: "1", "stop-color": v.skinShade })
      ]),
      el("linearGradient", { id: "eyeGrad-" + id, x1: "0.5", y1: "0", x2: "0.5", y2: "1" }, [
        el("stop", { offset: "0", "stop-color": v.eye[0] }),
        el("stop", { offset: "0.46", "stop-color": v.eye[1] }),
        el("stop", { offset: "1", "stop-color": v.eye[2] })
      ])
    ]);
  }

  /* ---------- 鲸尾 ---------- */

  function tail(v) {
    var g = el("g", { class: "a-tail" });
    /* 尾柄：从裙后偏右伸出，向右下方弯 */
    g.appendChild(el("path", {
      d: "M22,-108 C64,-118 104,-108 126,-82 C142,-64 148,-42 145,-24 " +
         "C144,-16 134,-14 128,-21 C114,-34 102,-48 92,-58 " +
         "C74,-72 48,-78 24,-76 Z",
      fill: "url(#tailGrad-" + v.key + ")"
    }));
    /* 尾鳍：两瓣 */
    g.appendChild(el("path", {
      d: "M132,-36 C144,-48 156,-50 164,-42 C166,-38 164,-33 160,-32 " +
         "C152,-30 142,-30 136,-26 C132,-22 127,-24 128,-29 Z",
      fill: v.dressLite
    }));
    g.appendChild(el("path", {
      d: "M130,-40 C136,-26 138,-14 134,-4 C133,1 126,2 124,-3 " +
         "C120,-14 120,-26 124,-36 Z",
      fill: v.dress
    }));
    /* 尾背高光 */
    g.appendChild(el("path", {
      d: "M34,-96 C66,-100 96,-92 114,-74", fill: "none",
      stroke: "rgba(255,255,255,0.16)", "stroke-width": "5", "stroke-linecap": "round"
    }));
    return g;
  }

  /* ---------- 后发：一整块蓬松长发，外缘做成波浪 ---------- */

  function hairBack(v) {
    var g = el("g", { class: "a-hair-back" });
    g.appendChild(el("path", {
      d: "M0,-352 " +
         "C38,-354 70,-336 82,-302 " +
         "C88,-284 80,-272 88,-254 " +
         "C98,-236 86,-220 92,-202 " +
         "C100,-184 84,-168 88,-150 " +
         "C92,-132 80,-116 82,-100 " +
         "C84,-86 74,-76 62,-74 " +
         "C44,-72 22,-70 0,-70 " +
         "C-22,-70 -44,-72 -62,-74 " +
         "C-74,-76 -84,-86 -82,-100 " +
         "C-80,-116 -92,-132 -88,-150 " +
         "C-84,-168 -100,-184 -92,-202 " +
         "C-86,-220 -98,-236 -88,-254 " +
         "C-80,-272 -88,-284 -82,-302 " +
         "C-70,-336 -38,-354 0,-352 Z",
      fill: "url(#hairGrad-" + v.key + ")"
    }));
    /* 发丝暗部：几条顺着下垂方向的细线，压出体积 */
    g.appendChild(el("path", { d: "M-64,-260 C-74,-224 -72,-186 -66,-150", fill: "none", stroke: v.hairDeep, "stroke-width": "3", opacity: "0.22" }));
    g.appendChild(el("path", { d: "M64,-260 C74,-224 72,-186 66,-150", fill: "none", stroke: v.hairDeep, "stroke-width": "3", opacity: "0.18" }));
    g.appendChild(el("path", { d: "M-48,-270 C-54,-238 -52,-200 -46,-168", fill: "none", stroke: v.hairDeep, "stroke-width": "2", opacity: "0.14" }));
    /* 顶部釉光 */
    g.appendChild(el("path", { d: "M-46,-330 C-24,-344 22,-344 46,-330", fill: "none", stroke: "rgba(255,255,255,0.3)", "stroke-width": "5", "stroke-linecap": "round" }));
    return g;
  }

  /* ---------- 侧发：压在肩前，垂到胯 ---------- */

  function hairSide(v) {
    var g = el("g", { class: "a-hair-side" });
    /* 左 */
    g.appendChild(el("path", {
      d: "M-70,-268 C-82,-240 -86,-210 -84,-180 " +
         "C-82,-152 -90,-136 -84,-118 C-79,-104 -66,-100 -60,-108 " +
         "C-54,-122 -58,-142 -57,-164 C-56,-196 -58,-234 -62,-262 Z",
      fill: "url(#hairGrad-" + v.key + ")"
    }));
    /* 右 */
    g.appendChild(el("path", {
      d: "M70,-268 C82,-240 86,-210 84,-180 " +
         "C82,-152 90,-136 84,-118 C79,-104 66,-100 60,-108 " +
         "C54,-122 58,-142 57,-164 C56,-196 58,-234 62,-262 Z",
      fill: "url(#hairGrad-" + v.key + ")"
    }));
    /* 内侧一根细发，制造层次 */
    g.appendChild(el("path", {
      d: "M-60,-250 C-70,-220 -72,-190 -70,-164 C-68,-146 -72,-132 -68,-120",
      fill: "none", stroke: v.hairDeep, "stroke-width": "2.4", opacity: "0.2"
    }));
    g.appendChild(el("path", {
      d: "M60,-250 C70,-220 72,-190 70,-164 C68,-146 72,-132 68,-120",
      fill: "none", stroke: v.hairDeep, "stroke-width": "2.4", opacity: "0.2"
    }));
    return g;
  }

  /* ---------- 上衣 / 裙 ---------- */

  function torsoShape(v) {
    var id = v.key;
    var g = el("g", { class: "a-shirt" });

    /* 脖子（短到几乎看不见，但留一点阴影把下巴和领子分开） */
    g.appendChild(el("path", { d: "M-12,-196 L12,-196 L12,-176 L-12,-176 Z", fill: v.skinShade }));

    /* 裙：钟形，下摆最宽处 ±100 */
    g.appendChild(el("path", {
      d: "M-42,-142 L42,-142 " +
         "C56,-120 82,-92 96,-64 " +
         "C102,-55 102,-50 94,-50 L-94,-50 " +
         "C-102,-50 -102,-55 -96,-64 " +
         "C-86,-92 -58,-120 -42,-142 Z",
      fill: "url(#dressGrad-" + id + ")"
    }));
    /* 裙褶：从腰往下发散的几道暗线 */
    [-30, -10, 10, 30].forEach(function (x) {
      g.appendChild(el("path", {
        d: "M" + x + ",-140 L" + (x * 2.9) + ",-56",
        stroke: v.dressDeep, "stroke-width": "2", opacity: "0.35", fill: "none"
      }));
    });

    /* 裙摆饰带：一圈略浅的蓝，带小印花 */
    g.appendChild(el("path", {
      d: "M-96,-76 C-64,-70 -32,-68 0,-68 C32,-68 64,-70 96,-76 " +
         "C97,-72 97,-68 96,-64 C64,-58 32,-56 0,-56 C-32,-56 -64,-58 -96,-64 " +
         "C-97,-68 -97,-72 -96,-76 Z",
      fill: v.dressLite, opacity: "0.92"
    }));
    /* 饰带上的印花：小鲸 / 星星 / 短横 */
    for (var i = -3; i <= 3; i++) {
      var px = i * 24;
      if (i % 2 === 0) {
        g.appendChild(el("path", {
          d: "M" + (px - 4) + ",-64 C" + (px - 1) + ",-68 " + (px + 3) + ",-67 " + (px + 4) + ",-63 " +
             "C" + (px + 2.5) + ",-60 " + (px - 2) + ",-60 " + (px - 4) + ",-64 Z",
          fill: "rgba(255,255,255,0.72)"
        }));
      } else {
        g.appendChild(el("path", { d: "M" + (px - 3) + ",-63 L" + (px + 3) + ",-63", stroke: "rgba(255,255,255,0.5)", "stroke-width": "1.4", "stroke-linecap": "round" }));
      }
    }

    /* 裙摆白蕾丝：一排半圆 */
    g.appendChild(el("path", {
      d: "M-96,-54 L96,-54 C97,-50 94,-48 90,-48 L-90,-48 C-94,-48 -97,-50 -96,-54 Z",
      fill: v.lace
    }));
    for (var j = -12; j <= 12; j++) {
      g.appendChild(el("circle", { cx: j * 7.6, cy: -50, r: 4.4, fill: v.lace }));
    }

    /* 上衣（胸衣）：藏青，方领口 */
    g.appendChild(el("path", {
      d: "M-48,-180 C-52,-164 -54,-152 -54,-142 L54,-142 C54,-152 52,-164 48,-180 Z",
      fill: "url(#dressGrad-" + id + ")"
    }));

    /* 白色围裙：胸前的围兜 + 裙前的一大片 */
    g.appendChild(el("path", {
      d: "M-26,-184 C-30,-166 -33,-152 -35,-142 " +
         "C-42,-122 -50,-102 -54,-92 " +
         "C-55,-86 -53,-82 -48,-82 L48,-82 " +
         "C53,-82 55,-86 54,-92 " +
         "C50,-102 42,-122 35,-142 " +
         "C33,-152 30,-166 26,-184 Z",
      fill: "url(#apronGrad-" + id + ")"
    }));
    /* 围裙荷叶边：沿下缘一圈半圆 */
    for (var k = -5; k <= 5; k++) {
      g.appendChild(el("circle", { cx: k * 9.8, cy: -82 + Math.abs(k) * 0.6, r: 4.6, fill: v.lace }));
    }
    /* 围裙上的小鲸刺绣 */
    g.appendChild(el("g", { transform: "translate(16,-92) scale(1)" }, [
      el("path", {
        d: "M-9,1 C-7,-4 0,-6 5,-4 C8,-3 9,-1 9,1 C6,3 1,4 -3,3 C-6,3 -8,2 -9,1 Z",
        fill: v.dress, opacity: "0.82"
      }),
      el("path", { d: "M9,1 L13,-1 L13,3 Z", fill: v.dress, opacity: "0.82" }),
      el("path", { d: "M-2,-6 C-2,-10 0,-11 1,-11 C1,-8 0,-6 -1,-5 Z", fill: v.dress, opacity: "0.6" }),
      el("circle", { cx: -6.2, cy: -0.6, r: 0.9, fill: "#FFFFFF", opacity: "0.9" })
    ]));

    /* 腰带 */
    g.appendChild(el("rect", { x: -46, y: -150, width: 92, height: 12, rx: 3, fill: v.tie }));
    g.appendChild(el("rect", { x: -46, y: -150, width: 92, height: 4, rx: 2, fill: v.tieLite, opacity: "0.8" }));
    [-26, -9, 8, 25].forEach(function (dx) {
      g.appendChild(el("circle", { cx: dx, cy: -143, r: 2.1, fill: "rgba(255,255,255,0.7)" }));
    });

    /* 白色圆领：两片荷叶边翻领 */
    g.appendChild(el("path", {
      d: "M-34,-186 C-20,-176 -8,-172 0,-172 C8,-172 20,-176 34,-186 " +
         "C30,-194 16,-198 0,-198 C-16,-198 -30,-194 -34,-186 Z",
      fill: v.lace
    }));
    [-26, -16, -6, 6, 16, 26].forEach(function (dx) {
      g.appendChild(el("circle", { cx: dx, cy: -188 + Math.abs(dx) * 0.16, r: 4.2, fill: v.lace }));
    });

    /* 胸前白门襟 + 三颗扣 */
    g.appendChild(el("rect", { x: -9, y: -184, width: 18, height: 26, rx: 2, fill: v.lace }));
    [-178, -170, -162].forEach(function (yy) {
      g.appendChild(el("circle", { cx: 0, cy: yy, r: 1.9, fill: v.dress }));
    });

    /* 藏青领结 */
    g.appendChild(el("path", { d: "M-3,-182 L-17,-175 L-17,-190 Z", fill: v.tie }));
    g.appendChild(el("path", { d: "M3,-182 L17,-175 L17,-190 Z", fill: v.tie }));
    g.appendChild(el("path", { d: "M-3,-182 L-15,-190 L-14,-194 L-2,-186 Z", fill: v.tieLite, opacity: "0.9" }));
    g.appendChild(el("rect", { x: -4, y: -186, width: 8, height: 9, rx: 3, fill: v.tieLite }));

    return g;
  }

  /* ---------- 腿：白袜 + 玛丽珍鞋 ---------- */

  function legs(v) {
    function one(side) {
      var s = side === "l" ? -1 : 1;
      /* 外层只负责把髋放到 (±21,-56)；内层才是可旋转的骨骼，
       * 否则 CSS 的 rotate 会把 translate 覆盖掉，腿会跳到原点。 */
      var wrap = el("g", { transform: "translate(" + (23 * s) + ",-56)" });
      var g = el("g", { class: "a-leg a-leg-" + side });
      /* bbox 栓：让包围盒关于髋点对称，配合 50%/50% 把旋转原点锁在髋 */
      g.appendChild(el("rect", { x: -40, y: -70, width: 80, height: 140, fill: "none", "pointer-events": "none" }));
      /* 白袜 */
      g.appendChild(el("rect", { x: -13, y: 0, width: 26, height: 40, rx: 10, fill: "#FBFDFF" }));
      g.appendChild(el("rect", { x: -13, y: 0, width: 26, height: 7, rx: 3.5, fill: "#E8EFF8" }));
      /* 袜口荷叶边 */
      [-9, 0, 9].forEach(function (dx) {
        g.appendChild(el("circle", { cx: dx, cy: 3, r: 5.4, fill: "#FFFFFF" }));
      });
      /* 藏青玛丽珍鞋 */
      g.appendChild(el("path", {
        d: "M-19,44 C-19,38 -14,36 -8,36 L8,36 C14,36 19,38 19,44 " +
           "C20,48 20,53 19,56 L-19,56 C-20,53 -20,48 -19,44 Z",
        fill: v.shoe
      }));
      /* 鞋头高光 */
      g.appendChild(el("ellipse", { cx: -7, cy: 45, rx: 5.6, ry: 3, fill: v.shoeLite, opacity: "0.95" }));
      /* 横带 + 小扣 */
      g.appendChild(el("path", { d: "M-18,42 L18,42", stroke: v.shoeLite, "stroke-width": "2.8", "stroke-linecap": "round" }));
      g.appendChild(el("circle", { cx: 9, cy: 42, r: 2, fill: "#C9D4EA" }));
      wrap.appendChild(g);
      return wrap;
    }
    return el("g", { class: "a-legs" }, [one("l"), one("r")]);
  }

  /* ---------- 手臂：肩 → 肘 → 腕，两段骨骼 ---------- */

  function arm(v, side) {
    var s = side === "l" ? -1 : 1;
    var g = el("g", {
      class: "a-arm a-arm-" + side,
      transform: "translate(" + (50 * s) + ",-178)"
    });
    var art = el("g", { class: "a-arm-art" });
    /* bbox 栓：让包围盒关于肩点对称，配合 50%/50% 把旋转原点锁在肩 */
    art.appendChild(el("rect", { x: -40, y: -40, width: 80, height: 80, fill: "none", "pointer-events": "none" }));

    /* 肩头圆润的袖山 */
    art.appendChild(el("circle", { cx: 3 * s, cy: 2, r: 14, fill: "url(#dressGrad-" + v.key + ")" }));
    /* 上臂：胶囊式袖子，外侧描一圈深色把手臂从身体上剥出来 */
    var up = "M2,-2 C" + (10 * s) + ",10 " + (14 * s) + ",20 " + (14 * s) + ",30";
    art.appendChild(el("path", { d: up, fill: "none", stroke: v.dressDeep, "stroke-width": "23", "stroke-linecap": "round" }));
    art.appendChild(el("path", { d: up, fill: "none", stroke: "url(#dressGrad-" + v.key + ")", "stroke-width": "19", "stroke-linecap": "round" }));

    /* 肘关节：translate 放在外层，内层 .a-fore 才是旋转骨骼，
     * 否则 CSS 的 rotate 会覆盖 transform 属性，把前臂甩回原点 */
    var elbow = el("g", { transform: "translate(" + (14 * s) + ",30)" });
    var fore = el("g", { class: "a-fore" });
    /* bbox 栓：让包围盒关于肘点对称 */
    fore.appendChild(el("rect", { x: -40, y: -60, width: 80, height: 120, fill: "none", "pointer-events": "none" }));
    /* 前臂（袖） */
    var low = "M0,0 C" + (2 * s) + ",12 " + (3 * s) + ",26 " + (3 * s) + ",36";
    fore.appendChild(el("path", { d: low, fill: "none", stroke: v.dressDeep, "stroke-width": "19", "stroke-linecap": "round" }));
    fore.appendChild(el("path", { d: low, fill: "none", stroke: "url(#dressGrad-" + v.key + ")", "stroke-width": "15.5", "stroke-linecap": "round" }));
    /* 白色蕾丝袖口 */
    [-4, 0, 4].forEach(function (dx) {
      fore.appendChild(el("circle", { cx: (3 * s) + dx * 0.9, cy: 34, r: 5, fill: v.lace }));
    });
    fore.appendChild(el("ellipse", { cx: 3 * s, cy: 34, rx: 9, ry: 6, fill: v.lace }));

    /* 手 */
    var hand = el("g", { class: "a-hand" });
    hand.appendChild(el("rect", { x: -9, y: 36, width: 18, height: 9, fill: "none", "pointer-events": "none" }));
    hand.appendChild(el("ellipse", { cx: 3 * s, cy: 42, rx: 7.6, ry: 7, fill: v.skin }));
    hand.appendChild(el("ellipse", { cx: (3 * s) - 2, cy: 40, rx: 3, ry: 2.4, fill: "#FFFFFF", opacity: "0.45" }));
    /* 手指：三根小方块，点击时整组上下走 */
    [-3.6, 0, 3.6].forEach(function (dx, i) {
      hand.appendChild(el("rect", {
        x: (3 * s) + dx - 1.4, y: 47, width: 2.8, height: 5.2 - i * 0.4, rx: 1.4,
        fill: v.skinShade, class: "a-finger"
      }));
    });
    fore.appendChild(hand);
    elbow.appendChild(fore);
    art.appendChild(elbow);
    g.appendChild(art);
    return g;
  }

  /* ---------- 头 ---------- */

  function headArt(v) {
    var id = v.key;
    var g = el("g", { class: "a-head" });

    var ex, ey;
    ey = -232;

    /* 鳍耳：扇形，外缘三个尖 */
    [[-1], [1]].forEach(function (arr) {
      var s = arr[0];
      g.appendChild(el("path", {
        d: "M" + (54 * s) + ",-250 " +
           "C" + (72 * s) + ",-258 " + (94 * s) + ",-254 " + (110 * s) + ",-242 " +
           "L" + (96 * s) + ",-235 " +
           "L" + (108 * s) + ",-228 " +
           "L" + (92 * s) + ",-221 " +
           "L" + (100 * s) + ",-212 " +
           "L" + (74 * s) + ",-215 " +
           "C" + (62 * s) + ",-223 " + (54 * s) + ",-238 " + (54 * s) + ",-250 Z",
        fill: "url(#finGrad-" + id + ")", stroke: v.finEdge, "stroke-width": "1.2", "stroke-linejoin": "round"
      }));
      /* 鳍条：从基部放射 3 道 */
      [[-244, -238], [-240, -228], [-236, -218]].forEach(function (pair) {
        g.appendChild(el("path", {
          d: "M" + (62 * s) + "," + pair[0] + " L" + (100 * s) + "," + pair[1],
          fill: "none", stroke: v.finEdge, "stroke-width": "0.9", opacity: "0.4"
        }));
      });
    });

    /* 脸 */
    g.appendChild(el("ellipse", { cx: 0, cy: -240, rx: 50, ry: 54, fill: "url(#skinGrad-" + id + ")" }));
    /* 下巴阴影 */
    g.appendChild(el("ellipse", { cx: 0, cy: -194, rx: 26, ry: 9, fill: v.skinShade, opacity: "0.4" }));

    /* 眼 */
    [-1, 1].forEach(function (s) {
      ex = 30 * s;
      g.appendChild(el("ellipse", { cx: ex, cy: ey, rx: 17, ry: 19.5, fill: "#FFFFFF" }));
      g.appendChild(el("ellipse", { cx: ex, cy: ey, rx: 15.6, ry: 18, fill: "url(#eyeGrad-" + id + ")" }));
      /* 瞳仁 */
      g.appendChild(el("ellipse", { cx: ex, cy: ey + 1, rx: 7.4, ry: 9.6, fill: v.pupil }));
      /* 虹膜底部反光 */
      g.appendChild(el("ellipse", { cx: ex, cy: ey + 8, rx: 10, ry: 6, fill: v.eye[2], opacity: "0.55" }));
      /* 高光：左上大、右下小 */
      g.appendChild(el("circle", { cx: ex - 5.6, cy: ey - 7.4, r: 5.4, fill: "#FFFFFF" }));
      g.appendChild(el("circle", { cx: ex + 5.4, cy: ey + 7.2, r: 2.6, fill: "#FFFFFF", opacity: "0.85" }));
      /* 上睫毛 */
      g.appendChild(el("path", {
        d: "M" + (ex - 17) + "," + (ey - 6) + " C" + (ex - 14) + "," + (ey - 20) + " " + (ex + 14) + "," + (ey - 20) + " " + (ex + 17) + "," + (ey - 7),
        fill: "none", stroke: "#1B2C46", "stroke-width": "4.4", "stroke-linecap": "round"
      }));
      /* 外眼角上挑 */
      g.appendChild(el("path", {
        d: "M" + (ex + 15 * s) + "," + (ey - 12) + " L" + (ex + 21 * s) + "," + (ey - 18),
        fill: "none", stroke: "#1B2C46", "stroke-width": "3", "stroke-linecap": "round"
      }));
    });

    /* 腮红 */
    g.appendChild(el("ellipse", { cx: -38, cy: ey + 16, rx: 12, ry: 6.4, fill: v.blush, opacity: "0.42" }));
    g.appendChild(el("ellipse", { cx: 38, cy: ey + 16, rx: 12, ry: 6.4, fill: v.blush, opacity: "0.42" }));

    /* 嘴：张开的小口 */
    g.appendChild(el("path", {
      d: "M-6,-206 C-3,-201 3,-201 6,-206 C4,-199 -4,-199 -6,-206 Z",
      fill: "#C9566B"
    }));
    g.appendChild(el("path", { d: "M-5,-205 L5,-205", fill: "none", stroke: "#A84056", "stroke-width": "1.6", "stroke-linecap": "round" }));

    /* 刘海：中分 M 形，压到眼睛上方 */
    g.appendChild(el("path", {
      d: "M-74,-272 C-78,-318 -46,-348 0,-350 C46,-348 78,-318 74,-272 " +
         "Q66,-250 54,-266 " +
         "Q40,-244 24,-262 " +
         "Q8,-240 -8,-262 " +
         "Q-24,-244 -38,-264 " +
         "Q-54,-250 -66,-268 " +
         "Q-72,-268 -74,-272 Z",
      fill: "url(#hairGrad2-" + id + ")"
    }));
    /* 刘海高光 */
    g.appendChild(el("path", {
      d: "M-46,-322 C-26,-336 22,-336 44,-322", fill: "none",
      stroke: "rgba(255,255,255,0.28)", "stroke-width": "5", "stroke-linecap": "round"
    }));

    /* 呆毛：从头顶向上再向左勾回来 */
    g.appendChild(el("path", {
      d: "M6,-346 C2,-372 -14,-392 -36,-386 C-46,-383 -47,-372 -38,-370 " +
         "C-24,-366 -10,-352 -2,-336 Z",
      fill: v.hair[1]
    }));

    /* 白色荷叶边发带：沿头顶一条弧 */
    g.appendChild(el("path", {
      d: "M-78,-278 C-82,-322 -44,-350 0,-350 C44,-350 82,-322 78,-278 " +
         "L70,-280 C72,-316 40,-340 0,-340 C-40,-340 -72,-316 -70,-280 Z",
      fill: v.lace
    }));
    /* 发带外缘的小齿边：小球半径与间距匹配，连成荷叶边 */
    for (var i = 0; i <= 13; i++) {
      var th = Math.PI * (1 - i / 13);
      g.appendChild(el("circle", {
        cx: 78 * Math.cos(th), cy: -282 - 60 * Math.sin(th), r: 5, fill: v.lace
      }));
    }
    /* 发带内侧一条冷色暗线，压出厚度 */
    g.appendChild(el("path", {
      d: "M-70,-280 C-72,-316 -40,-340 0,-340 C40,-340 72,-316 70,-280",
      fill: "none", stroke: v.laceShade, "stroke-width": "2", opacity: "0.85"
    }));

    /* 浅蓝蝴蝶结：画面右侧 */
    g.appendChild(el("g", { transform: "translate(72,-300) rotate(-14) scale(1.15)" }, [
      el("path", { d: "M0,0 C-12,-12 -24,-10 -25,-1 C-26,8 -14,11 0,3 Z", fill: v.ribbon }),
      el("path", { d: "M0,0 C12,-12 24,-10 25,-1 C26,8 14,11 0,3 Z", fill: v.ribbon }),
      el("path", { d: "M-4,2 C-8,12 -14,18 -20,20 C-16,13 -12,7 -8,1 Z", fill: v.ribbonDeep, opacity: "0.95" }),
      el("path", { d: "M4,2 C8,12 13,18 19,20 C16,13 12,7 8,1 Z", fill: v.ribbonDeep, opacity: "0.95" }),
      el("ellipse", { cx: 0, cy: 1, rx: 4.6, ry: 4, fill: v.ribbonDeep }),
      el("circle", { cx: -1, cy: -1, r: 1.6, fill: "rgba(255,255,255,0.8)" })
    ]));

    return g;
  }

  /* ---------- 装配 ---------- */

  function build(key) {
    var v = VARIANTS[key];
    var root = el("g", { class: "actor", "data-key": key, tabindex: "0" });
    root.appendChild(defs(v));
    root.appendChild(el("ellipse", { class: "a-shadow", cx: 0, cy: 0, rx: 74, ry: 11 }));
    root.appendChild(el("g", { class: "a-body" }, [
      hairBack(v),
      tail(v),
      legs(v),
      el("g", { class: "a-torso" }, [
        torsoShape(v),
        hairSide(v),
        arm(v, "l"),
        arm(v, "r"),
        headArt(v)
      ])
    ]));
    return { node: root, variant: v, key: key };
  }

  /* 姿势：sit（落座，双腿藏进桌裙后，手臂折到桌面上）/ stand（站立与行走） */
  function setPose(node, pose) {
    var seat = pose === "sit";
    node.classList.toggle("is-seated", seat);
  }

  function setTyping(node, on) {
    node.classList.toggle("is-typing", !!on);
  }

  /* 抽屉头像：复用同一套头部矢量，保证「抽屉里的脸」与场景里一致 */
  function avatar(key, size) {
    var v = VARIANTS[key];
    var s = size || 48;
    return el("svg", {
      viewBox: "-110 -370 220 220",
      width: s, height: s
    }, [
      defs(v),
      el("g", { transform: "translate(0,0)" }, [headArt(v)])
    ]);
  }

  return { build: build, avatar: avatar, setPose: setPose, setTyping: setTyping, VARIANTS: VARIANTS, UNIT: UNIT };
})();
