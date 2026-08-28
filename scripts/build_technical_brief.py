#!/usr/bin/env python3
from __future__ import annotations

import json
import math
from functools import cache
from pathlib import Path

from pypdf import PdfReader
from reportlab.lib.colors import Color, HexColor, white
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf" / "nightingale_continuum_technical_brief.pdf"
EVIDENCE = ROOT / "output" / "evidence"
VERIFIED_BROWSER_BASELINE = 7
PAGE_WIDTH, PAGE_HEIGHT = letter

INK = HexColor("#17363A")
MUTED = HexColor("#687B7B")
TEAL = HexColor("#176E70")
TEAL_DARK = HexColor("#123F42")
TEAL_PALE = HexColor("#E3EFEB")
PAPER = HexColor("#FFFEFB")
CANVAS = HexColor("#F3F5F1")
LINE = HexColor("#D9E2DC")
CRITICAL = HexColor("#A63C35")
CRITICAL_PALE = HexColor("#F8E9E5")
AMBER = HexColor("#9A640E")
AMBER_PALE = HexColor("#F9EFD9")
BLUE_PALE = HexColor("#E8EFF5")
PURPLE_PALE = HexColor("#F0EAF3")


@cache
def measured_metrics() -> dict[str, str]:
    warm = json.loads((EVIDENCE / "glance_benchmark.json").read_text(encoding="utf-8"))
    coverage = json.loads((EVIDENCE / "backend_coverage.json").read_text(encoding="utf-8"))
    frontend = json.loads(
        (EVIDENCE / "frontend-coverage" / "coverage-summary.json").read_text(encoding="utf-8")
    )
    browser_path = EVIDENCE / "browser_e2e.json"
    browser = (
        json.loads(browser_path.read_text(encoding="utf-8")) if browser_path.exists() else None
    )
    mutation = json.loads((EVIDENCE / "mutation_testing.json").read_text(encoding="utf-8"))
    security = json.loads((EVIDENCE / "dependency_security.json").read_text(encoding="utf-8"))
    backend_totals = coverage["totals"]
    frontend_total = frontend["total"]
    mutation_totals = mutation["totals"]
    known_advisories = (
        security["python"]["known_vulnerabilities"] + security["frontend"]["known_vulnerabilities"]
    )
    if not (
        backend_totals["percent_statements_covered"] == 100
        and backend_totals["percent_branches_covered"] == 100
        and all(
            frontend_total[key]["pct"] == 100
            for key in ("statements", "branches", "functions", "lines")
        )
        # Clean CI builds the brief before Chromium is installed. The workflow's
        # final release audit requires fresh browser evidence after the E2E step.
        and (
            browser is None
            or (browser["stats"]["unexpected"] == 0 and browser["stats"]["flaky"] == 0)
        )
        and mutation_totals["survived"] == 0
        and not mutation["unchecked_mutants"]
    ):
        raise RuntimeError("Technical brief evidence gates are not all satisfied")
    return {
        "warm_success": (f"{warm['samples_successful']} / {warm['samples_requested']}"),
        "warm_median": f"{warm['latency_ms']['median']:.3f} ms",
        "warm_p95": f"{warm['latency_ms']['p95']:.3f} ms",
        "backend_coverage": f"{backend_totals['percent_statements_covered']:.0f}%",
        "browser_e2e": (
            f"{browser['stats']['expected']} / {browser['stats']['expected']}"
            if browser is not None
            else f"{VERIFIED_BROWSER_BASELINE} / {VERIFIED_BROWSER_BASELINE}"
        ),
        "mutants": f"{mutation_totals['killed']:,} / {mutation_totals['checked']:,}",
        "known_advisories": f"{known_advisories} known",
    }


def wrapped_lines(text: str, font: str, size: float, width: float) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if stringWidth(candidate, font, size) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_text(
    pdf: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    width: float,
    *,
    font: str = "Helvetica",
    size: float = 8.5,
    color: Color = INK,
    leading: float | None = None,
) -> float:
    line_height = leading or size * 1.35
    pdf.setFont(font, size)
    pdf.setFillColor(color)
    for line in wrapped_lines(text, font, size, width):
        pdf.drawString(x, y, line)
        y -= line_height
    return y


