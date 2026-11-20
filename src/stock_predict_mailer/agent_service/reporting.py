"""Readable escaped HTML and plain text from the same structured result.

The formatters themselves live in ``plugins/builtin/report.py``; this module keeps
the public entry points and the write path, so callers, frozen mail bodies and
tests keep the same bytes. Each saved report also records which renderers and
which module versions produced it — a report is a frozen artifact, and the rest
of this project already hashes whatever it freezes.
"""
from __future__ import annotations

from .. import __version__
from ..core import atomic_write, write_json
from .input_evidence import persist


def render_with_provenance(analysis, timezone="Asia/Shanghai", *, charts="inline"):
    """Both formats plus the declared renderers behind them."""
    from ..plugins.registry import API_VERSION, identity, resolve

    view = {"analysis": analysis, "timezone": timezone, "charts": charts}
    text_plugin = resolve("report_text", kind="report_renderer")
    html_plugin = resolve("report_html", kind="report_renderer")
    text = text_plugin.render(view).decode("utf-8")
    html = html_plugin.render(view).decode("utf-8")
    provenance = {"plugin_api_version": API_VERSION, "release": __version__,
                  "renderers": [{"format": "text", **identity(text_plugin.manifest.id)},
                                {"format": "html", **identity(html_plugin.manifest.id)}]}
    return text, html, provenance


def render(analysis, timezone="Asia/Shanghai", *, charts="inline"):
    """Both formats come from the declared renderers; neither owns the content."""
    text, html, _ = render_with_provenance(analysis, timezone, charts=charts)
    return text, html


def save_report(workspace, analysis, timezone="Asia/Shanghai"):
    if "input_evidence" in analysis:
        persist(workspace, analysis["input_evidence"])
    folder = workspace / "analysis" / analysis["analysis_id"]
    write_json(folder / "analysis.json", analysis)
    _, html, provenance = render_with_provenance(analysis, timezone)
    atomic_write(folder / "report.html", html.encode())
    write_json(folder / "renderers.json", provenance)
    return folder
