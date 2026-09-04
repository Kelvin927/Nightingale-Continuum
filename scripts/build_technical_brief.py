#!/usr/bin/env python3
# ruff: noqa: E501 - source prose remains searchable as complete sentences
"""Build the three-page, evidence-linked Nightingale feedback brief."""

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

INK = HexColor("#18383B")
MUTED = HexColor("#657A78")
TEAL = HexColor("#176E70")
TEAL_DARK = HexColor("#103E41")
TEAL_PALE = HexColor("#E4F0EC")
PAPER = HexColor("#FFFEFB")
CANVAS = HexColor("#F2F5F1")
LINE = HexColor("#D6E0DA")
GREEN = HexColor("#24725F")
GREEN_PALE = HexColor("#E4F2EB")
AMBER = HexColor("#8A5B17")
AMBER_PALE = HexColor("#FAF0DB")
RED = HexColor("#9A4038")
RED_PALE = HexColor("#F8E8E5")
BLUE_PALE = HexColor("#E8EFF5")


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise RuntimeError(f"Missing generated evidence: {path.relative_to(ROOT)}")
    return json.loads(path.read_text(encoding="utf-8"))


@cache
def measured_metrics() -> dict[str, str]:
    warm = _load_json(EVIDENCE / "glance_benchmark.json")
    coverage = _load_json(EVIDENCE / "backend_coverage.json")["totals"]
    frontend = _load_json(EVIDENCE / "frontend-coverage" / "coverage-summary.json")["total"]
    mutation = _load_json(EVIDENCE / "mutation_testing.json")["totals"]
    security = _load_json(EVIDENCE / "dependency_security.json")
    browser_path = EVIDENCE / "browser_e2e.json"
    browser = _load_json(browser_path)["stats"] if browser_path.exists() else None
    frontend_complete = all(
        frontend[key]["pct"] == 100 for key in ("statements", "branches", "functions", "lines")
    )
    known_advisories = (
        security["python"]["known_vulnerabilities"] + security["frontend"]["known_vulnerabilities"]
    )
    if not (
        coverage["percent_statements_covered"] == 100
        and coverage["percent_branches_covered"] == 100
        and frontend_complete
        and mutation["survived"] == 0
        and mutation["checked"] == mutation["total"]
        and known_advisories == 0
        and (
            browser is None
            or (browser["unexpected"] == 0 and browser["flaky"] == 0 and browser["skipped"] == 0)
        )
    ):
        raise RuntimeError("Technical brief evidence gates are not all satisfied")
    return {
        "coverage": "100% / 100%",
        "browser": (
            "pending CI" if browser is None else f"{browser['expected']} / {browser['expected']}"
        ),
        "mutants": f"{mutation['killed']:,} / {mutation['checked']:,}",
        "warm_p95": f"{warm['latency_ms']['p95']:.3f} ms",
        "advisories": str(known_advisories),
    }


@cache
def source_line(relative: str, needle: str) -> int:
    path = ROOT / relative
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if needle in line:
            return number
    raise RuntimeError(f"Could not locate brief evidence marker {needle!r} in {relative}")


def code_ref(relative: str, needle: str) -> str:
    return f"{relative}:{source_line(relative, needle)}"


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


def text_block(
    pdf: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    width: float,
    *,
    font: str = "Helvetica",
    size: float = 6.4,
    color: Color = INK,
    leading: float | None = None,
    max_lines: int | None = None,
) -> float:
    line_height = leading or size * 1.32
    lines = wrapped_lines(text, font, size, width)
    if max_lines is not None and len(lines) > max_lines:
        raise RuntimeError(f"Brief copy exceeds {max_lines} lines: {text}")
    pdf.setFillColor(color)
    pdf.setFont(font, size)
    for line in lines:
        pdf.drawString(x, y, line)
        y -= line_height
    return y


def round_box(
    pdf: canvas.Canvas,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    fill: Color = PAPER,
    stroke: Color = LINE,
    radius: float = 7,
) -> None:
    pdf.setFillColor(fill)
    pdf.setStrokeColor(stroke)
    pdf.setLineWidth(0.65)
    pdf.roundRect(x, y, width, height, radius, fill=1, stroke=1)