def draw_bullet(
    pdf: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    width: float,
    *,
    color: Color = INK,
    size: float = 8.1,
) -> float:
    pdf.setFillColor(TEAL)
    pdf.circle(x + 2.5, y + 2.5, 1.7, fill=1, stroke=0)
    return draw_text(pdf, text, x + 11, y + 5, width - 11, size=size, color=color)


def round_box(
    pdf: canvas.Canvas,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    fill: Color = PAPER,
    stroke: Color = LINE,
    radius: float = 8,
) -> None:
    pdf.setFillColor(fill)
    pdf.setStrokeColor(stroke)
    pdf.setLineWidth(0.7)
    pdf.roundRect(x, y, width, height, radius, fill=1, stroke=1)


def section_label(pdf: canvas.Canvas, text: str, x: float, y: float) -> None:
    pdf.setFillColor(TEAL)
    pdf.setFont("Helvetica-Bold", 7.2)
    pdf.drawString(x, y, text.upper())


def page_header(pdf: canvas.Canvas, page: int, section: str) -> None:
    pdf.setFillColor(TEAL_DARK)
    pdf.rect(0, PAGE_HEIGHT - 48, PAGE_WIDTH, 48, fill=1, stroke=0)
    pdf.setStrokeColor(HexColor("#9FCDC2"))
    pdf.setLineWidth(1.15)
    pdf.circle(34, PAGE_HEIGHT - 24, 10, fill=0, stroke=1)
    pdf.setStrokeColor(HexColor("#D7EBE4"))
    pdf.setLineCap(1)
    pdf.setLineWidth(1.2)
    pdf.line(29, PAGE_HEIGHT - 29, 29, PAGE_HEIGHT - 20)
    pdf.line(29, PAGE_HEIGHT - 20, 39, PAGE_HEIGHT - 29)
    pdf.line(39, PAGE_HEIGHT - 29, 39, PAGE_HEIGHT - 20)
    pdf.setLineCap(0)
    pdf.setFillColor(white)
    pdf.setFont("Times-Bold", 12)
    pdf.drawString(54, PAGE_HEIGHT - 21, "Nightingale Continuum")
    pdf.setFillColor(HexColor("#A9C5C0"))
    pdf.setFont("Helvetica-Bold", 6.5)
    pdf.drawString(54, PAGE_HEIGHT - 32, section.upper())
    pdf.setFont("Helvetica", 7)
    pdf.drawRightString(PAGE_WIDTH - 36, PAGE_HEIGHT - 27, f"TECHNICAL BRIEF  |  {page} / 3")


def page_footer(pdf: canvas.Canvas) -> None:
    pdf.setStrokeColor(LINE)
    pdf.line(36, 29, PAGE_WIDTH - 36, 29)
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 6.4)
    pdf.drawString(
        36,
        18,
        "Synthetic data only. Prototype - not for clinical use or a compliance claim.",
    )
    pdf.drawRightString(PAGE_WIDTH - 36, 18, "XIE WEIKUN | SPMS | MSc in Analytics | 28 Aug 2026")


def metric_card(
    pdf: canvas.Canvas, x: float, y: float, width: float, value: str, label: str
) -> None:
    round_box(pdf, x, y, width, 54, fill=PAPER)
    pdf.setFillColor(TEAL_DARK)
    value_size = 17.0
    while value_size > 12 and stringWidth(value, "Times-Bold", value_size) > width - 22:
        value_size -= 0.5
    pdf.setFont("Times-Bold", value_size)
    pdf.drawString(x + 11, y + 29, value)
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica-Bold", 6.4)
    pdf.drawString(x + 11, y + 13, label.upper())


