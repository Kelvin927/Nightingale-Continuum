# Nightingale Continuum

**A longitudinal care note that compresses attention without compressing evidence.**

Nightingale Continuum is a prototype for a shared clinical narrative across clinician, staff, patient-contributed, and AI-scribed interactions. Its primary surface is a bounded consult glance that answers four questions in under 10 seconds: what matters, why it matters, who owns the next step, and exactly where the evidence came from.

> Synthetic data only. This is a product and safety prototype, not a clinical system, medical device, or compliance claim.

## Candidate

- **Name:** XIE WEIKUN
- **School:** SPMS
- **Programme:** MSc in Analytics
- **Repository:** <https://github.com/Kelvin927/Nightingale-Continuum>

## What is distinctive

- **Evidence-bound glance:** every highlight resolves to an immutable source version, exact character span, quote, source URI, and content hash.
- **Citation-first evidence review:** a role-scoped local reviewer organizes only authorized claims, quotes, actions, and conflicts; it abstains when the record cannot support a sourced answer.
- **Extraction before generation:** safety highlights extract verbatim spans from immutable versions. Generated scribe text is a visibly unconfirmed internal draft and is never treated as source-preserving paraphrase.
- **Revision-aware collaboration:** the interface polls a lightweight projection revision and reloads the workspace only when server evidence changes.
- **Visible trust ladder:** AI-proposed, human-authored, staff-verified, clinician-confirmed, and superseded states are expressed with text and iconography, not color alone.
- **Role-owned collaboration:** staff and clinicians share context but cannot overwrite each other's sections. Revert creates a new version; history is never erased.
- **Safe adaptive importance:** bounded Beta-posterior feedback can reorder ordinary suggestions, while critical risk, allergy, medication-safety, and urgent-task rules remain dominant.
- **Causal humility:** the Delta Lens distinguishes new, persistent, changed/conflicting, resolved, and unknown evidence without turning temporal order into a causal claim.
- **Honest shadow evaluation:** the deterministic display policy logs propensity 1.0. Surfaced-only feedback therefore raises an exposure-bias warning and cannot support policy promotion; the estimator remains exploratory.
- **Provenance-preserving decay:** hot/warm/cold tiers can remove derived caches, never the immutable source, audit metadata, or protected active safety evidence.

## Local start

Requirements: Python 3.12+, Node 24+, and npm 11+. Python build tooling and the complete third-party environment are exactly constrained in `backend/pyproject.toml` and the marker-aware `requirements-lock.txt`; npm uses `package-lock.json`. The lock resolves to 74 packages on the release macOS arm64 environment and 75 on Linux x86_64, where SQLAlchemy declares `greenlet` as a platform-specific runtime dependency.

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

The same release gates run in GitHub Actions from a fresh Ubuntu checkout; local commands remain the authoritative reproduction path.

```bash
make verify
```

This runs:

- exact installed-Python-graph verification against the marker-aware constraints lock;
- Ruff check and format verification with warnings promoted to errors in Python tests;
- 168 Python tests, including every brief-required filename and deterministic property tests;
- exact 100 percent backend statement and branch coverage gates;
- 46 Vitest tests with exact 100 percent statement, branch, function, and line coverage gates;
- automated axe accessibility checks for the role views and modal/drawer states;
- Python and npm advisory audits plus CycloneDX software bills of materials;
- cold-construction and warm-path performance evidence with zero tolerated failures;
- cache-safe mutation testing across eight critical domain modules; the runner serializes concurrent invocations, excludes generated Python bytecode, and rebuilds the gitignored mutant workspace before every run;
- TypeScript production build, release-package audit, and Git whitespace checks.

With the API running, measure the warm read path:

```bash
make benchmark
```

The final local release benchmark used 50 warm-ups plus 600 measured loopback requests: 600 succeeded, median 1.157 ms, P95 1.406 ms, and P99 1.896 ms. A separate 40-sample cold-construction benchmark completed 40/40 samples with median 31.489 ms and P95 33.467 ms. These are explicit local approximations, not production-network or orchestration claims. `make verify` regenerates the machine-readable results under the ignored `output/evidence/` directory; GitHub Actions retains the same evidence as a workflow artifact.

Browser tests are defined for desktop Chromium and Pixel 7-sized mobile Chromium:

```bash
cd frontend
npx playwright install chromium
cd ..
make test-browser
```