def page_base(pdf: canvas.Canvas, page: int, section: str) -> None:
    pdf.setFillColor(CANVAS)
    pdf.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=1, stroke=0)
    pdf.setFillColor(TEAL_DARK)
    pdf.rect(0, PAGE_HEIGHT - 48, PAGE_WIDTH, 48, fill=1, stroke=0)
    pdf.setStrokeColor(HexColor("#9DCEC3"))
    pdf.setLineWidth(1.1)
    pdf.circle(34, PAGE_HEIGHT - 24, 10, fill=0, stroke=1)
    pdf.setStrokeColor(HexColor("#D9EBE5"))
    pdf.setLineWidth(1.1)
    pdf.line(29, PAGE_HEIGHT - 29, 29, PAGE_HEIGHT - 20)
    pdf.line(29, PAGE_HEIGHT - 20, 39, PAGE_HEIGHT - 29)
    pdf.line(39, PAGE_HEIGHT - 29, 39, PAGE_HEIGHT - 20)
    pdf.setFillColor(white)
    pdf.setFont("Times-Bold", 12)
    pdf.drawString(54, PAGE_HEIGHT - 21, "Nightingale Continuum")
    pdf.setFillColor(HexColor("#A9C7C1"))
    pdf.setFont("Helvetica-Bold", 6.2)
    pdf.drawString(54, PAGE_HEIGHT - 32, section.upper())
    pdf.setFillColor(white)
    pdf.setFont("Helvetica", 7)
    pdf.drawRightString(PAGE_WIDTH - 36, PAGE_HEIGHT - 27, f"TECHNICAL BRIEF  |  {page} / 3")
    pdf.setStrokeColor(LINE)
    pdf.line(36, 29, PAGE_WIDTH - 36, 29)
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 6.2)
    pdf.drawString(
        36,
        18,
        "Synthetic data only. Prototype - not for clinical use or a compliance claim.",
    )
    pdf.drawRightString(PAGE_WIDTH - 36, 18, "XIE WEIKUN | SPMS | MSc in Analytics | 05 Sep 2026")


def title_block(pdf: canvas.Canvas, title: str, subtitle: str, *, kicker: str) -> None:
    pdf.setFillColor(TEAL)
    pdf.setFont("Helvetica-Bold", 6.5)
    pdf.drawString(36, 721, kicker.upper())
    pdf.setFillColor(INK)
    pdf.setFont("Times-Bold", 20)
    pdf.drawString(36, 698, title)
    text_block(pdf, subtitle, 36, 682, 540, size=7.6, color=MUTED, max_lines=2)


def status_style(status: str) -> tuple[Color, Color]:
    if status.startswith("SURVIVES"):
        return GREEN_PALE, GREEN
    if status == "PARTIAL":
        return AMBER_PALE, AMBER
    return RED_PALE, RED


def scenario_card(
    pdf: canvas.Canvas,
    *,
    number: str,
    title: str,
    status: str,
    where: str,
    failure: str,
    built: str,
    x: float,
    y: float,
    width: float = 262,
    height: float = 137,
) -> None:
    round_box(pdf, x, y, width, height, fill=PAPER)
    pdf.setFillColor(TEAL_DARK)
    pdf.circle(x + 17, y + height - 18, 10, fill=1, stroke=0)
    pdf.setFillColor(white)
    pdf.setFont("Helvetica-Bold", 6.5)
    pdf.drawCentredString(x + 17, y + height - 20.5, number)
    pdf.setFillColor(INK)
    pdf.setFont("Helvetica-Bold", 7.4)
    pdf.drawString(x + 31, y + height - 16, title)
    fill, foreground = status_style(status)
    pill_width = stringWidth(status, "Helvetica-Bold", 5.4) + 12
    pdf.setFillColor(fill)
    pdf.roundRect(
        x + width - pill_width - 9,
        y + height - 25,
        pill_width,
        13,
        5,
        fill=1,
        stroke=0,
    )
    pdf.setFillColor(foreground)
    pdf.setFont("Helvetica-Bold", 5.4)
    pdf.drawCentredString(x + width - pill_width / 2 - 9, y + height - 20.3, status)

    cursor = y + height - 39
    pdf.setFillColor(TEAL)
    pdf.setFont("Helvetica-Bold", 5.2)
    pdf.drawString(x + 12, cursor, "WHERE")
    cursor = text_block(
        pdf,
        where,
        x + 44,
        cursor,
        width - 56,
        font="Courier",
        size=5.25,
        color=MUTED,
        max_lines=2,
    )
    cursor -= 2
    pdf.setFillColor(RED)
    pdf.setFont("Helvetica-Bold", 5.2)
    pdf.drawString(x + 12, cursor, "FIRST BREAK")
    cursor = text_block(pdf, failure, x + 12, cursor - 8, width - 24, size=5.9, max_lines=3)
    cursor -= 2
    pdf.setFillColor(GREEN)
    pdf.setFont("Helvetica-Bold", 5.2)
    pdf.drawString(x + 12, cursor, "BUILT + RESIDUAL BOUNDARY")
    text_block(pdf, built, x + 12, cursor - 8, width - 24, size=5.9, max_lines=5)