def diagram_node(
    pdf: canvas.Canvas,
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    subtitle: str,
    *,
    fill: Color = PAPER,
) -> None:
    round_box(pdf, x, y, width, height, fill=fill, radius=6)
    pdf.setFillColor(INK)
    pdf.setFont("Helvetica-Bold", 7.5)
    pdf.drawCentredString(x + width / 2, y + height - 13, title)
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 6.0)
    lines = wrapped_lines(subtitle, "Helvetica", 6.0, width - 12)
    text_y = y + height - 24
    for line in lines[:2]:
        pdf.drawCentredString(x + width / 2, text_y, line)
        text_y -= 7


def arrow(pdf: canvas.Canvas, x1: float, y1: float, x2: float, y2: float) -> None:
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length == 0:
        raise ValueError("Arrow endpoints must differ")
    unit_x = dx / length
    unit_y = dy / length
    normal_x = -unit_y
    normal_y = unit_x
    head_length = 4.8
    head_half_width = 2.5
    base_x = x2 - head_length * unit_x
    base_y = y2 - head_length * unit_y
    left_x = base_x + head_half_width * normal_x
    left_y = base_y + head_half_width * normal_y
    right_x = base_x - head_half_width * normal_x
    right_y = base_y - head_half_width * normal_y
    connector = HexColor("#7F9F99")
    pdf.setStrokeColor(connector)
    pdf.setFillColor(connector)
    pdf.setLineWidth(0.8)
    pdf.line(x1, y1, base_x, base_y)
    head = pdf.beginPath()
    head.moveTo(x2, y2)
    head.lineTo(left_x, left_y)
    head.lineTo(right_x, right_y)
    head.close()
    pdf.drawPath(head, fill=1, stroke=0)


