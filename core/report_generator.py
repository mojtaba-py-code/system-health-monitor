"""Report generation from a health snapshot (JSON / CSV / TXT / HTML / PDF)."""

from __future__ import annotations

import csv
import html
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.base import Severity
from core.collector import HealthSnapshot
from utils.exceptions import MonitorError
from utils.security import validate_output_path

SUPPORTED_FORMATS = ("json", "csv", "txt", "html", "pdf")

_SEVERITY_COLOUR = {
    "OK": "#16a34a",
    "WARNING": "#d97706",
    "CRITICAL": "#dc2626",
    "UNKNOWN": "#6b7280",
}


def _flatten(snapshot: HealthSnapshot) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in snapshot.results:
        for metric in result.metrics:
            rows.append(
                {
                    "subsystem": metric.subsystem,
                    "metric": metric.name,
                    "value": metric.value,
                    "unit": metric.unit,
                    "severity": metric.severity.label,
                }
            )
    return rows


def _summary(snapshot: HealthSnapshot) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "overall_status": snapshot.worst_severity.label,
        "subsystems": {r.subsystem: r.worst_severity.label for r in snapshot.results},
        "total_metrics": sum(len(r.metrics) for r in snapshot.results),
    }


def render_json(snapshot: HealthSnapshot) -> str:
    return json.dumps({"summary": _summary(snapshot), "snapshot": snapshot.as_dict()}, indent=2, default=str)


def render_csv(snapshot: HealthSnapshot) -> str:
    rows = _flatten(snapshot)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=["subsystem", "metric", "value", "unit", "severity"])
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def render_txt(snapshot: HealthSnapshot) -> str:
    summary = _summary(snapshot)
    lines = [
        "System Health Report",
        "=" * 20,
        f"Generated: {summary['generated_at']}",
        f"Overall: {summary['overall_status']}",
        "",
    ]
    for result in snapshot.results:
        lines.append(f"[{result.subsystem.upper()}] ({result.worst_severity.label})")
        for metric in result.metrics:
            flag = "" if metric.severity == Severity.OK else f"  <-- {metric.severity.label}"
            lines.append(f"    {metric.name}: {metric.value}{metric.unit}{flag}")
        for err in result.errors:
            lines.append(f"    ! {err}")
        lines.append("")
    return "\n".join(lines)


def render_html(snapshot: HealthSnapshot) -> str:
    summary = _summary(snapshot)
    overall = summary["overall_status"]
    sections = []
    for result in snapshot.results:
        badge = _SEVERITY_COLOUR.get(result.worst_severity.label, "#6b7280")
        rows = "".join(
            f"<tr><td>{html.escape(m.name)}</td>"
            f"<td>{html.escape(str(m.value))}{html.escape(m.unit)}</td>"
            f"<td style='color:{_SEVERITY_COLOUR.get(m.severity.label, '#000')}'>{m.severity.label}</td></tr>"
            for m in result.metrics
        )
        sections.append(
            f"<h2>{html.escape(result.subsystem.title())} "
            f"<span style='color:{badge}'>&#9679; {result.worst_severity.label}</span></h2>"
            f"<table><thead><tr><th>Metric</th><th>Value</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table>"
        )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>System Health Report</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #1f2937; }}
  h1 {{ color: #0e75b6; }}
  table {{ border-collapse: collapse; width: 100%; margin-bottom: 1.5rem; }}
  th, td {{ border: 1px solid #e5e7eb; padding: 5px 10px; text-align: left; }}
  th {{ background: #f3f4f6; }}
</style></head><body>
  <h1>System Health Report</h1>
  <p>Generated: {summary['generated_at']} &nbsp;|&nbsp; Overall:
     <strong style="color:{_SEVERITY_COLOUR.get(overall)}">{overall}</strong></p>
  {''.join(sections)}
</body></html>
"""


def render_pdf(snapshot: HealthSnapshot, destination: Path) -> None:
    """Write a PDF report (requires the optional 'reportlab' package)."""
    try:
        from reportlab.lib.pagesizes import A4  # type: ignore
        from reportlab.pdfgen import canvas  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise MonitorError("PDF reports require the optional 'reportlab' package.") from exc

    pdf = canvas.Canvas(str(destination), pagesize=A4)
    _width, height = A4
    y = height - 50
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(50, y, "System Health Report")
    y -= 30
    pdf.setFont("Helvetica", 10)
    for result in snapshot.results:
        if y < 60:
            pdf.showPage()
            y = height - 50
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(50, y, f"{result.subsystem.title()} ({result.worst_severity.label})")
        y -= 18
        pdf.setFont("Helvetica", 9)
        for metric in result.metrics:
            if y < 50:
                pdf.showPage()
                y = height - 50
            pdf.drawString(60, y, f"{metric.name}: {metric.value}{metric.unit} [{metric.severity.label}]")
            y -= 13
        y -= 8
    pdf.save()


_RENDERERS = {"json": render_json, "csv": render_csv, "txt": render_txt, "html": render_html}


def generate_report(
    snapshot: HealthSnapshot,
    *,
    fmt: str = "json",
    output_dir: str | Path = "reports",
    name: str | None = None,
    allowed_roots: list[str] | None = None,
) -> Path:
    """Render *snapshot* to disk in *fmt* and return the written path."""
    fmt = fmt.lower()
    if fmt not in SUPPORTED_FORMATS:
        raise MonitorError(f"Unsupported report format '{fmt}'. Choose from {', '.join(SUPPORTED_FORMATS)}.")

    directory = validate_output_path(output_dir, allowed_roots=allowed_roots)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = directory / f"{name or 'health_report'}_{stamp}.{fmt}"

    if fmt == "pdf":
        render_pdf(snapshot, destination)
    else:
        destination.write_text(_RENDERERS[fmt](snapshot), encoding="utf-8")
    return destination


def render(snapshot: HealthSnapshot, fmt: str = "json") -> str:
    """Render to a string (non-PDF) — convenient for tests."""
    fmt = fmt.lower()
    if fmt not in _RENDERERS:
        raise MonitorError(f"Cannot render '{fmt}' to string.")
    return _RENDERERS[fmt](snapshot)