The committed browser run passes all 7 applicable workflows with zero failures, retries classified as flaky, or skipped cases. Each run uses unique checkout-owned API/web ports and a temporary SQLite database, so an already-running demo cannot be mistaken for the tested build and parallel requests cannot touch demo state or share a single in-memory connection.

## Where security is enforced

The request path is `route -> authenticated actor -> object policy -> domain transaction -> actor-safe projection`.

- Every patient, entry, comment thread, highlight, provenance span, version, and audit request is resolved inside the actor's clinic scope.
- Out-of-scope identifiers return the same not-found response as nonexistent identifiers.
- Patient responses are built from an allow-list projection. Raw AI entries, internal notes, comments, conflicts, versions, and audit data never enter the patient response.
- Staff-authored content cannot be released directly to the patient. Patient summaries and instructions require clinician ownership plus the `clinician_confirmed` trust state; patient-authored insights remain a separate allow-listed class.
- Mutations validate role ownership. Staff cannot edit clinician sections; clinicians cannot edit staff sections.
- Every accepted mutation appends an immutable version and metadata-only audit event within the transaction.
- Same-section stale writes return a structured `409` conflict. Independent role-owned sections can update concurrently.

The local SQLite policy layer makes the candidate demo runnable without Docker. A production deployment would add PostgreSQL row-level security under a non-owner application role, authenticated OIDC sessions with MFA, managed encryption keys, centralized audit retention, rate limits, monitoring, backups, and an independently reviewed authorization policy. Those controls are deployment requirements, not claims about this prototype.

## Where redaction happens

AI-scribe input follows this enforced sequence:

```text
raw synthetic transcript
  -> known-person + title/name recognizers
  -> Singapore NRIC/FIN-like recognizer
  -> phone + email recognizers
  -> redaction receipt (types/counts, sanitized hash, clinical-anchor fidelity)
  -> provider boundary
  -> schema-constrained AI-proposed entry
  -> exact-source highlights
  -> human review
```

The receipt requires both removal of every detected identifier and exact preservation of the multiset of recognized medication, allergy, and dose anchors. If clinical anchors change, capture fails closed with a `422` receipt before the provider is called. The default `LocalDeterministicScribe` uses no network and no external model. Tests spy on the provider boundary and assert that known names, NRIC/FIN-like IDs, phone numbers, and email addresses do not cross it. Automated redaction can still miss identifiers or clinical concepts outside the bounded recognizers, so real deployment requires a representative annotated corpus, dual privacy/clinical-fidelity error reporting, private infrastructure, monitoring, and approved vendors.

## What each number means

No displayed number is accepted as self-validating. The prototype defines each quantity, the evidence needed to challenge it, and a fail-safe response.

| Signal | Operational definition | How an error is detected | What happens when it is wrong or unsupported |
| --- | --- | --- | --- |
| Risk level | A deterministic rule classifies extracted sentences. Allergy or severe-reaction language is `critical`; medication or dose language is at least `high`; unresolved follow-up is at least `medium`. A model cannot lower this floor. | Exact rule tests, property tests, mutation tests, and clinician review compare labels with source spans. Production evaluation must report class-wise sensitivity, especially for allergy, medication, dose, and critical-result strata. | Critical and medication/allergy items retain a non-learnable ordering floor. Unrecognized or ambiguous clinical semantics remain for human review; the prototype makes no claim of complete clinical NLP coverage. |
| Evidence support | A policy score derived only from trust state: superseded `0`, AI-proposed `0.65`, human-authored `0.75`, staff-verified `0.85`, clinician-confirmed `0.95`. Bands are low `<0.60`, medium `0.60–<0.85`, and high `≥0.85`. | The trust-state mapping, band boundaries, provenance integrity, current-version filtering, and patient projection are exact test contracts. | The score is explicitly **not** a calibrated probability of correctness. AI-proposed claims remain reviewable drafts; unsupported review questions abstain; only clinician-confirmed patient content can cross the patient boundary. |
| Importance score | Fixed risk, safety entity, recency, action, and pin terms plus a role/clinic posterior adjustment clipped to `[-0.75, +0.75]`. Ordering first applies the hard safety band. | Tests decompose every score factor, perturb feedback, preserve critical ordering, exclude stale versions, and kill mutations in the ranking logic. | Feedback may reorder ordinary items only. It cannot demote critical, allergy, medication, or urgent-task classes below their deterministic floor. |
| Redaction pass | All detected identifier substrings are absent after replacement **and** the recognized clinical-anchor multiset is unchanged. | The receipt exposes detector version, entity counts, sanitized hash, anchor count, and fidelity result. Negative tests deliberately make a name overlap a medication anchor. | The provider is not called; the transaction rolls back and returns `redaction_fidelity_failed`. No draft or highlight is created. |
| Feedback evidence | The current UI is deterministic, so every surfaced impression has server-owned propensity `1.0`; client-supplied propensities are ignored. | Evaluation checks exposure support, effective sample size, extreme weights, uncertainty, assumptions, and policy version. | Deterministic, surfaced-only feedback is labelled exposure-biased and exploratory. It cannot justify automatic policy promotion; randomized or otherwise supported logging is required first. |
| Conflict signal | A bounded deterministic detector compares current versions for supported medication-dose disagreements and positive allergy statements versus no-known-allergy statements. | Paired contradiction fixtures, duplicate suppression, clinic/patient scoping, and current-version tests. | A conflict is opened for care-team reconciliation. The system never chooses a winning note or silently edits either source; unsupported drugs, negation, temporality, and resolution remain explicit human boundaries. |
| Patient-facing content | Patient insight is patient-authored. Patient summaries and instructions must be clinician-owned and clinician-confirmed. AI scribe drafts stay internal. | API denial tests, direct-object concealment tests, role-view accessibility tests, and patient allow-list projection tests. | Unconfirmed or wrong-type releases return `403`/`404` and do not enter the patient workspace. There is no autonomous patient-facing generation path in this prototype. |