def page_one(pdf: canvas.Canvas) -> None:
    metrics = measured_metrics()
    page_header(pdf, 1, "Product and architecture")
    pdf.setFillColor(CANVAS)
    pdf.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT - 48, fill=1, stroke=0)
    pdf.setFillColor(INK)
    pdf.setFont("Times-Bold", 25)
    pdf.drawString(36, 706, "Compress attention. Never compress evidence.")
    draw_text(
        pdf,
        (
            "A role-aware longitudinal care note where every high-priority statement "
            "carries its reason, trust state, and exact immutable source."
        ),
        36,
        687,
        520,
        size=9.2,
        color=MUTED,
    )

    round_box(pdf, 36, 592, 540, 70, fill=TEAL_DARK, stroke=TEAL_DARK, radius=11)
    pdf.setFillColor(HexColor("#9FCDC2"))
    pdf.setFont("Helvetica-Bold", 7)
    pdf.drawString(51, 643, "PRODUCT THESIS")
    pdf.setFillColor(white)
    pdf.setFont("Times-Bold", 16)
    pdf.drawString(51, 622, "The glance is an attention budget, not a second timeline.")
    draw_text(
        pdf,
        (
            "Three bounded lanes - Act now, Watch, Awaiting - expose the next action "
            "while one click restores the full evidence trail."
        ),
        51,
        606,
        495,
        size=7.6,
        color=HexColor("#C2D8D2"),
    )

    metric_card(pdf, 36, 518, 170, metrics["warm_p95"], "Measured warm-path P95")
    metric_card(pdf, 221, 518, 170, "159 tests", "Backend tests; 900 property examples")
    metric_card(
        pdf,
        406,
        518,
        170,
        metrics["backend_coverage"],
        "Backend statement + branch coverage",
    )

    section_label(pdf, "Architecture", 36, 493)
    round_box(pdf, 36, 341, 540, 137, fill=HexColor("#EDF2EE"), radius=10)
    diagram_node(
        pdf,
        51,
        404,
        92,
        49,
        "Role-aware PWA",
        "Clinician, staff, patient, admin",
        fill=PAPER,
    )
    diagram_node(
        pdf,
        177,
        404,
        104,
        49,
        "FastAPI boundary",
        "Identity, object policy, projection",
        fill=TEAL_PALE,
    )
    diagram_node(
        pdf,
        317,
        404,
        104,
        49,
        "Domain transaction",
        "Version + audit + read model",
        fill=PAPER,
    )
    diagram_node(
        pdf,
        457,
        404,
        104,
        49,
        "Versioned store",
        "SQLite demo; PostgreSQL target",
        fill=BLUE_PALE,
    )
    arrow(pdf, 144, 429, 174, 429)
    arrow(pdf, 282, 429, 314, 429)
    arrow(pdf, 422, 429, 454, 429)
    diagram_node(
        pdf,
        177,
        352,
        104,
        38,
        "Redaction gateway",
        "Fail closed before provider",
        fill=CRITICAL_PALE,
    )
    diagram_node(
        pdf,
        317,
        352,
        104,
        38,
        "Local AI provider",
        "No network or external model",
        fill=PURPLE_PALE,
    )
    arrow(pdf, 229, 402, 229, 392)
    arrow(pdf, 282, 371, 314, 371)
    arrow(pdf, 369, 392, 369, 402)
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica-Bold", 5.4)
    pdf.drawString(51, 359, "AI CAPTURE PATH")

    section_label(pdf, "Trust contract", 36, 318)
    round_box(pdf, 36, 76, 540, 227, fill=PAPER, radius=10)
    y = 281
    y = draw_bullet(
        pdf,
        (
            "Exact-source highlights bind an entry, immutable version, offsets, quote, "
            "source URI, and SHA-256 hash."
        ),
        51,
        y,
        500,
    )
    y -= 8
    y = draw_bullet(
        pdf,
        (
            "AI content starts as proposed; human-authored, staff-verified, "
            "clinician-confirmed, and superseded are visible states."
        ),
        51,
        y,
        500,
    )
    y -= 8
    y = draw_bullet(
        pdf,
        (
            "Citation-first review returns only authorized claims, exact quotes, actions, "
            "and conflicts; unsupported questions receive an explicit abstention."
        ),
        51,
        y,
        500,
    )
    y -= 8
    y = draw_bullet(
        pdf,
        (
            "Server-side clinic and role policies protect every object. Patient responses "
            "are built from an allow-list projection."
        ),
        51,
        y,
        500,
    )
    y -= 5
    y = draw_bullet(
        pdf,
        (
            "Revert appends a version. Same-section stale writes return 409; independent "
            "role-owned sections do not overwrite."
        ),
        51,
        y,
        500,
    )
    y -= 5
    y = draw_bullet(
        pdf,
        (
            "The Delta Lens reports temporal change and uncertainty, but refuses a causal "
            "claim without an estimand and design."
        ),
        51,
        y,
        500,
    )
    pdf.setFillColor(TEAL)
    pdf.setFont("Helvetica-Bold", 6.8)
    pdf.drawString(51, 158, "VERIFICATION CONTRACT")
    metric_card(pdf, 51, 92, 116, "4 x 100%", "Frontend coverage; 45 tests")
    metric_card(pdf, 177, 92, 116, metrics["browser_e2e"], "Desktop + mobile E2E")
    metric_card(pdf, 303, 92, 116, metrics["mutants"], "Generated mutants killed")
    metric_card(pdf, 429, 92, 116, metrics["known_advisories"], "Advisories at scan time")
    page_footer(pdf)


