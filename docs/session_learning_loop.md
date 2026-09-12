# Session Learning Loop

The first loop uses observed course conversations and scored single-choice
practice. KT integration remains behind `LearnerStateProvider`; no mastery
probability or measured learning gain is claimed by the current rules.

## Behavior

1. `QueryPipeline` maps course questions to canonical KCs. Learning events retain
   all event-eligible matches, including comparisons involving two concepts.
2. After a successful teaching answer has been persisted, the shared turn
   producer schedules practice for that student's session. Scheduling failures
   are logged independently and do not invalidate the answer.
3. `AssessmentAssignmentPlanner.plan_session` selects only KCs mentioned in the
   same student/session. It creates two-question requests. A persistent unique
   student/session/KC identity prevents repeated follow-ups from creating more
   automatic quizzes for the same topic.
4. A process-local worker invokes the existing assignment tool. The assessment
   list shows queued, generating, and failed preparation states. Students can
   filter by session and retry failures. Active questions remain immutable.
5. The authenticated submission API injects `AssessmentEvidenceRecorder` into
   the assessment application service. The service persists server-scored
   results before publishing typed `QuestionAnsweredEvent` facts.
6. The recorder uses stable assessment/question event IDs. Retrying submission
   or reading its result repairs interrupted evidence publication without
   double-counting answers. `MemoryCore` rebuilds the persisted practice profile.
7. Ordinary grounded concept answers and personalized explanations consume the
   relevant practice evidence. Guidance affects answer generation, not retrieval
   queries. The result view offers a return to the originating conversation.

Explicitly requesting another assessment still invokes the existing assignment
route. It may provide a new practice opportunity at an evidence-informed level.

## Evidence And Policy

Conversation mentions and self-reported understanding do not advance exercise
difficulty. Missing practice evidence means unassessed, never low mastery.

`ConceptPractice` retains total answers, correct answers, assessment count, the
latest six answers' aggregate, last answer time, and a recent incorrect stem.
Raw events retain question/assessment IDs, requested question difficulty,
selected and correct option IDs, response time, and answer-change count. The
original question, answer key, and evidence remain in the assessment record.

The first policy is deliberately explicit and replaceable:

- Any incorrect answer in the latest six: `needs_practice`, basic practice and
  a concrete explanation of the current question.
- All recent answers correct: `practiced`; at least two answers permit an
  intermediate follow-up assessment.
- At least three recent correct answers across two assessments, including at
  least two intermediate/advanced items: `ready_for_extension`, permitting an
  advanced follow-up.

These are teaching heuristics, not calibrated student or item difficulty
estimates. Correct answers do not prove independence from outside help. A
single-choice error does not establish a particular misconception. Historical
clarification/self-report records remain separate from scored practice.

## Ownership And Persistence

| Owner | Responsibility |
| --- | --- |
| `agent/learning_loop.py` | Background orchestration after the completed turn |
| `teaching/assessment_assignment.py` | Session target selection and difficulty policy |
| `assessment/preparation.py` | Durable request identity and queue state transitions |
| `assessment/application.py` | Assignment, answer-blind projection, scoring and callback boundary |
| `teaching/assessment_evidence.py` | Scored result to learning-event translation |
| `teaching/practice.py` | Evidence summary and conservative readiness rules |
| `teaching/practice_guidance.py` | Relevant evidence to explanation guidance |

The preparation table shares `ASSESSMENT_DB_PATH` with assessment storage. Events
and profile projections use `CHAT_HISTORY_DIR`. Runtime files remain under
`var/` by default. Queue claims use SQLite compare-and-set transitions; automatic
assignments reuse the preparation ID even after retry.

The worker runs one generation at a time per application process. Persisted
queued work resumes when the student's preparation list is read or another
session turn schedules it. An inactive generating request older than fifteen
minutes becomes retryable when listed, covering interrupted processes. This is
not a distributed queue with worker heartbeats; production capacity and recovery
latency require a separate deployment decision.

## Validation Boundaries

The closed-loop tests use fixture generation to verify session isolation,
idempotency, recovery, durable evidence, and subsequent teaching choices.
Turn tests cover both synchronous and streaming completion. HTTP tests cover
authenticated projections. Live generation and browser checks must be reported
separately from fixture-based tests.
