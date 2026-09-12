# Question Generation MVP

## Scope

An independent, authenticated `POST /api/questions/generate` endpoint produces
Chinese single-choice practice material from the existing course knowledge
base. It does not enter the chat agent, alter QueryPipeline, record learning
events, grade attempts, or persist a question bank. There is no new frontend,
teacher-role system, generic-agent tool, skill, or multi-agent workflow in this
slice. Evidence verifier and Item quality critic are two serial internal
`assessment/` domain components, not agent roles and not inputs to agent
orchestration.

The small structured-generation workflow is adapted from AI Mini-Quiz
Generator. See [attribution and license](third_party/ai-mini-quiz-generator.md).
No new Gemini, Streamlit, Torch, or model-weight dependency is introduced.

## Request

Use the existing login cookie when calling this endpoint. A request body is:

```json
{"topic": "决策树", "count": 5, "difficulty": "basic"}
```

- `topic`: nonblank text, at most 500 characters.
- `count`: integer from 1 through 10, default 5.
- `difficulty`: `basic`, `intermediate`, or `advanced`, default `basic`.
- `concept_id`: optional canonical ID from `data/knowledge_graph.json`. When
  supplied, `topic` must match that concept's display name or an exact alias;
  unknown or conflicting identities return 422. Without an ID, exact topic
  aliases resolve to the catalog; unrecognized topics use literal matching.

The response contains a title, questions, and server-selected textbook sources.
Each question has four distinct options identified by A/B/C/D, one correct
option ID, an explanation, difficulty, and source IDs. Answers are intentionally
included for self-study generation; this endpoint is not a secure exam-taking
interface.

## Processing

```text
authenticated API -> assessment service -> canonical concept and alias query
                                       -> expanded textbook candidates
                                       -> target-bearing, deduplicated evidence
                                       -> structured candidate batch
                                       -> per-question contract validation
                                       -> Evidence verifier: evidence, unique answer, source/excerpt, topic
                                       -> Item quality critic: ambiguity, leakage, distractors, pedagogy, difficulty, duplication
                                       -> accept or reject each candidate
                                       -> one bounded repair call for missing slots
```

No usable evidence means no generation-model call. Validation checks the
requested question count, option IDs/text, answer membership, difficulty,
duplicate stems, and references to the supplied sources. Structurally accepted
candidates first go to `assessment/verifier.py`, the Evidence verifier. It does
not receive the author's marked answer or explanation. It independently lists
every option it considers textbook-supported; every listed option must carry a
server-assigned excerpt ID. The service derives its source ID from the immutable
catalog instead of asking the model to copy that relationship. The service creates one immutable
catalog from the non-empty evidence lines, reuses it across the bounded repair
round, and validates every selected excerpt after any verifier implementation returns.
Unknown IDs, duplicate support entries, malformed output, and incomplete
coverage fail closed. A supported answer must resolve to a source declared by
the candidate; the model cannot override an excerpt's source ownership. A candidate
passes this first gate only when it is on topic and its marked answer is the
sole supported option. This module owns no pedagogical-quality judgment.

Only evidence-accepted candidates then go to `assessment/critic.py`, the Item
quality critic. It receives de-identified candidate stems/options, requested
topic, and de-identified previously accepted stems/options. It does
not receive the answer key, explanation, source ID, excerpt ID, or any textbook
evidence. It returns one exclusive role per option, option-level parallelism,
answer-leakage signals, pedagogical defects/usefulness, observed cognitive
operation, and learning-objective distinctness. The service derives the apparent
answer set from the roles and checks cognitive operation against the requested
difficulty. The service compares the
apparent answer set with the hidden marked answer only after the critic returns.
A critic rejection enters the same one-round repair budget; a malformed,
incomplete, or unavailable response from either module fails the request rather
than entering repair. After the blind evidence verdict matches the marked answer, the final
explanation uses that verdict's explicit `answer_explanation` rather than publishing
the author's unchecked elaboration. The replacement is validated against the
normal question text contract. Returned source text is drawn from the bounded
evidence supplied to the Evidence verifier, not invented by a model.

The Evidence verifier prompt renders only catalog excerpts, not a second copy
of the full source text, and is capped at 48,000 characters before any provider
call. Each selected evidence line is at most 1,200 characters under the catalog
contract. The Item quality critic prompt is capped at 24,000 characters and
contains no source material or hidden answer data. These limits prevent either
review stage from silently expanding its bounded request.