This design follows the principle of selective prediction: a system earns the right to answer only where evidence and workflow support exist. A future probabilistic model would require held-out calibration, subgroup reliability analysis, selective-risk/coverage curves, and prospective error review before any probability label could be shown.

## Original contribution and novelty boundary

The candidate contribution is the system-level synthesis: an attention-budget UI bound to immutable evidence; explicit extraction-versus-generation separation; deterministic clinical-risk floors above bounded learning; an exposure-aware evaluation state that refuses promotion from deterministic surfaced-only feedback; a dual privacy/clinical-fidelity redaction receipt; revision-aware contradiction surfacing; and a stricter clinician-confirmed patient-release boundary. These elements were designed and implemented for this challenge and reflect an MSc Analytics perspective on estimands, uncertainty, selective prediction, causal identification, and auditability.

The repository does **not** claim that provenance models, Beta-Bernoulli shrinkage, doubly robust estimation, selective prediction, redaction, optimistic concurrency, or human review are individually novel research methods. The potential innovation is their product-specific combination and the visibility of failure semantics. Establishing scientific novelty would require a documented systematic literature and patent search plus comparative empirical evaluation; that study has not been performed here.

## Repository map

```text
backend/app/            FastAPI policy, domain, provenance, learning, retention
backend/tests/          Required micro-tests plus adversarial safety tests
frontend/src/           Responsive React care workspace and role projections
frontend/e2e/           Desktop/mobile browser workflow specification
output/pdf/             Submission-ready technical brief
scripts/                Reproducible verification, benchmarks, brief builder
```

## Important limitations

- All records and identifiers are fictional. Do not load real PHI.
- The prototype is not HIPAA, PDPA, GDPR, SOC 2, medical-device, or production-safety certified.
- Local deterministic drafting proves the privacy and provenance workflow, not transcription or clinical-note quality.
- Automatic conflict detection is deliberately bounded to a small medication/allergy vocabulary. It surfaces candidate contradictions and never claims a resolved clinical truth.
- The browser capture shell records locally but uses an editable synthetic transcript for the deterministic demo pipeline; real ASR, diarization, multilingual terminology, noisy-room evaluation, and consent flows remain production work.
- Offline ranking estimates describe a synthetic interaction proxy. They do not establish clinical benefit or patient safety.
- Hash chaining is tamper-evident inside the application threat model, not externally notarized.

## Submission files

The repository intentionally contains only the requested submission materials and the files needed to run and verify them:

- the working application and automated tests under `backend/` and `frontend/`;
- this `README.md` with setup, run, RBAC, redaction, testing, and limitations;
- [`ATTRIBUTION.txt`](ATTRIBUTION.txt) with external libraries, models, assets, and licenses; and
- [`output/pdf/nightingale_continuum_technical_brief.pdf`](output/pdf/nightingale_continuum_technical_brief.pdf), the required three-page technical brief.

The demo video is submitted separately. Generated coverage, security, mutation, browser, and benchmark evidence is intentionally excluded from Git and produced by `make verify`, `make test-browser`, or GitHub Actions.
