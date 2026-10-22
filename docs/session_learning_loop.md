# Session Learning Loop

The loop uses course conversations and server-scored single-choice practice.
The existing persisted learner profile, exposed through `LearnerStateProvider`,
remains the only learner-state source. These rules do not estimate mastery
probability or measured learning gain.

## Behavior and opportunities

1. `QueryPipeline` maps course questions to canonical KCs. Successful teaching
   turns persist `LearningEvent` facts before scheduling practice; scheduling
   failures do not invalidate the answer.
2. `AssessmentAssignmentPlanner` reads the current student's course/session
   mentions, actual scored-answer events, and latest profile. An opportunity is
   identified by the latest scored event plus resource/policy revision, or an
   initial opportunity if no answer exists. Repeated mentions or profile revision
   changes alone cannot create another opportunity. A resource revision change
   permits a replacement plan, including recovery from an old deterministic
   insufficient-evidence failure.
3. Each session is bounded to three distinct KCs, three opportunities per KC and
   nine preparations in total. Historical failed preparations consume their
   opportunity, not every future scored opportunity. A queued/generating job or
   actual READY/IN_PROGRESS assessment protects that student's KC across sessions,
   including explicit assignments without preparation records.
4. Each automatic plan requests exactly two complementary questions, one concept
   distinction and one application transfer, at the profile's recommended level.
   Trusted `AssessmentPlanContext` freezes the opportunity, profile revision,
   source-event cursor, resource revision, policy and selection reason. These
   planning facts are server-owned and are not accepted in client generation input.
5. The worker uses the existing assignment tool/application service. Complete
   reviewed content is reused where compatible; only missing slots are generated.
   READY requires the exact count, both review gates, member coverage and current
   resources. An opened assessment's question snapshot is never replaced.
6. Submission persists server scoring before `AssessmentEvidenceRecorder`
   publishes stable assessment/question event IDs. Submission retries and result
   reads repair interrupted publication without counting the same scored event
   twice. The existing profile projection consumes those facts.
7. Subsequent teaching explanations and the next practice opportunity use that
   profile. Teaching guidance affects explanation generation, not retrieval queries.

Explicit assessment requests use the same application owner. Requests for a KC
with an active assessment return that existing immutable assessment. Allocation
is serialized inside the application process; the durable preparation repository
also uses a SQLite transaction to prevent simultaneous queued/generating jobs
for the same student/course/KC.

## Practice evidence and difficulty

Conversation mentions and self-reported understanding do not advance difficulty.
Missing practice evidence means unassessed. `ConceptPractice` retains raw answer
counts, the latest six answers, recent incorrect stems and recent attempts for
feedback, alongside a separate recommended difficulty and independent-item count.

Only the first scored exposure of a stable content `item_id` counts as independent
progression evidence; old records fall back to their question ID. Repeated-item
answers still update raw counts and recent feedback. The policy advances at most
one level per scored assessment opportunity:

- Two distinct correct items in one opportunity permit basic → intermediate.
- Advanced requires at least four distinct items across two opportunities, at
  least three correct among the latest four, including two intermediate/advanced
  successes, and a new opportunity with two correct distinct items.
- One error preserves the current recommendation. Two new unconsumed errors
  among the latest three distinct items, with negative evidence in the current
  opportunity, lower it by one level. Those errors cannot trigger another drop
  in a later successful opportunity.

Any recent raw error retains `needs_practice` feedback even when the independent
evidence supports an intermediate or advanced recommendation. Thus a repeated
wrong answer remains visible without manufacturing another independent failure.
These are explicit teaching heuristics, not calibrated ability/item estimates.

## Assessment model context

`teaching/assessment_assignment.py` owns the projection from `LearnerStateSnapshot`
to the bounded `AssessmentLearnerEvidence` generation input. It includes only the
selected course/KC's scored totals, independent-item count, recent counts,
mention/clarification counts and at most two recent incorrect attempts. Each
attempt retains the recorded stem, selected/correct option text and observed
cognitive operation when available. Missing evidence stays unknown. Student IDs,
unrelated KCs and raw conversation transcripts are excluded. Mentions and
clarifications do not increase the recommended difficulty. The immutable request,
including this evidence, survives preparation retries and assignment persistence.

`assessment/task_context.py` owns the resolved model context. The author and editor
receive the canonical target, explicit members, course learning objectives,
ordered slot tasks, shared operation rules, difficulty scaffolding and the learner
projection. Shared rules appear once per prompt. Recorded errors guide practice
focus and distractors; they cannot supply textbook facts. The evidence verifier
and quality critic receive the target's lexical scope without the learner
projection, requested cognitive labels or author answer/analysis. Thus an author's
request for interpretation cannot turn a recall item into an accepted item merely
by labeling it.

The normal conversational path still renders the learner summary and bounded
relevant memory into system context, followed by history messages and the current
user input (`agent/message_context.py`, `runtime/messages.py`). Assessment generation
uses its own bounded projection instead of concatenating that full conversation.

Correct-answer excerpt coverage is checked inside the shared repair loop for both
fresh and reused batches. An uncovered member reserves one replacement slot while
preserving as much already-covered content as possible. This is a content repair
when the selected evidence supports the missing member; retrieval without adequate
member evidence still fails before authoring. A reviewer outage preserves the
candidate for review without rewriting it, obeys the per-call/lifetime retry budget
and leaves unrelated content rejection codes intact. Permanent provider errors do
not trigger another reviewer call.

