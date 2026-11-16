"""Build bilingual, self-contained animated README diagrams; --check detects drift."""
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets"

WIDTH, HEIGHT = 1600, 1240
CARD_W, CARD_H = 350, 140
COLS = [40, 430, 820, 1210]
ROWS = [226, 568, 920]
ROW_MID = [row + CARD_H // 2 for row in ROWS]
ROW_COLORS = ["#60a5fa", "#fbbf24", "#a78bfa"]

CONTENT = {
    "en": {
        "title": "From forecasts to evidence",
        "subtitle": "Stock-Predict-Mailer / local-first runtime / explicit permissions at every boundary",
        "lanes": [
            "01 / VALIDATE, EXPLAIN, PUBLISH",
            "02 / OPTIONAL CAPABILITIES + MAIL",
            "03 / OBSERVE AT THE RIGHT TIME",
        ],
        "nodes": [
            ["Prediction intake", "Mock / file / HTTP or console task", "Upstream model owns its prediction", "Direction, value, horizon, timestamps"],
            ["Strict contract gates", "Version, subject, finite numbers", "Fresh prediction + available context", "Reject invalid or stale inputs"],
            ["Bounded analysis", "Deterministic or configured agents", "MCP / A2A: authorized tools + roles", "Time, calls, steps and cost limits"],
            ["Evidence-grounded report", "Facts, inferences, limits, risks", "JSON + escaped HTML + chart data", "Same evidence in the frozen email"],
            ["Explicit forecast archive", "Per-task target, metric, calendar", "Freeze before any provider call", "Immutable; never inherits opt-in"],
            ["Private knowledge", "Upload → clean → review → index", "Worker uses the same workspace + key", "Authorized citations at the cutoff"],
            ["Conversation + progress", "Memory, checkpoints and event stream", "Visible delegation and degradation", "Animation is not a model invocation"],
            ["MailCore outbox", "Frozen content, recipient, endpoint", "Deduplicate → deliver → audit state", "Bounded retry; review uncertainty"],
            ["Explicit observation import", "UTF-8 JSON or single-row CSV", "No inferred units or adjustment rules", "256 KiB; raw + normalized hashes"],
            ["Match + time gates", "Subject / metric / unit / synthetic", "Observed time = predeclared target", "Target + availability ≤ cutoff ≤ now"],
            ["Web preview · no writes", "Not due / unavailable → no score", "Ready → direction + numeric errors", "persisted=false; archive unchanged"],
            ["Separate CLI evaluation", "Explicit forecast evaluate command", "Append immutable, versioned receipt", "Never change the original report"],
        ],
        "states": "pending · simulated / submitted · retry · uncertain",
        "ops": "OPERATIONS  /  doctor  ·  runtime lifecycle  ·  encrypted backup  ·  isolated restore  ·  preflight + transactional migration",
        "footer": "Moving markers illustrate routes, not live telemetry. Dashed routes require an explicit opt-in or a separate command.",
        "legend": ["default path", "opt-in / separate command", "animated route, not telemetry"],
        "alt": "Detailed runtime: strict intake, optional archive and knowledge, bounded analysis, reports, durable delivery, observation gates, preview and explicit CLI receipts.",
    },
    "zh-CN": {
        "title": "从上游预测到可核对的证据",
        "subtitle": "Stock-Predict-Mailer / 本机运行 / 每个边界保留明确授权",
        "lanes": [
            "01 / 校验、分析与报告",
            "02 / 按需能力与持久化交付",
            "03 / 在正确时点核对观测",
        ],
        "nodes": [
            ["接收上游预测", "Mock / 文件 / HTTP 或控制台任务", "预测结果由上游模型负责", "方向、数值、周期与时间声明"],
            ["严格输入门禁", "版本、标的与有限数字", "预测未过期，上下文在当时可用", "非法或过期输入阻断任务"],
            ["有界分析", "确定性分析或已配置 Agent", "MCP / A2A：获准工具与角色", "时间、调用、步骤和费用上限"],
            ["带证据的分层报告", "事实 / 推断 / 限制 / 风险", "JSON、转义 HTML 与图表资料", "冻结邮件沿用同一份来源证据"],
            ["显式事前归档", "本轮声明目标、指标、单位与日历", "在可选服务调用前固定口径", "不可覆盖；下一轮不继承开关"],
            ["私有知识库", "上传 → 清洗 → 审批 → 索引", "Worker 沿用同一工作区和密钥", "仅引用有权限且符合截止的证据"],
            ["会话与任务进度", "记忆、检查点和事件流", "委派、失败与降级明确展示", "场景动画不等于模型正在调用"],
            ["MailCore 持久发件箱", "冻结正文、收件人与投递端点", "去重 → 交付 → 状态审计", "有界重试；不确定结果人工核对"],
            ["显式导入观测", "UTF-8 JSON 或固定字段单行 CSV", "不猜测单位、复权口径或交易日", "256 KiB；原文与标准观测摘要"],
            ["匹配与时点门禁", "标的 / 指标 / 单位 / 合成标记", "观测时点必须等于事前目标", "到期且可用时间 ≤ 截止 ≤ 现在"],
            ["网页预览 · 不写入", "未到期或不可用：不显示评分", "符合条件：方向与数值误差", "persisted=false；档案不变"],
            ["单独执行 CLI 评估", "显式 forecast evaluate 命令", "追加不可覆盖的版本化回执", "不改变原始分析报告"],
        ],
        "states": "pending · simulated / submitted · retry · uncertain",
        "ops": "运行保障  /  doctor 诊断  ·  组件启停  ·  加密备份  ·  隔离恢复  ·  迁移预检与单库事务",
        "footer": "移动标记仅说明路径，不是实时遥测。虚线路径需要本轮显式启用，或单独执行对应命令。",
        "legend": ["默认路径", "显式启用或单独命令", "移动标记仅示意路径"],
        "alt": "详细运行流程：严格接入、可选归档与知识库、有界分析、报告、持久投递、观测时点、预览及显式 CLI 回执。",
    },
}

# (path, colour, optional). Colours: blue = analysis chain, green = delivery,
# amber = optional capability, violet = point-in-time evaluation.
EDGES = [
    (f"M{COLS[0] + CARD_W} {ROW_MID[0]}H{COLS[1]}", ROW_COLORS[0], False),
    (f"M{COLS[1] + CARD_W} {ROW_MID[0]}H{COLS[2]}", ROW_COLORS[0], False),
    (f"M{COLS[2] + CARD_W} {ROW_MID[0]}H{COLS[3]}", "#34d399", False),
    ("M368 568V474H1000V366", ROW_COLORS[1], True),
    ("M605 568V430H905V366", ROW_COLORS[1], True),
    ("M1090 366V568", ROW_COLORS[0], False),
    ("M1385 366V568", "#34d399", False),
    ("M368 708V920", ROW_COLORS[2], True),
    (f"M{COLS[0] + CARD_W} {ROW_MID[2]}H{COLS[1]}", ROW_COLORS[2], False),
    (f"M{COLS[1] + CARD_W} {ROW_MID[2]}H{COLS[2]}", ROW_COLORS[2], False),
    (f"M{COLS[2] + CARD_W} {ROW_MID[2]}H{COLS[3]}", ROW_COLORS[1], True),
]
MARKERS = {"#60a5fa": "blue", "#34d399": "green", "#fbbf24": "amber", "#a78bfa": "violet"}


def build(language):
    c = CONTENT[language]
    parts = [f'''<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title description" xml:lang="{language}">
<title id="title">{escape(c['title'])}</title><desc id="description">{escape(c['alt'])}</desc>
<defs>''']
    for colour, name in MARKERS.items():
        parts.append(
            f'<marker id="arrow-{name}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
            f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{colour}"/></marker>'
        )
    parts.append('''</defs>
<style>
text {font-family:Inter,"Segoe UI",system-ui,"Microsoft YaHei",Arial,sans-serif}
.title {fill:#f1f5f9;font-size:38px;font-weight:650} .sub {fill:#94a3b8;font-size:17.5px}
.lane {fill:#c7d2fe;font-size:15px;font-weight:650;letter-spacing:0.8px}
.name {fill:#f1f5f9;font-size:20px;font-weight:600} .body {fill:#cbd5e1;font-size:15.5px}
.hint {fill:#94a3b8;font-size:13.5px} .state {fill:#34d399;font-size:13.5px;letter-spacing:0.3px}
.edge {fill:none;stroke-width:1.9;stroke-linecap:round} .optional {stroke-dasharray:7 6}
.flow {stroke-dasharray:8 6;animation:dash 4s linear infinite} .token {fill:#e2e8f0}
@keyframes dash {to {stroke-dashoffset:-56}}
@media(prefers-reduced-motion:reduce) {.flow {animation:none} .token {display:none}}
</style>
<rect width="1600" height="1240" rx="24" fill="#0b1220"/>
<rect x="0.5" y="0.5" width="1599" height="1239" rx="24" fill="none" stroke="#1e293b"/>''')

    parts.append(f'<text x="40" y="66" class="title">{escape(c["title"])}</text>')
    parts.append(f'<text x="40" y="104" class="sub">{escape(c["subtitle"])}</text>')

    # Legend, top right: solid sample, dashed sample, moving marker sample.
    parts.append('<path d="M1156 54H1198" stroke="#94a3b8" class="edge"/>')
    parts.append(f'<text x="1208" y="59" class="hint">{escape(c["legend"][0])}</text>')
    parts.append('<path d="M1332 54H1374" stroke="#94a3b8" class="edge optional"/>')
    parts.append(f'<text x="1384" y="59" class="hint">{escape(c["legend"][1])}</text>')
    parts.append('<circle cx="1162" cy="88" r="4" fill="#e2e8f0"/>')
    parts.append(f'<text x="1176" y="93" class="hint">{escape(c["legend"][2])}</text>')

    # Lane separators + labels.
    for index, row in enumerate(ROWS):
        if index:
            parts.append(f'<path d="M40 {row - 58}H1560" stroke="#1b2740" stroke-width="1"/>')
        parts.append(f'<rect x="40" y="{row - 40}" width="9" height="9" rx="2" fill="{ROW_COLORS[index]}"/>')
        parts.append(f'<text x="60" y="{row - 31}" class="lane">{escape(c["lanes"][index])}</text>')

    # Cards first so connector arrowheads stay visible at the card edges.
    for i, node in enumerate(c["nodes"]):
        row, col = divmod(i, 4)
        x, y = COLS[col], ROWS[row]
        colour = ROW_COLORS[row]
        parts.append(f'<rect x="{x}" y="{y}" width="{CARD_W}" height="{CARD_H}" rx="12" fill="#111c2e" stroke="#2a3a52"/>')
        parts.append(f'<path d="M{x + 1} {y + 13}V{y + 43}" stroke="{colour}" stroke-width="3" stroke-linecap="round"/>')
        parts.append(f'<text x="{x + 18}" y="{y + 34}" class="name">{escape(node[0])}</text>')
        for j, line in enumerate(node[1:]):
            parts.append(f'<text x="{x + 18}" y="{y + 66 + j * 24}" class="body">{escape(line)}</text>')

    tokens = []
    for i, (path, colour, optional) in enumerate(EDGES):
        marker = MARKERS[colour]
        cls = "edge optional" if optional else "edge flow"
        parts.append(f'<path d="{path}" stroke="{colour}" class="{cls}" marker-end="url(#arrow-{marker})"/>')
        tokens.append(
            f'<circle r="4" class="token"><animateMotion dur="{4 + i % 4}s" begin="{i % 3}s" '
            f'repeatCount="indefinite" path="{path}"/></circle>'
        )

    parts.extend(tokens)
    parts.append(f'<text x="{COLS[3] + 4}" y="{ROWS[1] + CARD_H + 34}" class="state">{escape(c["states"])}</text>')
    parts.append('<rect x="40" y="1100" width="1520" height="52" rx="10" fill="#141f33" stroke="#22304a"/>')
    parts.append('<rect x="40" y="1100" width="3" height="52" rx="1.5" fill="#64748b"/>')
    parts.append(f'<text x="60" y="1134" class="body">{escape(c["ops"])}</text>')
    parts.append(f'<text x="40" y="1200" class="sub">{escape(c["footer"])}</text></svg>')
    return "\n".join(parts) + "\n"


if __name__ == "__main__":
    import sys
    ASSETS.mkdir(parents=True, exist_ok=True)
    for lang in CONTENT:
        path = ASSETS / f"runtime-flow.{lang}.svg"
        content = build(lang)
        if "--check" in sys.argv:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                raise SystemExit(f"Diagram is stale: {path.name}")
        else:
            path.write_text(content, encoding="utf-8", newline="\n")
    print("Runtime diagrams are current")
