# Research Direction Review — Knowledge-State-Conditioned Evidence Acquisition

**Date:** 2026-07-25
**Branch:** `feat/research-knowledge-state-search`
**Review skills:** `research-review` + `analyze-results`
**External review:** independent secondary Codex reviewer, two rounds, xhigh
**Scope:** current research direction, Phase A pilot, Phase B annotation state, method-selection path, and closed-loop gate

## 1. Executive verdict

| Dimension | Score | Verdict |
|---|---:|---|
| Research direction value | **4/5** | Worth continuing |
| Current execution path | **2/5** | Must be reordered and narrowed |

### Bottom line

The question is good:

> Should a learner's knowledge state affect evidence acquisition and search
> planning, rather than only the final answer?

The current execution path is not yet good enough. The project has demonstrated
that a typed evidence-obligation interface can be built and that obligation
execution is a real failure mode. It has **not** demonstrated that
`Counterfactual-Selective Gap` is an independent, generalizable, or
cost-fair algorithmic contribution.

**Decision: continue the direction, but stop the current “full model-only
annotation → complex planner → closed-loop” momentum.** First establish a small
independent human-gold slice and run a static, matched-budget attribution
experiment.

## 2. What was reviewed

### Research framing

The current narrowed problem is:

```text
learner knowledge state
    → learner-specific evidence obligations
    → evidence acquisition / query planning
    → hard-core-preserving, auditable evidence coverage
```

The candidate methods are:

- `M1N`: null-structured shared core-only baseline;
- `M1`: Raw Profile + Core;
- `M2`: Predicted Gap + Core;
- `M3`: Counterfactual-Selective Gap + Core;
- `M4`: Gold Gap oracle;
- `M5`: Swapped/Wrong Gap negative control.

### Local evidence

The repaired Phase A three-repeat artifact contains 72 successful cases. Its
aggregate summary is:

| Method | Core recall | Learner recall | Edge recall | Path recall | Strict precision | Conflict rate | Logical model calls |
|---|---:|---:|---:|---:|---:|---:|---:|
| M1N | 0.711 | 0.000 | 0.593 | 0.222 | 0.444 | 0.123 | 0.500 |
| M1 | 0.667 | 0.111 | 0.722 | 0.389 | 0.452 | 0.148 | 1.000 |
| M2 | 0.756 | 0.667 | 0.815 | 0.611 | 0.529 | 0.111 | 2.000 |
| M3 | 0.733 | 1.000 | 0.889 | 0.778 | 0.562 | 0.117 | 2.444 |

These values are diagnostic only:

- 3 tasks;
- 6 profiles;
- 18 claims;
- 9 edges;
- 30 sources;
- single-curator annotations;
- curator-written paraphrase sources;
- no independent human validation.

The paired M3-vs-M1 analysis is mixed rather than decisive:

- all-profile core recall delta: `-0.044`;
- gap-profile learner recall delta: `+0.222`;
- all-profile strict precision delta: `-0.024`;
- all-profile path recall delta: `-0.056`;
- logical model-call delta: `+1.333`;
- M3 was positive on only `3/9` paired gap rows for learner recall.

The positive repaired-contract summary in the tracker should therefore remain a
pilot signal, not a final method claim.

### Current Phase B state

As of this review:

- 12 tasks / 24 profiles / 72 claims / 48 edges are designed;
- 144 source excerpts passed capture and QA;
- `human_verified_count=0`;
- the full relation dataset is not frozen;
- the latest full-run directory contains 1,440 Gemini judgments but no complete
  consensus/final proxy label artifact;
- `dataset_frozen=false`;
- `method_runs_authorized=false`;
- closed-loop remains blocked.

The existing audit is correctly `WARN`: it found no fake ground truth or
self-normalized score, but the evaluation substrate is not yet independent
enough for method claims.

## 3. What is genuinely promising

1. **The research question is sharper than generic educational
   personalization.** It distinguishes answer personalization from
   evidence-acquisition personalization.
2. **Hard-core support is the right constraint.** Learner-specific retrieval
   must not improve by silently dropping foundational evidence.
3. **M4/M5 are valuable controls.** Gold-gap and wrong-gap controls can test
   whether the benchmark rewards correct learner state rather than merely the
   presence of structured gap text.
