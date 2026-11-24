"""Deterministic SVG renderers for the existing validated chart model."""
from ...agent_service.charts import render_svg
from ..contract import declare


class LineChart:
    manifest = declare(id="chart_line", kind="chart_renderer", label="时间序列折线图", capabilities=("line",))
    render = staticmethod(render_svg)


class GroupedBarChart:
    manifest = declare(id="chart_bar", kind="chart_renderer", label="分组柱状图", capabilities=("bar",))

    @staticmethod
    def render(chart):
        return render_svg(chart, bars=True)