Assessment-specific evidence selection lives in `assessment/evidence.py` and
does not change ordinary RAG behavior. It requests at least 12 candidates,
soft-prioritizes the catalog subsection/chapter, rejects contents pages, and
keeps whole target-bearing sentences. Repeated/near-duplicate sentences and
flattened execution-output tails are removed. Latin anchors have token
boundaries, while whitespace inside PDF-extracted terms is tolerated.

The current conservative support gate requires at least one distinct sentence
of 24 non-whitespace characters per requested question, within the evidence
budget. This is a documented heuristic, not a count of independent facts;
it can reject short valid evidence or evidence expressed without explicit
concept names. Sentence matching and deduplication thresholds require broader
evaluation beyond the five initial cases. Each returned question must mention
the target name or alias in its stem; absence rejects the batch with 502.

These checks do NOT prove factual correctness, pedagogical quality, calibrated
difficulty, or that a cited passage entails the answer. Evidence support and
item quality are separate structured second-model judgments, not deterministic
measures. A passing serial review means only that both modules produced
contract-valid, non-rejecting results; it is not a fact proof or a substitute
for teacher review and a Chinese textbook quality evaluation. The service keeps
accepted questions and requests only the missing count once when model output or
a candidate contract is invalid, or when a candidate receives a rejecting
verdict. A second failure rejects the quiz rather than publishing
partial/unvalidated questions or falling back to a normal chat answer.

## Actionable review and repair

The item critic assigns each option one exclusive `assessment` role: answer
or distractor. The service derives the apparent answer set from those roles;
the model cannot emit a second contradictory answer set. Distractor quality is
checked independently through option parallelism and specific pedagogical
defects, so an incorrect but comparable alternative is not rejected merely
because it performs a different operation or names a different concept. The old
`plausible_for_unmastered_student` boolean is removed. Factual incorrectness is
not itself a distractor defect. Basic items may assess learned definitions and
properties; ordinary terminology overlap is not automatically answer leakage.

The critic does not receive the requested difficulty. It reports the observed
`cognitive_operation` (recall, interpretation, application, or analysis), and
the service checks that against `DIFFICULTY_RULES` in `models.py`. The author
receives the same rule's concrete instruction. This replaces the biased
`difficulty_appropriate` boolean: a definition question cannot pass as advanced
merely because the request or generated label says advanced. The operation is
still a model judgment, not a calibrated measurement of learner difficulty.

`feedback.py` owns typed repair feedback. The author receives each rejected
candidate, all rejection codes, overall and option-level reasons, and separately
the accepted items to avoid. A rejected stem may be retained while its options
are corrected; only accepted stems and duplicates within a candidate batch are
reserved. The same single repair budget and both mandatory review gates apply.
Structured parser failures enter that repair budget; provider and transport
failures still receive no implicit retry.

Item criticism runs in ordered batches of at most two questions because each
item requires four option-level explanations. Every later batch sees only the
previously accepted items, including accepted items from earlier batches in the
same round, so learning-objective diversity still crosses batch boundaries.
Each critic call also exposes the exact candidate count and index range in its
JSON Schema; accepted history is explicitly excluded from returned verdicts.
Batching limits individual reviewer output and call latency; it does not add an
author repair round or publish a partial quiz. A reviewer failure still aborts
the request. End-to-end latency remains dependent on quiz size.

`diagnostics.py` emits a correlation ID, stage, round, item count, duration,
exception class chain, and acceptance rejection codes to the existing logger.
It never logs prompts, textbook text, question content, credentials, or raw
exception messages. This distinguishes upstream failures from review rejection
without changing the sanitized HTTP response.

## Model Configuration

Settings use the existing `.env` loader and shared model factory:

| Setting | Default | Purpose |
| --- | --- | --- |
| `ASSESSMENT_GENERATOR_MODEL_NAME` | empty | Candidate author model; blank reuses the selected chat model |
| `ASSESSMENT_VERIFIER_MODEL_NAME` | empty | Reviewer model for both serial review modules; blank reuses the selected chat model |
| `ASSESSMENT_MAX_TOKENS` | 4096 | Separate output budget |
| `ASSESSMENT_TIMEOUT_SECONDS` | 60 | Model client timeout |
| `ASSESSMENT_TEMPERATURE` | 0.2 | Generation temperature |
| `ASSESSMENT_CONTEXT_MAX_CHARS` | 6000 | Textbook evidence budget |