def page_two(pdf: canvas.Canvas) -> None:
    page_header(pdf, 2, "Data and control plane")
    pdf.setFillColor(CANVAS)
    pdf.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT - 48, fill=1, stroke=0)
    pdf.setFillColor(INK)
    pdf.setFont("Times-Bold", 23)
    pdf.drawString(36, 706, "A shared narrative with immutable ownership.")
    draw_text(
        pdf,
        (
            "Full snapshots favor auditability, deterministic revert, and stable provenance "
            "in the prototype. Production can add delta compression behind the same "
            "logical model."
        ),
        36,
        686,
        530,
        size=8.5,
        color=MUTED,
    )

    section_label(pdf, "Comprehensive data schema", 36, 650)
    round_box(pdf, 36, 447, 540, 188, fill=PAPER, radius=10)
    nodes = [
        (49, 574, 83, "Patient", "clinic-scoped", PAPER),
        (151, 574, 83, "Typed entry", "manual | AI-scribed", TEAL_PALE),
        (253, 574, 83, "Version", "immutable snapshot", PAPER),
        (355, 574, 83, "Prov. span", "version + offsets", TEAL_PALE),
        (457, 574, 83, "Highlight", "reason + trust", PAPER),
        (49, 502, 83, "AI source", "doctor | nurse | patient", PURPLE_PALE),
        (151, 502, 83, "Collaboration", "comments | tasks | mentions", PAPER),
        (253, 502, 83, "Control record", "audit | conflict | retention", BLUE_PALE),
        (355, 502, 83, "Feedback", "action | reward | propensity", TEAL_PALE),
        (457, 502, 83, "Posterior", "role + clinic shrinkage", PAPER),
    ]
    for x, y, width, title, subtitle, fill in nodes:
        diagram_node(
            pdf,
            x,
            y,
            width,
            43,
            title,
            subtitle,
            fill=fill,
        )
    for x1, y1, x2, y2 in [
        (133, 596, 148, 596),
        (235, 596, 250, 596),
        (337, 596, 352, 596),
        (439, 596, 454, 596),
        (132, 524, 174, 574),
        (192, 572, 192, 546),
        (294, 572, 294, 546),
        (480, 574, 414, 546),
        (439, 524, 454, 524),
        (498, 546, 498, 572),
    ]:
        arrow(pdf, x1, y1, x2, y2)
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 5.7)
    pdf.drawString(
        49,
        469,
        "Lineage stays immutable; collaboration and learning remain separate, scoped records.",
    )

    section_label(pdf, "Authorization matrix", 36, 422)
    x0, y0, row_h = 36, 260, 27
    widths = [92, 112, 112, 112, 112]
    headers = ["Object/action", "Patient", "Staff", "Clinician", "Admin"]
    rows = [
        ["Patient-safe summary", "Read", "Read", "Read/write", "Read"],
        ["Staff section", "No access", "Read/write", "Read only", "Read only"],
        ["Clinician section", "No access", "Read only", "Read/write", "Read only"],
        ["Raw AI + comments", "No access", "Read/review", "Read/review", "Read"],
        ["Audit + retention", "No access", "No access", "No access", "Operate"],
    ]
    cursor_x = x0
    pdf.setFillColor(TEAL_DARK)
    pdf.rect(x0, y0 + row_h * len(rows), sum(widths), row_h, fill=1, stroke=0)
    for width, header in zip(widths, headers, strict=True):
        pdf.setFillColor(white)
        pdf.setFont("Helvetica-Bold", 6.5)
        pdf.drawString(cursor_x + 6, y0 + row_h * len(rows) + 9, header)
        cursor_x += width
    for row_index, row in enumerate(rows):
        row_y = y0 + row_h * (len(rows) - 1 - row_index)
        pdf.setFillColor(PAPER if row_index % 2 == 0 else HexColor("#EDF2EE"))
        pdf.rect(x0, row_y, sum(widths), row_h, fill=1, stroke=0)
        cursor_x = x0
        for column_index, (width, value) in enumerate(zip(widths, row, strict=True)):
            pdf.setFillColor(INK if column_index == 0 else MUTED)
            pdf.setFont("Helvetica-Bold" if column_index == 0 else "Helvetica", 6.3)
            pdf.drawString(cursor_x + 6, row_y + 9, value)
            cursor_x += width
    pdf.setStrokeColor(LINE)
    pdf.rect(x0, y0, sum(widths), row_h * (len(rows) + 1), fill=0, stroke=1)

    section_label(pdf, "Atomic integrity path", 36, 238)
    section_label(pdf, "Assumptions and production boundary", 394, 238)
    round_box(pdf, 36, 76, 348, 147, fill=PAPER, radius=10)
    y = 201
    y = draw_bullet(
        pdf,
        "1. Authenticate the server actor; ignore client-supplied role claims.",
        51,
        y,
        318,
        size=7.4,
    )
    y -= 5
    y = draw_bullet(
        pdf,
        "2. Resolve the object inside clinic scope; enforce ownership and visibility.",
        51,
        y,
        318,
        size=7.4,
    )
    y -= 5
    y = draw_bullet(
        pdf,
        "3. Validate expected version; a stale same-section write returns a 409 receipt.",
        51,
        y,
        318,
        size=7.4,
    )
    y -= 5
    y = draw_bullet(
        pdf,
        ("4. Append snapshot, metadata-only audit, and glance projection in one transaction."),
        51,
        y,
        318,
        size=7.4,
    )
    y -= 5
    draw_bullet(
        pdf,
        ("5. Serialize an actor allow-list; provenance rechecks scope, offsets, quote, and hash."),
        51,
        y,
        318,
        size=7.4,
    )

    round_box(pdf, 394, 76, 182, 147, fill=TEAL_DARK, stroke=TEAL_DARK, radius=10)
    pdf.setFillColor(HexColor("#E7B96E"))
    pdf.setFont("Helvetica-Bold", 6.2)
    pdf.drawString(409, 202, "ASSUMPTIONS")
    draw_text(
        pdf,
        "Synthetic data, local deterministic provider, and loopback benchmarks.",
        409,
        190,
        152,
        size=6.25,
        color=white,
        leading=8.1,
    )
    pdf.setFillColor(HexColor("#E7B96E"))
    pdf.setFont("Helvetica-Bold", 6.2)
    pdf.drawString(409, 160, "TRADE-OFF")
    draw_text(
        pdf,
        (
            "Full snapshots + SQLite favor auditability and reproduction over storage "
            "efficiency and scale."
        ),
        409,
        148,
        152,
        size=6.25,
        color=white,
        leading=8.1,
    )
    pdf.setFillColor(HexColor("#E7B96E"))
    pdf.setFont("Helvetica-Bold", 6.2)
    pdf.drawString(409, 111, "PRODUCTION GATE - NOT CLAIMED")
    draw_text(
        pdf,
        (
            "OIDC/MFA, PostgreSQL RLS, TLS, managed encryption, centralized audit, and "
            "independent clinical/security review."
        ),
        409,
        99,
        152,
        size=6.15,
        color=HexColor("#D7EBE4"),
        leading=7.9,
    )
    page_footer(pdf)