def scenario_data() -> list[dict[str, str]]:
    return [
        {
            "number": "01",
            "title": "Phone-only patient access",
            "status": "SURVIVES - LOCAL",
            "where": code_ref("backend/app/access.py", "def issue_access_claim"),
            "failure": "A real patient still fails if the production channel broker, recovery policy, or device secret is absent.",
            "built": "One-use, hashed, rate-limited channel claim; device-bound patient session; server re-fetches a patient-only projection. Email is never identity. Production assurance level remains an owner decision.",
        },
        {
            "number": "02",
            "title": "One-line tenant isolation defect",
            "status": "PARTIAL",
            "where": code_ref("deployment/postgres/tenant_rls.sql", "ALTER TABLE patients ENABLE"),
            "failure": "SQLite would rely on application predicates; one missed predicate can disclose rows reachable by that route.",
            "built": "Central actor/object policy, cross-tenant concealment tests, RLS for every tenant table, and FORCE RLS target. It survives only after PostgreSQL migration and non-owner runtime-role verification.",
        },
        {
            "number": "03",
            "title": "PHI through logs and telemetry",
            "status": "SURVIVES - SCOPED",
            "where": code_ref("backend/app/telemetry.py", "ALLOWED_ATTRIBUTE_KEYS"),
            "failure": "An unregistered SDK, host proxy, crash agent, or deployment access log can create a new egress path.",
            "built": "Low-cardinality allow-list telemetry, route templates, normalized request IDs, metadata-only audit and synthetic identifier canary tests. Third-party dashboards and retention require deployment inspection.",
        },
        {
            "number": "04",
            "title": "Redaction before every model call",
            "status": "SURVIVES - LOCAL",
            "where": code_ref("backend/app/scribe.py", "payload = RedactedPayload"),
            "failure": "A future provider call outside the typed gateway would bypass the proof.",
            "built": "Identifiers are removed and clinical anchors compared before RedactedPayload exists; ProviderGateway accepts only that type. Provider spies prove zero calls on fidelity failure. Network egress policy is not deployed.",
        },
        {
            "number": "05",
            "title": "Clinic B onboarding",
            "status": "SURVIVES - DEMO",
            "where": code_ref("backend/app/configuration.py", "class ClinicConfiguration"),
            "failure": "Production onboarding fails on missing secrets, regional contracts, migration state, or policy ownership.",
            "built": "Versioned locale, channel, provider, timeout, retention, feature and escalation configuration; second clinic works without code edits; rollback and cross-clinic cache/policy tests. Secret provisioning stays external.",
        },
        {
            "number": "06",
            "title": "Trilingual noisy consult",
            "status": "PARTIAL",
            "where": code_ref("backend/app/capture.py", "def add_segment"),
            "failure": "The browser records audio but no live ASR adapter turns it into transcript events; real Hokkien can be mistranscribed or omitted.",
            "built": "Provider-neutral timestamped language spans, speaker label, ASR/audio quality and explicit unsupported-language abstention. No WER/CER or safety-concept recall claim without licensed SEA audio and native review.",
        },
        {
            "number": "07",
            "title": "Allergy at minute two",
            "status": "SURVIVES - SIMULATED",
            "where": code_ref("backend/app/capture.py", "def _detect_safety_signals"),
            "failure": "Real detection latency and sensitivity fail with an inaccurate or delayed ASR adapter.",
            "built": "Idempotent ordered segment stream emits a provisional, timestamp-bound allergy signal before finalization; unsupported spans abstain; clinician confirm/dismiss is audited. The test is event-level, not real audio.",
        },
        {
            "number": "08",
            "title": "Provider hangs for 45 seconds",
            "status": "SURVIVES - SIMULATED",
            "where": code_ref(
                "backend/app/providers.py", "future.result(timeout=self.timeout_seconds)"
            ),
            "failure": "A provider that ignores cancellation can consume worker capacity after the user has received a fallback.",
            "built": "Server deadline, non-blocking cancellation, circuit breaker, stable failure code and deterministic rule-only draft; UI labels degradation. Production needs process isolation, concurrency budgets and queue monitoring.",
        },
        {
            "number": "09",
            "title": "Provider returns 503 for one hour",
            "status": "SURVIVES - SIMULATED",
            "where": code_ref("backend/app/providers.py", "def _fallback"),
            "failure": "Without a durable production job queue, automatic recovery work can be lost across process restart.",
            "built": "Repeated failures open the circuit; deterministic evidence remains and new drafts are visibly rule-only or fail closed. No stale AI result is relabelled as current. Durable retry infrastructure is still external.",
        },
        {
            "number": "10",
            "title": "Concurrent note edits",
            "status": "SURVIVES - CONTRACT",
            "where": code_ref("backend/app/care.py", "def edit_entry"),
            "failure": "True character-level live coauthoring is not supported; disconnected local drafts still depend on browser persistence.",
            "built": "Expected-version write prevents lost update; 409 returns base/current/proposed snapshots; deterministic three-way merge is only a reviewed draft and cannot save until explicitly compared.",
        },
        {
            "number": "11",
            "title": "Appointment link never arrives",
            "status": "SURVIVES - SIMULATED",
            "where": code_ref("backend/app/delivery.py", "def escalate_appointment_followups"),
            "failure": "The demo admin records provider receipts; no contracted channel or signed webhook proves live delivery semantics.",
            "built": "Purpose-specific outbox distinguishes queued, accepted, delivered, patient acknowledged, failed and overdue. Failed/overdue creates one owned care task; late acknowledgement closes it without erasing history.",
        },
        {
            "number": "12",
            "title": "Wrong dosage reaches patient",
            "status": "PARTIAL",
            "where": code_ref("backend/app/terminology.py", "def assess_medication_terminology"),
            "failure": "A clinician can still approve a clinically wrong but syntactically supported dose; the local vocabulary is not a drug-safety authority.",
            "built": "Exact source offsets, unit normalization, unresolved-dose block, medication-specific attestation, immutable approval receipt and correction delivery. RxNorm/local formulary and clinical validation remain production gates.",
        },
        {
            "number": "13",
            "title": "Conflicting allergy assertions",
            "status": "PARTIAL",
            "where": code_ref("backend/app/conflicts.py", "def detect_structured_conflicts"),
            "failure": "Unseen phrasing, temporality, certainty or language may evade the bounded deterministic detector.",
            "built": "Safety-floor conflict card presents two immutable sources side by side; reviewer must inspect both, record rationale, or escalate unresolved. No latest-note or source-hierarchy auto-winner.",
        },
        {
            "number": "14",
            "title": "Meaningless confidence number",
            "status": "SURVIVES - DEFINED",
            "where": code_ref("backend/app/importance.py", "def evidence_support_score"),
            "failure": "A user can still misread evidence support as probability if explanatory copy is removed later.",
            "built": "Evidence support is a versioned trust-state mapping, never model self-confidence; bands, decomposition, error tests and fail-safe behavior are visible. Unsupported review questions abstain.",
        },
        {
            "number": "15",
            "title": "Exposure bias and fatigue",
            "status": "PARTIAL",
            "where": code_ref("backend/app/evaluation.py", "def evaluate_shadow_policy"),
            "failure": "Deterministic surfaced-only data cannot estimate unseen outcomes or justify promotion.",
            "built": "Feedback changes a shadow score only; server logs propensity; hard allergy/medication/urgent floors resist dismissal; evaluation refuses promotion without overlap, ESS and uncertainty evidence. No live causal claim.",
        },
        {
            "number": "16",
            "title": "Edited source behind a citation",
            "status": "SURVIVES - LOCAL",
            "where": code_ref("backend/app/provenance.py", "def resolve_span"),
            "failure": "A deleted/corrupted store or untracked external source cannot be reconstructed by the application hash alone.",
            "built": "Citation remains bound to immutable version, offsets, quote and hash; current edit marks dependency stale and shows original/current side by side. Regeneration creates a proposal and preserves protected human state.",
        },
    ]