Local versus remote model selection and credentials follow the existing shared
configuration. The generator and reviewer have separate model-name factories
but share the assessment token, timeout, and provider settings. The reviewer
runs Evidence verification followed by ordered Item quality critic batches of
at most two items; it is not a second agent or a new provider configuration. The current local repair
configuration is `generator=Pro/deepseek-ai/DeepSeek-V3` and
`reviewer=deepseek-ai/DeepSeek-V4-Pro` at temperature 0. The V4 Pro review
profile matched all seven fixed positive/negative regression cases; this is a
small authored regression set, not a human-labeled quality benchmark. Qwen3.5-9B repeatedly reached the author
read timeout on groupby during acceptance; the DeepSeek author completed an
independent two-question run through both gates. Shared model names do not make
the two prompts statistically independent; both reviewer inputs still hide the
author answer key and explanation. The generation call does not bind agent
tools or stream partial questions. SDK/provider failures are not retried. After
a valid provider response, the service may make one separate repair call for
invalid structured output or rejected question slots. Both models must support
LangChain structured output. The client timeout is not an end-to-end deadline
for retrieval, generation, Evidence verification, and criticism; do not
advertise it as one.

The historical single-verifier calibration batches took 11.998 s and 13.766 s.
They do not measure current serial reviewer latency because the current path
adds the Item quality critic after Evidence verification. When repair is
required, the worst normal path is generation + Evidence verification + Item
quality criticism + one repair generation + both review stages; provider timing
and rejection rate can make end-to-end latency materially higher.

## Failures

- 401: authentication required.
- 422: invalid request or no usable textbook evidence.
- 502: generation failed or output violated the question contract.
- 503: retrieval dependency unavailable.
- 500: unexpected internal failure, with a sanitized response.

Tests replace model and retrieval I/O. Passing those tests demonstrates the
local contract, not live provider compatibility or generated-question quality.

## Verification

### Evidence Regression

The original ten generated questions and source evidence are preserved in
`benchmarks/data/assessment_generation_baseline.json`. The same five concepts
and expanded real retrieval candidates are frozen in
`benchmarks/data/assessment_evidence_regression.json` (seed `4027065355`).
This is a regression set, not an independent held-out evaluation dataset.

```bash
PYTHONPATH=src .venv/bin/python benchmarks/assessment_harness.py
# Explicitly enables live retrieval and model calls:
PYTHONPATH=src .venv/bin/python benchmarks/assessment_harness.py --live
```

The default run checks evidence selection without any provider call. Four
concepts have enough retained evidence for two questions; cross-validation is
expected to be refused because the captured candidates only contain one unique
brief mention after deduplication. That does not establish that the entire
textbook lacks a fuller explanation.

### Initial MVP

The evidence-selection update passed 727 tests with 14 skips and the existing
optional-reranker warning in the isolated source snapshot, plus route tests
37/37 and route harness 119/119 (Unexpected RAG 0). Frozen evidence regression
passed 5/5, including the expected insufficient-evidence rejection. The
snapshot includes concurrently developed unrelated tests; 727 is the full-suite
count, not the number of assessment tests.

Live optimization results are retained under `var/artifacts/assessment/`:

- `optimized_five_concepts.json`: intermediate version, 8 questions in 90.14 s;
  the grouping batch still included a sorting question.
- `optimized_five_concepts_final.json`: stricter output-tail selection and
  target-stem checks, 6 questions returned in 98.611 s; cross-validation was
  refused and loc/iloc had one generation-contract failure.
- `loc_iloc_diagnostic.json`: separate investigation subsequently returned two
  questions in 20.302 s. It does not retroactively change the preceding batch's
  success rate. The original failure report contained only the exception type,
  so its precise failed invariant is unknown; the harness now records the
  sanitized domain error reason for subsequent failures.
- `optimization_report.md`: full questions, explanations, timings, and caveats.

