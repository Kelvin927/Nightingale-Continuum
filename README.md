# Nightingale Continuum

**A longitudinal care note that compresses attention without compressing evidence.**

Nightingale Continuum is a candidate-build prototype for a shared clinical narrative across clinician, staff, patient-contributed, and AI-scribed interactions. Its primary surface is a bounded consult glance that answers four questions in under 10 seconds: what matters, why it matters, who owns the next step, and exactly where the evidence came from.

> Synthetic data only. This is a product and safety prototype, not a clinical system, medical device, or compliance claim.

## What is distinctive

- **Evidence-bound glance:** every highlight resolves to an immutable source version, exact character span, quote, source URI, and content hash.
- **Visible trust ladder:** AI-proposed, human-authored, staff-verified, clinician-confirmed, and superseded states are expressed with text and iconography, not color alone.
- **Role-owned collaboration:** staff and clinicians share context but cannot overwrite each other's sections. Revert creates a new version; history is never erased.
- **Safe adaptive importance:** bounded Beta-posterior feedback can reorder ordinary suggestions, while critical risk, allergy, medication-safety, and urgent-task rules remain dominant.
- **Causal humility:** the Delta Lens distinguishes new, persistent, changed/conflicting, resolved, and unknown evidence without turning temporal order into a causal claim.
- **Shadow policy evaluation:** impression propensities and outcomes support an exploratory doubly robust estimate with assumptions, uncertainty, and effective sample size shown explicitly.
- **Provenance-preserving decay:** hot/warm/cold tiers can remove derived caches, never the immutable source, audit metadata, or protected active safety evidence.

## Five-minute local start

Requirements: Python 3.12+, Node 24+, and npm 11+. Python build tooling and the complete 74-package third-party environment are exactly constrained in `backend/pyproject.toml` and `requirements-lock.txt`; npm uses `package-lock.json`.

```bash
make setup
```

Start the API in terminal 1:

```bash
make api
```

Start the web client in terminal 2:

```bash
make web
```

Open `http://127.0.0.1:5173`. The repository seeds one synthetic care journey and four switchable demo identities:

| Role | Demo identity | Primary behavior |
| --- | --- | --- |
| Clinician | Dr Lina Patel | Clinical sections, all AI drafts, review feedback, exact sources |
| Staff | Jon Bell | Staff workflow notes, assignments, comments, follow-up coordination |
| Patient | Maya Chen | Patient-facing summaries/instructions and patient insight capture only |
| Admin | Rose Tan | Clinic-scoped audit verification, policy evidence, retention operations |

The `X-Demo-User` header is isolated demo authentication. Role and clinic are loaded on the server; the API never accepts them from the request payload. Production must replace this header with authenticated OIDC sessions and MFA.

## Verify the build

```bash
make verify
```

This runs:

- exact installed-Python-graph verification against the 74-package constraints lock;
- Ruff check and format verification with warnings promoted to errors in Python tests;
- 124 Python tests, including every brief-required filename and deterministic property tests;
- exact 100 percent backend statement and branch coverage gates;
- 40 Vitest tests with exact 100 percent statement, branch, function, and line coverage gates;
- automated axe accessibility checks for the role views and modal/drawer states;
- Python and npm advisory audits plus CycloneDX software bills of materials;
- cold-construction and warm-path performance evidence with zero tolerated failures;
- mutation testing across six critical domain modules; the clean-room run killed all 1,581 generated mutants;
- TypeScript production build, release-package audit, and Git whitespace checks.

With the API running, measure the warm read path:

```bash
make benchmark
```

The committed clean-room benchmark used 50 warm-ups plus 600 measured loopback requests: 600 succeeded, median 1.102 ms, P95 1.179 ms, and P99 1.457 ms. A separate 40-sample cold-construction benchmark completed 40/40 samples with median 28.724 ms and P95 30.656 ms. These are explicit local approximations, not production-network or orchestration claims. See [`output/evidence/glance_benchmark.json`](output/evidence/glance_benchmark.json) and [`output/evidence/cold_start_benchmark.json`](output/evidence/cold_start_benchmark.json).

Browser tests are defined for desktop Chromium and Pixel 7-sized mobile Chromium:

```bash
cd frontend
npx playwright install chromium
cd ..
make test-browser
```