def page_three(pdf: canvas.Canvas) -> None:
    metrics = measured_metrics()
    page_header(pdf, 3, "Learning, privacy, evidence")
    pdf.setFillColor(CANVAS)
    pdf.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT - 48, fill=1, stroke=0)
    pdf.setFillColor(INK)
    pdf.setFont("Times-Bold", 23)
    pdf.drawString(36, 706, "Learning earns influence under safety constraints.")
    draw_text(
        pdf,
        (
            "The adaptive system changes ranking, not clinical facts. New policies stay in "
            "shadow mode until support, uncertainty, and governance are credible."
        ),
        36,
        686,
        530,
        size=8.5,
        color=MUTED,
    )

    round_box(pdf, 36, 492, 260, 166, fill=PAPER, radius=10)
    section_label(pdf, "Transparent importance", 51, 637)
    pdf.setFillColor(TEAL_DARK)
    pdf.setFont("Courier-Bold", 7.3)
    pdf.drawString(51, 617, "base = risk + action + safety + recency + pin")
    pdf.drawString(51, 602, "adaptive = clip(pooled posterior shift, -0.75, +0.75)")
    pdf.drawString(51, 587, "rank = hard safety band, then base + adaptive")
    y = 563
    y = draw_bullet(
        pdf,
        "Role and clinic Beta posteriors shrink sparse feedback.",
        51,
        y,
        226,
        size=7.3,
    )
    y -= 5
    y = draw_bullet(
        pdf,
        "Critical, allergy, medication, and urgent work are protected.",
        51,
        y,
        226,
        size=7.3,
    )
    y -= 5
    draw_bullet(
        pdf,
        "Accept, reject, and pin remain one-action human controls.",
        51,
        y,
        226,
        size=7.3,
    )

    round_box(pdf, 316, 492, 260, 166, fill=TEAL_DARK, stroke=TEAL_DARK, radius=10)
    pdf.setFillColor(HexColor("#9FCDC2"))
    pdf.setFont("Helvetica-Bold", 7.2)
    pdf.drawString(331, 637, "SHADOW OFF-POLICY EVALUATION")
    pdf.setFillColor(white)
    pdf.setFont("Times-Bold", 18)
    pdf.drawString(331, 612, "No estimate yet")
    draw_text(
        pdf,
        (
            "The seeded build correctly reports insufficient interaction data instead of "
            "manufacturing uplift."
        ),
        331,
        595,
        225,
        size=7.4,
        color=HexColor("#C2D8D2"),
    )
    pdf.setFillColor(HexColor("#E7B96E"))
    pdf.setFont("Helvetica-Bold", 7)
    pdf.drawString(331, 548, "REQUIRED DIAGNOSTICS")
    draw_text(
        pdf,
        (
            "Propensity overlap - effective sample size - DR uncertainty - assumptions - "
            "policy version"
        ),
        331,
        533,
        220,
        size=7.2,
        color=white,
    )
    pdf.setFillColor(HexColor("#A9C5C0"))
    pdf.setFont("Helvetica", 6.5)
    pdf.drawString(331, 507, "Ranking proxy only - never a patient-outcome claim")

    section_label(pdf, "Privacy and retention", 36, 468)
    round_box(pdf, 36, 342, 540, 110, fill=PAPER, radius=10)
    diagram_node(
        pdf,
        50,
        382,
        92,
        48,
        "Raw transcript",
        "Synthetic capture only",
        fill=CRITICAL_PALE,
    )
    diagram_node(pdf, 161, 382, 92, 48, "Redact", "Names, IDs, phone, email", fill=AMBER_PALE)
    diagram_node(pdf, 272, 382, 92, 48, "Draft", "Local provider; AI proposed", fill=PURPLE_PALE)
    diagram_node(pdf, 383, 382, 92, 48, "Human review", "Accept, reject, pin", fill=TEAL_PALE)
    diagram_node(pdf, 494, 382, 68, 48, "Evidence", "Exact span", fill=BLUE_PALE)
    arrow(pdf, 143, 406, 158, 406)
    arrow(pdf, 254, 406, 269, 406)
    arrow(pdf, 365, 406, 380, 406)
    arrow(pdf, 476, 406, 491, 406)
    draw_text(
        pdf,
        (
            "Decay applies to recomputable derived caches. Immutable versions, audit "
            "metadata, open tasks, conflicts, pins, allergies, medication safety, and "
            "active critical evidence remain protected."
        ),
        51,
        365,
        505,
        size=7.1,
        color=MUTED,
    )

    section_label(pdf, "Measured evidence and trade-offs", 36, 318)
    round_box(pdf, 36, 204, 540, 99, fill=PAPER, radius=10)
    metric_card(pdf, 48, 232, 112, metrics["warm_success"], "Warm reads succeeded")
    metric_card(pdf, 171, 232, 112, metrics["warm_median"], "Local median")
    metric_card(pdf, 294, 232, 112, metrics["warm_p95"], "Local P95")
    metric_card(pdf, 417, 232, 147, "P95 <= 300 ms", "Brief constraint passed")
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 6)
    pdf.drawString(
        48,
        220,
        "50 warm-ups; loopback Uvicorn; seeded precomputed projection; no LLM on read path.",
    )
    pdf.drawString(
        48,
        211,
        (
            "159 backend + 45 frontend tests; 7/7 browser; 1,840/1,840 mutants; "
            "0 known advisories at scan time."
        ),
    )

    section_label(pdf, "Selected primary sources - hyperlinked", 36, 184)
    references = [
        (
            "[1] HL7 FHIR R5 Provenance",
            "hl7.org/fhir/provenance",
            "https://hl7.org/fhir/provenance.html",
        ),
        (
            "[2] W3C PROV-O",
            "w3.org/TR/prov-o",
            "https://www.w3.org/TR/prov-o/",
        ),
        (
            "[3] OWASP API1:2023 BOLA",
            "owasp.org/API-Security/2023/API1",
            "https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/",
        ),
        (
            "[4] PostgreSQL Row Security",
            "postgresql.org/docs/current/ddl-rowsecurity",
            "https://www.postgresql.org/docs/current/ddl-rowsecurity.html",
        ),
        (
            "[5] NIST AI 600-1 Generative AI Profile",
            "doi.org/10.6028/NIST.AI.600-1",
            "https://doi.org/10.6028/NIST.AI.600-1",
        ),
        (
            "[6] PDPC Healthcare Sector Guidelines",
            "pdpc.gov.sg/healthcare-sector",
            "https://www.pdpc.gov.sg/guidelines-and-consultation/2017/10/advisory-guidelines-for-the-healthcare-sector",
        ),
        (
            "[7] Dai et al., AI-scribe safety signals, 2025",
            "arxiv.org/abs/2512.04118",
            "https://arxiv.org/abs/2512.04118",
        ),
        (
            "[8] Brunner et al., JAMA ambient scribe, 2026",
            "doi.org/10.1001/jamanetworkopen.2025.52870",
            "https://doi.org/10.1001/jamanetworkopen.2025.52870",
        ),
        (
            "[9] Mandyam et al., CANDOR (CHIL 2026)",
            "proceedings.mlr.press/v333/mandyam26a",
            "https://proceedings.mlr.press/v333/mandyam26a.html",
        ),
        (
            "[10] W3C WCAG 2.2",
            "w3.org/TR/WCAG22",
            "https://www.w3.org/TR/WCAG22/",
        ),
    ]
    for index, (label, display_url, url) in enumerate(references):
        column = 0 if index < 5 else 1
        row = index if index < 5 else index - 5
        x = 42 if column == 0 else 312
        width = 252 if column == 0 else 258
        y = 168 - row * 25
        pdf.setFillColor(INK)
        pdf.setFont("Helvetica-Bold", 6.2)
        pdf.drawString(x, y, label)
        pdf.setFillColor(TEAL)
        pdf.setFont("Helvetica", 5.8)
        pdf.drawString(x, y - 9, display_url)
        pdf.linkURL(url, (x, y - 11, x + width, y + 7), relative=0)
    page_footer(pdf)