def assessment_page(pdf: canvas.Canvas, page: int, scenarios: list[dict[str, str]]) -> None:
    page_base(
        pdf,
        page,
        f"Feedback survival assessment {scenarios[0]['number']}-{scenarios[-1]['number']}",
    )
    title_block(
        pdf,
        f"Incident survival assessment {scenarios[0]['number']}-{scenarios[-1]['number']}",
        "Status is bounded to tested synthetic behavior. Each card names the code evidence, first user-visible failure, implemented control, and what still needs external authority.",
        kicker="No green-tick theatre",
    )
    positions = [
        (36, 524),
        (314, 524),
        (36, 379),
        (314, 379),
        (36, 234),
        (314, 234),
        (36, 89),
        (314, 89),
    ]
    for scenario, (x, y) in zip(scenarios, positions, strict=True):
        scenario_card(pdf, x=x, y=y, **scenario)


def mini_capability(
    pdf: canvas.Canvas,
    x: float,
    y: float,
    title: str,
    state: str,
    text: str,
    *,
    width: float = 258,
    height: float = 39,
) -> None:
    round_box(pdf, x, y, width, height, fill=PAPER, radius=5)
    pdf.setFillColor(TEAL)
    pdf.setFont("Helvetica-Bold", 6.0)
    pdf.drawString(x + 8, y + height - 12, title.upper())
    fill, foreground = status_style(state)
    pill_width = stringWidth(state, "Helvetica-Bold", 4.8) + 9
    pdf.setFillColor(fill)
    pdf.roundRect(
        x + width - pill_width - 7,
        y + height - 17,
        pill_width,
        11,
        4,
        fill=1,
        stroke=0,
    )
    pdf.setFillColor(foreground)
    pdf.setFont("Helvetica-Bold", 4.8)
    pdf.drawCentredString(x + width - pill_width / 2 - 7, y + height - 13.2, state)
    text_block(
        pdf,
        text,
        x + 8,
        y + height - 23,
        width - 16,
        size=5.45,
        color=MUTED,
        max_lines=2,
    )