The committed browser run passes all 5 applicable workflows with zero failures, retries classified as flaky, or skipped cases. Each run uses a unique temporary SQLite database so parallel browser requests cannot touch demo state or share a single in-memory connection.

## Where security is enforced

The request path is `route -> authenticated actor -> object policy -> domain transaction -> actor-safe projection`.

- Every patient, entry, comment thread, highlight, provenance span, version, and audit request is resolved inside the actor's clinic scope.
- Out-of-scope identifiers return the same not-found response as nonexistent identifiers.
- Patient responses are built from an allow-list projection. Raw AI entries, internal notes, comments, conflicts, versions, and audit data never enter the patient response.
- Mutations validate role ownership. Staff cannot edit clinician sections; clinicians cannot edit staff sections.
- Every accepted mutation appends an immutable version and metadata-only audit event within the transaction.
- Same-section stale writes return a structured `409` conflict. Independent role-owned sections can update concurrently.

The local SQLite policy layer makes the candidate demo runnable without Docker. The production design adds PostgreSQL row-level security under a non-owner application role as a second enforcement layer. See [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) for residual risks and required deployment controls.

## Where redaction happens

AI-scribe input follows this enforced sequence:

```text
raw synthetic transcript
  -> known-person + title/name recognizers
  -> Singapore NRIC/FIN-like recognizer
  -> phone + email recognizers
  -> redaction receipt (types/counts and sanitized-text hash only)
  -> provider boundary
  -> schema-constrained AI-proposed entry
  -> exact-source highlights
  -> human review
```

The default `LocalDeterministicScribe` uses no network and no external model. Tests spy on the provider boundary and assert that known names, NRIC/FIN-like IDs, phone numbers, and email addresses do not cross it. Automated redaction can still miss identifiers, so real deployment requires validated clinical de-identification, private infrastructure, monitoring, and approved vendors.

## Repository map

```text
backend/app/            FastAPI policy, domain, provenance, learning, retention
backend/tests/          Required micro-tests plus adversarial safety tests
frontend/src/           Responsive React care workspace and role projections
frontend/e2e/           Desktop/mobile browser workflow specification
docs/                   Architecture, threat model, quality gates, evidence ledger
output/evidence/        Machine-readable benchmark and verification evidence
output/pdf/             Submission-ready technical brief
scripts/                Reproducible verification, benchmarks, brief builder
PROJECT_STATE.md        Recovery checkpoint and verification status
```

## Important limitations

- All records and identifiers are fictional. Do not load real PHI.
- The prototype is not HIPAA, PDPA, GDPR, SOC 2, medical-device, or production-safety certified.
- Local deterministic drafting proves the privacy and provenance workflow, not transcription or clinical-note quality.
- The browser capture shell records locally but uses an editable synthetic transcript for the deterministic demo pipeline; real ASR, diarization, multilingual terminology, noisy-room evaluation, and consent flows remain production work.
- Offline ranking estimates describe a synthetic interaction proxy. They do not establish clinical benefit or patient safety.
- Hash chaining is tamper-evident inside the application threat model, not externally notarized.

## Submission artifacts

- [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md) - 48-hour execution plan and definition of done
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) - architecture, schema, ranking, and retention decisions
- [`docs/INNOVATION_LEDGER.md`](docs/INNOVATION_LEDGER.md) - standards, research-derived methods, prototype contributions, and non-claims
- [`docs/DEMO_RUNBOOK.md`](docs/DEMO_RUNBOOK.md) - deterministic video script and final human checks
- [`docs/ASSURANCE_REPORT.md`](docs/ASSURANCE_REPORT.md) - machine-verifiable quality evidence and honest residual boundaries
- [`docs/MUTATION_REVIEW.md`](docs/MUTATION_REVIEW.md) - unadjusted mutation result and survivor-elimination rationale
- [`docs/references/EVIDENCE_REGISTRY.md`](docs/references/EVIDENCE_REGISTRY.md) - primary research and official standards
- [`ATTRIBUTION.txt`](ATTRIBUTION.txt) - libraries, models, assets, and licenses
- [`output/pdf/nightingale_continuum_technical_brief.pdf`](output/pdf/nightingale_continuum_technical_brief.pdf) - concise 3-page technical brief