4. **The failure decomposition was useful.** The original failures localized to
   obligation-to-query execution, rather than being hidden behind aggregate
   answer quality.
5. **The typed ledger/target contract is a good systems contribution.** It
   makes support, cost, and failure accounting more auditable than a final-answer
   preference score.

## 4. Fatal or near-fatal risks

### 4.1 The evaluation gold is not yet trustworthy enough

Correct URL capture, source checksums, model repeatability, and calibration
agreement do not prove that a source supports a target relation. The current
model-only relation track can be retained as an exploratory proxy, but it must
not be called human gold or used for the headline method result.

### 4.2 M3 is confounded with the execution guardrail

The current evidence cannot separate:

1. **representation effect:** Raw Profile vs Predicted Gap vs Selective Gap;
2. **execution effect:** free planner vs mandatory target-coverage contract.

The contract repair itself changed whether learner obligations reached queries.
Therefore the current M3 gain may be a contract-governed execution effect rather
than a counterfactual selection effect.

### 4.3 Cost comparisons are not yet fair

M3 uses substantially more logical model calls than M1. Fewer external search
calls do not imply lower total cost. Future claims must report:

- external search calls;
- logical model calls;
- input/output tokens;
- latency;
- retry and failure cost;
- selected source count.

### 4.4 The benchmark may reward its own construction

The Phase A Gold-vs-Core gate shows that the pilot is discriminable under its
curated task/profile/source design. It does not yet show that natural educational
tasks have the same structure or that the planner generalizes to held-out task
families.

### 4.5 Annotation engineering is beginning to replace algorithm validation

The v1–v6 protocol, authorization, retry, drift, scope, and seal work is useful
infrastructure, but it cannot become the research result by default. If the
relation ontology cannot be reliably human-validated, the correct response is to
simplify the ontology, not to add another protocol version.

### 4.6 “Counterfactual” may overstate the mechanism

Unless the method explicitly defines an intervention, alternative learner state,
potential obligation, and selection rule, `counterfactual` sounds more causal
than the implementation warrants. A safer label is:

> `Learner-Gap-Conditioned Evidence Acquisition`

or:

> `Learner-Specific Evidence Obligation Selection`

## 5. Is the current path correct?

| Stage | Assessment | Required adjustment |
|---|---|---|
| Phase A pilot | **Correct and complete** | Freeze it as diagnostic; stop searching for more positive pilot evidence |
| Phase B dataset construction | **Correct goal, wrong order** | Human-gold anchor before completing/expanding model-only labels |
| M1/M2/M3 comparison | **Correct matrix, insufficient attribution** | Add representation × executor factorial and matched total budget |
| Closed-loop | **Correctly blocked** | Do not start until static C1 passes on independent gold |
| SFT/RL/learning gain | **Correctly out of scope** | Keep blocked |

The current blocking behavior is correct. The problematic part is that the
project has continued deep annotation engineering while the two scientific
questions that select the Phase B method remain unresolved:

1. Does the selective gate add value beyond predicted obligations?
2. Does paired counterfactual neutralization add value beyond a simpler
   neutralization?

## 6. Required next experiment package

### 6.1 Stop and archive the current full model-only annotation

**Decision: stop the current full annotation continuation.**

- Stop deferred queue/retry/consensus completion.
- Preserve all existing files.
- Mark them as `exploratory_proxy`.
- Use them for schema debugging, disagreement analysis, and human-anchor
  selection only.
- Do not use them for primary evaluation, significance tests, or method
  authorization.

This is not data deletion and not a claim that the existing artifacts are
useless. It is a claim boundary.

### 6.2 Human-gold anchor

Run a small, independent anchor before resuming any full annotation:

- 6–8 task-profile cases;
- balanced prerequisite, misconception, and goal gaps;
- two independent blind annotators;
- one independent adjudicator;
- complete source-to-claim/edge judgments for the selected cases;
- proxy labels compared against human labels but never promoted to gold.

Suggested pre-registered checks:

- overall agreement statistic at least `0.70`;
- no gap type below `0.60`;
- adjudication rate no higher than `20%`;
- M4 vs M1N learner-coverage margin at least `0.10`;
- M5 must not approach M4.