def metric_tile(pdf: canvas.Canvas, x: float, value: str, label: str) -> None:
    round_box(pdf, x, 130, 101, 44, fill=TEAL_DARK, stroke=TEAL_DARK, radius=6)
    pdf.setFillColor(white)
    pdf.setFont("Times-Bold", 12)
    pdf.drawString(x + 9, 152, value)
    pdf.setFillColor(HexColor("#B7D2CC"))
    pdf.setFont("Helvetica-Bold", 5.0)
    pdf.drawString(x + 9, 138, label.upper())


def page_three(pdf: canvas.Canvas) -> None:
    metrics = measured_metrics()
    page_base(pdf, 3, "Capability 17, evaluation, boundaries and references")
    title_block(
        pdf,
        "Capability group 17: broad contracts, narrow claims",
        "The build integrates the requested stack end to end, but deliberately marks real audio, clinical validation, provider transport, legal interpretation, and deployment controls as external evidence gates.",
        kicker="Research and innovation boundary",
    )

    round_box(pdf, 36, 608, 540, 57, fill=TEAL_DARK, stroke=TEAL_DARK, radius=8)
    pdf.setFillColor(white)
    pdf.setFont("Times-Bold", 11)
    pdf.drawString(49, 645, "Selected system design: evidence before automation")
    stages = ["Identity", "Stream", "Privacy", "Evidence", "Human gate", "Delivery"]
    stage_width = 75
    start = 49
    pdf.setStrokeColor(HexColor("#699791"))
    pdf.setLineWidth(1.2)
    pdf.line(start + 9, 623, start + 5 * 88 + 9, 623)
    for index, stage in enumerate(stages):
        cx = start + index * 88
        pdf.setFillColor(HexColor("#DCECE7"))
        pdf.circle(cx + 9, 623, 9, fill=1, stroke=0)
        pdf.setFillColor(TEAL_DARK)
        pdf.setFont("Helvetica-Bold", 5.7)
        pdf.drawCentredString(cx + 9, 621, str(index + 1))
        pdf.setFillColor(HexColor("#D4E7E1"))
        pdf.setFont("Helvetica-Bold", 5.8)
        pdf.drawCentredString(cx + stage_width / 2, 611, stage)

    capabilities = [
        (
            "Streaming + noisy ASR",
            "PARTIAL",
            "Ordered resumable segment contract and quality abstention; no live ASR/WER corpus.",
        ),
        (
            "Speaker attribution",
            "PARTIAL",
            "Provider label is evidence, never biometric identity or clinical authority; human correction retained.",
        ),
        (
            "Code switching",
            "PARTIAL",
            "Within-statement language spans; unsupported Hokkien abstains instead of becoming generic Chinese.",
        ),
        (
            "Multilingual downstream",
            "PARTIAL",
            "Original spans remain primary; safety extraction handles bounded English terms only.",
        ),
        (
            "Terminology + dosage",
            "PARTIAL",
            "Exact local evidence and fail-closed units; RxNorm/formulary validation is not claimed.",
        ),
        (
            "Immutable provenance",
            "SURVIVES",
            "Version, offsets, quote, URI, hash, stale propagation and original/current comparison.",
        ),
        (
            "Negation + conflict",
            "PARTIAL",
            "Bounded deterministic candidates and two-source review; unknown semantics stay unresolved.",
        ),
        (
            "Collaborative editing",
            "SURVIVES",
            "Optimistic concurrency plus reviewed three-way draft; no CRDT claim.",
        ),
        (
            "AI regeneration",
            "SURVIVES",
            "New proposal only; human confirmations, tasks, conflict decisions and deliveries preserved.",
        ),
        (
            "Audience outputs",
            "SURVIVES",
            "Server allow-list projections; AI drafts internal; patient release requires clinician confirmation.",
        ),
        (
            "Bounded self-learning",
            "PARTIAL",
            "Clinic/role shadow posteriors, hard floors and promotion refusal under exposure bias.",
        ),
        (
            "Patient delivery",
            "SURVIVES",
            "Immutable approved copy, receipt state, patient acknowledgement, correction and escalation.",
        ),
    ]
    for index, (title, state, text) in enumerate(capabilities):
        column = index % 2
        row = index // 2
        mini_capability(pdf, 36 + column * 278, 558 - row * 45, title, state, text)

    headings = ["WHAT I TRIED", "WHERE I STOPPED", "ASSUMPTIONS THAT REMAIN"]
    copy = [
        "Tested deadline, 503, low-quality stream, unsupported language, stale citation, concurrent edit, contradiction, wrong dose, failed delivery and late acknowledgement paths - including desktop and mobile browsers.",
        "No licensed SEA clinical audio, native-speaker labels, approved drug reference, real messaging provider, production OIDC/RLS runtime, legal ruling, clinical reviewer, or prospective pilot evidence was available. The UI names these absences.",
        "All identities and care facts are synthetic. Provider and delivery callbacks are deterministic rehearsals. Hashes prove application consistency, not external notarization. A passing test is not clinical safety or compliance certification.",
    ]
    fills = [TEAL_PALE, AMBER_PALE, BLUE_PALE]
    for index, (heading, body, fill) in enumerate(zip(headings, copy, fills, strict=True)):
        x = 36 + index * 184
        round_box(pdf, x, 192, 172, 91, fill=fill, radius=7)
        pdf.setFillColor(TEAL_DARK)
        pdf.setFont("Helvetica-Bold", 5.8)
        pdf.drawString(x + 10, 267, heading)
        text_block(pdf, body, x + 10, 254, 152, size=5.55, color=INK, max_lines=10)

    metric_tile(pdf, 36, metrics["coverage"], "Backend / frontend coverage")
    metric_tile(pdf, 146, metrics["browser"], "Desktop + mobile browser")
    metric_tile(pdf, 256, metrics["mutants"], "Killed / checked mutants")
    metric_tile(pdf, 366, metrics["warm_p95"], "Local warm-path P95")
    metric_tile(pdf, 476, metrics["advisories"], "Known advisories at scan")

    pdf.setFillColor(TEAL)
    pdf.setFont("Helvetica-Bold", 5.8)
    pdf.drawString(36, 111, "SELECTED PRIMARY REFERENCES - HYPERLINKED")
    references = [
        (
            "[1] NIST SP 800-63B identity",
            "https://pages.nist.gov/800-63-4/sp800-63b.html",
        ),
        (
            "[2] PostgreSQL row security",
            "https://www.postgresql.org/docs/current/ddl-rowsecurity.html",
        ),
        (
            "[3] OWASP logging guidance",
            "https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html",
        ),
        (
            "[4] OpenTelemetry sensitive data",
            "https://opentelemetry.io/docs/security/handling-sensitive-data/",
        ),
        ("[5] HL7 FHIR Provenance", "https://hl7.org/fhir/R5/provenance.html"),
        (
            "[6] HL7 FHIR Communication",
            "https://hl7.org/fhir/R5/communication.html",
        ),
        ("[7] HL7 FHIR Appointment", "https://hl7.org/fhir/R5/appointment.html"),
        (
            "[8] NLM RxNorm APIs",
            "https://lhncbc.nlm.nih.gov/RxNav/APIs/RxNormAPIs.html",
        ),
        (
            "[9] FDA CDS guidance, Jan 2026",
            "https://www.fda.gov/regulatory-information/search-fda-guidance-documents/clinical-decision-support-software",
        ),
        (
            "[10] Singapore PDPC healthcare",
            "https://www.pdpc.gov.sg/guidelines-and-consultation/2017/10/advisory-guidelines-for-the-healthcare-sector",
        ),
        (
            "[11] AWS transactional outbox",
            "https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html",
        ),
        ("[12] W3C WCAG 2.2", "https://www.w3.org/TR/WCAG22/"),
    ]
    for index, (label, url) in enumerate(references):
        column = index % 3
        row = index // 3
        x = 36 + column * 184
        y = 96 - row * 15
        pdf.setFillColor(INK)
        pdf.setFont("Helvetica", 5.45)
        pdf.drawString(x, y, label)
        pdf.linkURL(url, (x, y - 2, x + 172, y + 7), relative=0)


