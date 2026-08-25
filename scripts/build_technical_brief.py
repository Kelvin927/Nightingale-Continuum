#!/usr/bin/env python3
from __future__ import annotations

import json
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
    return {
        "warm_success": (f"{warm['samples_successful']} / {warm['samples_requested']}"),
        "warm_median": f"{warm['latency_ms']['median']:.3f} ms",
        "warm_p95": f"{warm['latency_ms']['p95']:.3f} ms",
        "backend_coverage": (f"{coverage['totals']['percent_statements_covered']:.0f}%"),
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
    pdf.setFillColor(HexColor("#BCE0D3"))
    pdf.circle(34, PAGE_HEIGHT - 24, 10, fill=0, stroke=1)
    pdf.line(28, PAGE_HEIGHT - 26, 39, PAGE_HEIGHT - 20)
    pdf.line(30, PAGE_HEIGHT - 31, 41, PAGE_HEIGHT - 25)
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
    pdf.drawRightString(PAGE_WIDTH - 36, 18, "Candidate build | 26 Aug 2026")


def metric_card(
    pdf: canvas.Canvas, x: float, y: float, width: float, value: str, label: str
) -> None:
    round_box(pdf, x, y, width, 54, fill=PAPER)
    pdf.setFillColor(TEAL_DARK)
    pdf.setFont("Times-Bold", 17)
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
    pdf.setFont("Helvetica", 5.8)
    lines = wrapped_lines(subtitle, "Helvetica", 5.8, width - 12)
    text_y = y + height - 24
    for line in lines[:2]:
        pdf.drawCentredString(x + width / 2, text_y, line)
        text_y -= 7


def arrow(pdf: canvas.Canvas, x1: float, y1: float, x2: float, y2: float) -> None:
    pdf.setStrokeColor(HexColor("#8EA7A2"))
    pdf.setFillColor(HexColor("#8EA7A2"))
    pdf.setLineWidth(0.8)
    pdf.line(x1, y1, x2, y2)
    direction = 1 if x2 >= x1 else -1
    pdf.line(x2, y2, x2 - 4 * direction, y2 + 2.5)
    pdf.line(x2, y2, x2 - 4 * direction, y2 - 2.5)


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
    metric_card(pdf, 221, 518, 170, "124 tests", "Backend and required micro-tests")
    metric_card(pdf, 406, 518, 170, metrics["backend_coverage"], "Line + branch coverage")

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
            "Server-side clinic and role policies protect every object. Patient responses "
            "are built from an allow-list projection."
        ),
        51,
        y,
        500,
    )
    y -= 8
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
    y -= 8
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
    metric_card(pdf, 51, 92, 116, "4 x 100%", "Frontend coverage + 5 E2E")
    metric_card(pdf, 177, 92, 116, "900", "Property examples")
    metric_card(pdf, 303, 92, 116, "0 known", "Dependency advisories")
    metric_card(pdf, 429, 92, 116, "0", "Mutation survivors")
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
        (49, 574, 83, "Patient", "clinic-scoped"),
        (151, 574, 83, "Entry", "stable identity"),
        (253, 574, 83, "Version", "immutable snapshot"),
        (355, 574, 83, "Prov. span", "version + offsets"),
        (457, 574, 83, "Highlight", "reason + trust"),
        (151, 502, 83, "Comment", "thread + assignment"),
        (253, 502, 83, "Audit event", "metadata hash chain"),
        (355, 502, 83, "Feedback", "reward + propensity"),
        (457, 502, 83, "Posterior", "role + clinic shrinkage"),
        (49, 502, 83, "Task", "owner + urgency"),
        (202, 457, 96, "Conflict", "explicit disposition"),
        (337, 457, 96, "Retention", "tier + manifest"),
    ]
    for x, y, width, title, subtitle in nodes:
        diagram_node(
            pdf,
            x,
            y,
            width,
            43 if y > 460 else 34,
            title,
            subtitle,
            fill=TEAL_PALE if title in {"Entry", "Prov. span", "Feedback"} else PAPER,
        )
    for x1, y1, x2, y2 in [
        (133, 596, 148, 596),
        (235, 596, 250, 596),
        (337, 596, 352, 596),
        (439, 596, 454, 596),
        (192, 572, 192, 546),
        (294, 572, 294, 546),
        (396, 572, 396, 546),
        (498, 572, 498, 546),
        (90, 572, 90, 546),
        (294, 501, 263, 493),
        (396, 501, 385, 493),
    ]:
        arrow(pdf, x1, y1, x2, y2)

    section_label(pdf, "Authorization matrix", 36, 422)
    x0, y0, row_h = 36, 281, 27
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

    section_label(pdf, "Atomic integrity path", 36, 259)
    round_box(pdf, 36, 76, 540, 168, fill=PAPER, radius=10)
    y = 222
    y = draw_bullet(
        pdf,
        "1. Resolve actor identity from the server-side membership; ignore client role claims.",
        51,
        y,
        500,
    )
    y -= 6
    y = draw_bullet(
        pdf,
        "2. Resolve the object inside clinic scope and check role ownership and visibility.",
        51,
        y,
        500,
    )
    y -= 6
    y = draw_bullet(
        pdf,
        (
            "3. Validate expected version. A stale same-section mutation fails with a "
            "deterministic conflict receipt."
        ),
        51,
        y,
        500,
    )
    y -= 6
    y = draw_bullet(
        pdf,
        (
            "4. Append the snapshot, move the current pointer, append metadata-only audit, "
            "and refresh the glance projection."
        ),
        51,
        y,
        500,
    )
    y -= 6
    draw_bullet(
        pdf,
        (
            "5. Serialize only fields allowed for the actor; provenance resolution repeats "
            "scope and integrity checks."
        ),
        51,
        y,
        500,
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
    round_box(pdf, 36, 214, 540, 89, fill=PAPER, radius=10)
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

    section_label(pdf, "Selected primary sources", 36, 191)
    references = [
        ("[1] HL7 FHIR R5 Provenance", "https://hl7.org/fhir/provenance.html"),
        ("[2] W3C PROV-O", "https://www.w3.org/TR/prov-o/"),
        (
            "[3] OWASP API1:2023 BOLA",
            "https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/",
        ),
        (
            "[4] NIST AI 600-1 Generative AI Profile",
            "https://doi.org/10.6028/NIST.AI.600-1",
        ),
        (
            "[5] Dai et al., AI-scribe safety signals, arXiv 2025",
            "https://arxiv.org/abs/2512.04118",
        ),
        (
            "[6] Ambient scribe evaluation, JAMA Network Open, 2026",
            "https://jamanetwork.com/journals/jamanetworkopen/fullarticle/2843515",
        ),
        (
            "[7] Mandyam et al., CANDOR, CHIL 2026",
            "https://proceedings.mlr.press/v333/mandyam26a.html",
        ),
    ]
    y = 177
    for label, url in references:
        pdf.setFillColor(INK)
        pdf.setFont("Helvetica", 6.25)
        pdf.drawString(42, y, label)
        pdf.setFillColor(TEAL)
        pdf.drawRightString(570, y, url)
        pdf.linkURL(url, (300, y - 2, 570, y + 7), relative=0)
        y -= 15
    page_footer(pdf)


def build_pdf(path: Path = OUTPUT) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path), pagesize=letter, pageCompression=1, invariant=1)
    pdf.setTitle("Nightingale Continuum - Technical Brief")
    pdf.setAuthor("Candidate build")
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
        "Learning earns influence",
        measured_metrics()["warm_p95"],
        "124 tests",
        "5 E2E",
        "100%",
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