The frozen-evidence generator comparison uses DeepSeek-V3 for its historical
blind review call for both candidates. `Qwen/Qwen3.5-4B` completed only one of the four
evidence-sufficient concepts; the other three generation calls reached the
60-second provider timeout. `Qwen/Qwen3.5-9B` completed all four sufficient
concepts in one generation and one verification call per concept, taking
98.589 seconds for the five-case fixture including the expected pre-generation
cross-validation refusal. Reports are stored as
`qwen35_4b_generator_benchmark.json` and
`qwen35_9b_generator_benchmark.json`. The 9B run also exposed truncated
`groupby(` text that the original schema accepted, so stems, option text, and
explanations now reject unbalanced `()`, `[]`, `{}`, `（）`, `【】`, and `《》`
delimiters before blind verification. A same-evidence protocol probe reproduced
the truncation with `json_schema` in 3.771 seconds, while `function_calling`
returned a complete schema-valid payload in 8.988 seconds. The author therefore
uses LangChain function calling; the DeepSeek reviewer uses JSON-schema
structured output. These five cases justify selecting 9B over 4B for this MVP;
they are not a broad model-quality benchmark.

The bounded per-question repair implementation was then replayed against the
same five live concepts. It returned eight questions in 98.144 seconds: loc/iloc,
grouping, DIKW, and large language models each returned two questions, while
cross-validation was still refused before generation because its captured
evidence was insufficient. The prior full run returned six questions, so the
repair path recovered the previously lost loc/iloc batch without weakening the
evidence gate. The result is stored in `repair_five_concepts.json`.

Manual review still found pedagogical defects that structural validation cannot
detect. The two grouping questions test nearly the same `value_counts` idea, and
the large-language-model application question has multiple options that are all
listed as valid applications in the supplied evidence. This run therefore shows
better batch completion, not production-ready question quality. It motivated the
current split between the Evidence verifier's source-grounded unique-answer gate
and the Item quality critic's answer-blind pedagogical gate.

### Historical Combined-Verifier Calibration

`var/artifacts/assessment/quality_verifier_calibration.json` records the first
verifier contract. It received the marked answer and explanation and passed all
four reviewed candidates, including the known ambiguous large-language-model
application question. That artifact is historical evidence of confirmation bias,
not evidence that the old contract was adequate.

The pre-split blind evidence contract is calibrated in
`var/artifacts/assessment/blind_quality_verifier_calibration.json`. It hides the
marked answer and explanation, requires a source ID and exact evidence quote for
every independently supported option, and lets the service compare the returned
support set with the author answer. That calibration describes the earlier
free-text quote contract, not the current two-module serial review. In the
recorded run:

- Both `groupby_aggregation` questions passed in 11.998 s. They still cover
  closely related frequency-counting ideas, so this is explicit evidence that
  semantic repetition has not been solved.
- The first `large_language_model` question passed. For the application question,
  the verifier found textbook support for A, B, C, and D while the author marked
  D; it therefore failed in 13.766 s under `multiple_correct_answers`.
- The two-case calibration took 25.764 s total. It demonstrates that the blind
  per-option citation contract can catch this known ambiguity, not stable
  accuracy across topics, models, difficulty levels, or textbook revisions.

The pre-split combined contract later added a typed
`distinct_learning_objective` verdict and rejected `false` as
`semantic_duplicate`. That was a single-model proxy and is not an Evidence
verifier responsibility in the current design. Learning-objective duplication
now belongs to the Item quality critic, which receives the previously accepted
de-identified items. The historical artifact does not calibrate that new gate.
The verdict remains model-assisted rather than a deterministic semantic proof;
do not replace this gap with a broad string-similarity threshold without a
separate evaluation set and a defensible diversity contract.

A first live grouping run with that pre-split field reached verification after
18.314 s of generation, but the verifier returned a quote that was not present
verbatim in the named evidence and the request failed closed after another
10.105 s. A repeat attempt timed out in the generation provider call after
60.344 s and never reached verification. These runs confirm the failure gates,
not live stability. The quote-copying failure motivated the current server-owned
excerpt catalog: the free-text `quote` field was deleted rather than retained as
a compatibility path.

The first live `groupby_aggregation` run with the excerpt catalog completed in
41.337 s: generation took 25.036 s and the historical verification call took
13.140 s, with no repair round. The verifier selected `E1`/`E2` for the count
question and `E3` for the max question; both `(source_id, excerpt_id)` pairs
passed service-owned validation. The two accepted questions exercised count and
max rather than the previous near-duplicate frequency-counting pair. This
single run shows that the free-text quote-copying failure was removed for this
case, not that current two-stage reviewer latency, pedagogical judgments, or
general question quality are stable.