## Reviewed content and resource identity

Normal successful assignment organically accumulates reviewed content; there is
no offline bulk generation. Shared items carry stable content IDs, correct-answer
excerpt certificates, critic operation/objective, original evidence and a resource
revision. Student assignments, IDs, attempts, answers and profile state stay separate.
Selection requires matching course, target, graph/TOC digests, corpus/index revision,
evidence/review policy, difficulty and teaching objective/operation. Active and
latest-three-assessment items are excluded; unseen items precede older exposures.
The server-owned `AssessmentExposureConstraint` applies equally to cached content,
whole-batch drafting, missing-slot editing and retained retry slots. A forbidden
item becomes a repairable slot rejection. Progress freezes the original plan's
exclusions; current exposure is refreshed before publication in the same
student/course scope. Older history outside this bounded window remains eligible
for review. The author/editor sees only current-KC avoid examples, capped at 4,000
characters within a 64,000-character full prompt limit; all forbidden identities
remain enforced even when their examples are omitted.

Review certificates additionally bind the concrete slot objective and recorded
error focus through a task fingerprint. Counts and learner identity are excluded
from this fingerprint so compatible tasks remain shareable. Different task
certificates can coexist for the same content identity. The shared bank retains
the fingerprint, not the learner's raw mistake records. This binds reuse to the
task under which both gates accepted the item; it does not independently establish
that an item remedies a particular misconception or measures learning gain.
Assessment database migration 8 preserves existing content while extending the
certificate key and persisting the bounded learner projection on assignments.

`benchmarks/assessment_task_harness.py` validates fixed cognitive cases offline by
default. Its optional provider mode evaluates critic classification only; neither
passing synthetic regression tests nor matching these labels establishes actual
generation success rates. The authored annotations still require teacher review.

Identity ignores option labels/order and explanation, plus layout and terminal
question punctuation. It preserves case, numbers, operators, negation, factorials
and superscripts. This is a conservative surface deduplication rule; it does not
claim to detect semantic paraphrases. Contradictory reviewed keys for identical
content quarantine the shared asset and prevent publication of the conflicting batch.

A complete compatible original batch can be reused without retrieval/model calls.
A partial match seeds accepted slots and the normal editor fills only the shortfall;
new items pass both gates. Recombining items from multiple original batches runs
both gates again for current batch complementarity. `BatchReviewState` persists
that obligation independently of missing slots, so a retry cannot bypass it.
Its certificate binds exact slot item IDs, target, difficulty, teaching requirement
(including operations) and review policy. Composition changes invalidate it.
A rejected combination keeps compatible slots and sends only rejected slots
through the same editor/dual-review loop. Individual assets remain reusable in
other compatible combinations. Reviewer unavailability preserves accepted items
and an outstanding gate; each failed gate attempt consumes the same lifetime
budget. Four failed pure gate attempts exhaust retry eligibility.
Cached evidence must fit the
same budgets; oversized entries fall back to normal generation. A full cache hit
that omits a composite target member reserves a missing slot to generate that
member. Final member coverage uses verified correct-answer excerpts, never a
combined name copied into the stem.

Resource changes invalidate pending progress and reuse, not historical results.
Retries retain accepted slots and certificates only with their exact resource
revision. Repair is bounded to two editor rounds per call and four cumulative recovery
rounds across retained progress. Failed combination-review attempts also consume
a cumulative round; there is no separate unbounded gate retry budget. Capped progress is not retryable; stale or unversioned
progress is rejected before model calls.

## Ownership and persistence

| Owner | Responsibility |
| --- | --- |
| `agent/learning_loop.py` | Completed-turn orchestration and background preparation |
| `teaching/assessment_assignment.py` | Opportunity, target, objectives and difficulty selection |
| `assessment/preparation.py` | Durable opportunity identity and queue transitions |
| `assessment/application.py` | Allocation, immutable assignment, scoring and callbacks |
| `assessment/items.py` | Shared reviewed content identity, storage and selection |
| `assessment/versioning.py` | Resource/review identity without opening a corpus/index |
| `assessment/generation_constraints.py` | Server exposure facts and composition-bound review certificate |
| `teaching/assessment_evidence.py` | Scored result to learning events |
| `teaching/practice.py` | Raw feedback and independent progression evidence |

Preparations, assignments and reviewed content share `ASSESSMENT_DB_PATH`;
learning events and profile projections use `APP_DB_PATH`. Runtime files remain
under `var/`. Existing records load without newly introduced certificates, item
IDs or planning context; they do not become certified reusable content. Review
policy `evidence-and-blind-critic/3` invalidates old in-flight progress and assets
whose combination gate/exposure contract predates this version. Assignment
snapshots retain their original request and evidence.

The worker runs one generation at a time per process. Queued work resumes when
preparations are listed or another turn schedules it. An inactive generating job
older than fifteen minutes becomes retryable when listed. This is not a distributed
queue with worker heartbeats or a distributed allocation lock; deployment across
processes requires a separate concurrency/capacity decision.

## Validation boundaries

Offline fixtures test evidence provenance, opportunities, profile progression,
concurrent allocation, deduplication, reuse/shortfall, both review boundaries,
idempotency and recovery. They do not establish live-provider question quality,
semantic paraphrase detection or learning effectiveness. The captured correlation
case replays selection using frozen source pages; no real question batch is
pregenerated or added to a runtime database/index by this validation.