If the slice fails, simplify the relation ontology before doing more methods.

### 6.3 Representation × executor factorial

Run a 3×2 static factorial:

| Representation | Free executor | Mandatory target-coverage guardrail |
|---|---:|---:|
| M1 Raw Profile + Core | M1-F | M1-G |
| M2 Predicted Gap + Core | M2-F | M2-G |
| M3 Selective Gap + Core | M3-F | M3-G |

The guardrail may enforce only obligations generated by the same method. It must
not inject gold learner targets into M1 or M2.

Minimum design:

- 6–8 task-profile cases;
- all three gap types;
- 3 repeats;
- same model, temperature, source pool, output schema, retry policy;
- same maximum search calls and source budget;
- matched maximum logical model calls and token budget;
- report native cost separately.

Primary estimand:

> learner-valid evidence precision at a fixed total budget.

Hard constraints:

- learner coverage above a pre-registered floor;
- hard-core recall non-inferior to M1.

Secondary diagnostics:

- obligation execution rate;
- missed-obligation rate;
- target activation;
- redundant query rate;
- conflict rate;
- path recall;
- token/latency/retry cost.

### 6.4 Decision tree

1. **M3 > M1 and M3 > M2 under free and guarded executors, with matched cost**
   → continue to a small fixed-snapshot closed-loop experiment.
2. **M3 > M1 but not M2**
   → remove the counterfactual-selective claim; frame the result as structured
   learner-gap conditioning.
3. **M3 works only with the guardrail**
   → frame as a contract-governed system/protocol contribution, not a new
   planner algorithm.
4. **M3 does not beat M1, M5 is also strong, or human-gold/discriminability
   fails**
   → stop the M3 method line; simplify, pivot to benchmark/protocol, or end
   this research line.

## 7. Recommended paper framing

### Preferred working title

> **Learner-Conditioned Evidence Obligations for Educational Search: A
> Controlled Study of Coverage, Precision, and Cost**

### Current defensible claim

> We study whether learner knowledge state should enter evidence acquisition
> rather than only answer generation. We formulate learner-specific evidence
> obligations and evaluate their effect on learner evidence coverage, hard-core
> support, precision, and search cost under a fixed evidence snapshot.

### Claims that remain prohibited

- improved student learning or transfer;
- knowledge tracing/BKT quality;
- causal reasoning;
- general-purpose deep research;
- robust superiority across educational domains;
- SFT/RL/bandit benefit;
- closed-loop benefit before C1 passes;
- human-validated benchmark before human validation exists.

## 8. External literature sanity check

The generic claim “personalization should enter the deep-research loop” is not
novel by itself. Recent work already studies personalized deep research,
personalized deep-research evaluation, and the need for real-user evaluation.
The defensible novelty must therefore come from the narrower educational
knowledge-state formulation, explicit evidence obligations, hard-core
preservation, and a credible evaluation protocol—not from combining the words
“student profile” and “web search.”

## 9. Two-round external review summary

### Round 1

The independent reviewer rated the direction **4/5** and the current path
**2/5**, recommending conditional continuation as a static C1 controlled study
or benchmark/protocol paper rather than a new search-algorithm paper.

The load-bearing criticisms were:

- no human gold;
- M3/guardrail confounding;
- unfair logical-call budget;
- pilot construction bias;
- unclear estimand denominators;
- annotation bottleneck replacing algorithm validation;
- possible overclaim in the word `counterfactual`.

### Round 2 follow-up

The reviewer made three binary recommendations:

1. **Stop v6 full model-only annotation now; preserve it as exploratory proxy.**
2. **Run the 3×2 representation × executor factorial with matched budget and
   three repeats.**
3. **Use a three-way paper decision tree:** algorithm if M3 beats M2
   independently; systems/protocol if only the guardrail works; benchmark
   simplification or stop if human-gold/discriminability fails.

## 10. Final decision

**The direction is good. We are only partially on the right road.**

The scientific road is right:

```text
learner state → evidence obligations → auditable evidence acquisition
```

The operational road has drifted:

```text
complex annotation protocol → more retries → more artifacts → eventual method
```

The next correct move is to reverse that order:

```text
small human-gold validity gate
    → matched-budget static attribution
    → method selection
    → only then closed-loop
```