After the pre-split verifier contract and tests were applied, the isolated
assessment worktree passed 683 tests with 14 skips and two existing warnings.
The route-focused tests passed 37/37, the route harness passed 119/119 with
Unexpected RAG 0, and the full Ruff check/format gates passed. No frontend was
changed.

The final grouping questions cover groupby/count and groupby/max rather than
apply or sort_values. These small, reused cases are not evidence of general
semantic accuracy or a latency improvement. The original run generated ten
questions, while the final run returned six; total times are not comparable
as throughput gains.

After bounded repair was added, the assessment-specific suite passed 65 tests,
the full isolated-worktree suite passed 662 tests with 14 skips and the existing
optional-reranker warning, Ruff passed, and the route harness remained 119/119
with Unexpected RAG 0. These are pre-serial-review baseline gates; they do not
establish the current two-module reviewer path as stable or validate its
live-quality behavior.

### Split Item-Critic Calibration (2026-09-11)

`var/artifacts/assessment/random_five_formal_critic.json` replays the ten
previously generated `Qwen/Qwen3.5-9B` questions through the current
`AssessmentQualityCritic` only. The five two-question calls all returned
complete structured verdicts with `Pro/deepseek-ai/DeepSeek-V3`. They took
27.127 s, 42.281 s, 30.537 s, 27.300 s, and 26.299 s: 153.545 s total and
30.709 s per batch on average. These numbers exclude retrieval, generation,
Evidence verification, and any repair call.

The service acceptance mapping passed one question, rejected eight as
`implausible_distractors`, and rejected one as `answer_ambiguity`. The critic
identified the weak or nonparallel options previously found by manual review in
the visual-encoding, recurrent-neural-network, data-cleaning, and
technology-forecasting batches. This is evidence that the split critic has more
useful discrimination than the historical combined verifier, not a calibrated
estimate of precision or recall.

Calibration also exposed two structured-output issues. `pedagogically_useful`
and `pedagogical_defects` are independent signals: a question can retain some
instructional value while still containing a mandatory rejection defect, so the
service rejects either a negative usefulness verdict or any listed defect
without forcing the model fields to be logical opposites. Duplicate checks
remain fail-closed, while the JSON Schema now declares `uniqueItems` for answer
sets, leakage signals, and pedagogical defects so the provider sees the same
uniqueness constraint before Pydantic validation.

Repeated Pandas runs varied on whether the `read_csv` question's alternatives
were plausible enough to pass. The critic must therefore remain a rejection
gate and cannot be treated as ground truth. Before production use, build a
human-labeled item-quality set and measure reviewer agreement, false rejection,
false acceptance, and latency by topic and difficulty. The observed 26-42 s
critic batch latency also makes asynchronous job status or progress feedback a
product requirement for larger quizzes.

### Original MVP Gates

The implementation snapshot passed 666 tests with 14 existing skips and one
optional-reranker warning. The full suite ran outside the network-restricted
sandbox in a temporary source copy containing the repository-root `conftest.py`,
but no real `.env` or `var/`. It used the original virtualenv dependencies.
An earlier incomplete copy missed that root test configuration and failed
collection; a subsequent sandbox run stalled near completion and was terminated.

Additional gates: route tests 37/37, route harness 119/119 with Unexpected RAG 0,
repository Ruff check passed, and 249 files passed format check at verification.
The new adapter tests use real ChatOpenAI structured parsing over a simulated
HTTP transport. No frontend was changed, so no frontend build was run.

One live service-level smoke request (`topic=PCA`, `count=1`) succeeded with the
configured model and existing textbook knowledge base in 18.94 seconds. It
returned a Chinese PCA/LDA question, four options, answer B, explanation, and
textbook source references. This confirms one provider call, not a quality
benchmark or a live authenticated end-to-end submission. Retrieved passages
still contained some duplicated/fragmented textbook text; improving that
upstream corpus is outside this assessment slice.

A separate development API was started at `http://127.0.0.1:8085/docs`, with
health check verified. Existing services were not restarted. For local testing,
use `/api/auth/login` in the API documentation to obtain the existing login
cookie before calling `/api/questions/generate`. The root `/` has no UI.