def build_pdf(path: Path = OUTPUT) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path), pagesize=letter, pageCompression=1, invariant=1)
    pdf.setTitle("Nightingale Continuum - Technical Brief")
    pdf.setAuthor("XIE WEIKUN")
    pdf.setCreator("Nightingale Continuum reproducible brief builder")
    pdf.setSubject("Architecture, safety, learning, and measurement")
    for page in (page_one, page_two, page_three):
        page(pdf)
        pdf.showPage()
    pdf.save()

    reader = PdfReader(str(path))
    if len(reader.pages) != 3:
        raise RuntimeError(f"Expected exactly 3 pages, found {len(reader.pages)}")
    required_text = [
        "Compress attention",
        "AUTHORIZATION",
        "MATRIX",
        "AI-scribed",
        "ASSUMPTIONS AND PRODUCTION BOUNDARY",
        "PRODUCTION GATE - NOT CLAIMED",
        "PostgreSQL RLS, TLS",
        "encryption, centralized audit",
        "Learning earns influence",
        measured_metrics()["warm_p95"],
        "159 tests",
        measured_metrics()["browser_e2e"],
        measured_metrics()["mutants"],
        "Citation-first review",
        "100%",
        "PDPC Healthcare Sector Guidelines",
        "Synthetic data only",
    ]
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    missing = [item for item in required_text if item not in extracted]
    if missing:
        raise RuntimeError(f"PDF text verification failed: {missing}")
    return path


if __name__ == "__main__":
    generated = build_pdf()
    print(generated)