def build_pdf(path: Path = OUTPUT) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path), pagesize=letter, pageCompression=1, invariant=1)
    pdf.setTitle("Nightingale Continuum - Feedback 1-17 Technical Brief")
    pdf.setAuthor("XIE WEIKUN")
    pdf.setCreator("Nightingale Continuum reproducible brief builder")
    pdf.setSubject("Incident survival, capability boundaries, evaluation and deployment gates")
    scenarios = scenario_data()
    assessment_page(pdf, 1, scenarios[:8])
    pdf.showPage()
    assessment_page(pdf, 2, scenarios[8:])
    pdf.showPage()
    page_three(pdf)
    pdf.showPage()
    pdf.save()

    reader = PdfReader(str(path))
    if len(reader.pages) != 3:
        raise RuntimeError(f"Expected exactly 3 pages, found {len(reader.pages)}")
    extracted_pages = [page.extract_text() or "" for page in reader.pages]
    extracted = "\n".join(extracted_pages)
    required = [
        "Incident survival assessment 01-08",
        "Incident survival assessment 09-16",
        "Capability group 17",
        "FIRST BREAK",
        "BUILT + RESIDUAL BOUNDARY",
        "SURVIVES - LOCAL",
        "PARTIAL",
        "WHERE I STOPPED",
        "ASSUMPTIONS THAT REMAIN",
        "FDA CDS guidance, Jan 2026",
        measured_metrics()["coverage"],
        measured_metrics()["mutants"],
        "Synthetic data only",
    ]
    missing = [item for item in required if item not in extracted]
    if missing:
        raise RuntimeError(f"PDF text verification failed: {missing}")
    for index, page_text in enumerate(extracted_pages, start=1):
        if len(page_text) < 1_000:
            raise RuntimeError(f"Page {index} extracted too little text")
    return path


if __name__ == "__main__":
    print(build_pdf())
