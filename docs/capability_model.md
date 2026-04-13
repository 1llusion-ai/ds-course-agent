# Capability Model

This project intentionally uses a mixed capability architecture instead of turning every behavior into a `tool` or every strategy into a `skill`.

The goal is to keep the teaching agent explainable, reusable, and easy to extend without letting the codebase drift into "everything is an agent primitive".

## Design Rules

Use a `tool` when the capability is primarily:

- deterministic or query-like
- backed by a data source or external state
- useful across multiple answer strategies
- something the agent can "call" and inspect

Use a `skill` when the capability is primarily:

- a user-facing response pattern
- reusable across many prompts
- driven by structured instructions in `SKILL.md`
- better described as "how to respond" than "what data to fetch"

Use a normal module/service when the capability is primarily:

- internal business logic
- ranking, filtering, scoring, or aggregation
- profile updates or weak-spot detection
- implementation detail behind a tool or skill

## Current Capability Matrix

### Tools

These expose data access or deterministic query behaviors to the agent.

| Capability | Why it is a tool | Main file |
| --- | --- | --- |
| Textbook retrieval | Query textbook chunks and return grounded context | `core/tools.py` |
| KB status check | Deterministic environment/status check | `core/tools.py` |
| Course schedule query | Query course time/location from structured schedule data | `core/tools.py` |

### Skills

These are higher-level teaching strategies. They are intentionally few in number.

| Skill | Why it stays a skill | Main files |
| --- | --- | --- |
| `learning-path` | Turns a "how should I study" intent into a prioritized plan | `skills/learning-path/SKILL.md`, `skills/learning-path/scripts/*` |
| `personalized-explanation` | Turns a "explain this for me, based on my state" intent into a grounded explanation scaffold | `skills/personalized-explanation/SKILL.md`, `skills/personalized-explanation/scripts/*` |

### Internal Modules

These should not be promoted to tools or skills unless their role changes.

| Module area | Why it remains internal |
| --- | --- |
| `core/memory_core.py` | profile aggregation, weak-spot detection, resolved-history bookkeeping |
| `core/knowledge_mapper.py` | concept matching and related-concept lookup |
| `skills/learning-path/scripts/planner.py` | internal route ranking and step ordering |
| `skills/personalized-explanation/scripts/strategy.py` | internal relevance filtering and scaffold strategy |
| retrieval fusion / rerank logic | internal ranking implementation rather than a user-facing capability |

## Why Not Make Everything a Skill?

Because that usually makes the system noisier, not better.

If weak-spot detection, concept ranking, or retrieval fusion were all represented as skills, we would lose:

- clear ownership of internal logic
- predictable test boundaries
- simple debugging of deterministic components

This repo should usually keep only `2-4` top-level skills for the main teaching agent.

## Why Not Make `learning-path` a Tool?

Because it is not a pure fetch or deterministic query.

It combines:

- profile state
- concept ordering
- weak-spot priority
- teaching strategy

That makes it a better fit for a strategy skill than a plain tool.

## Why `personalized-explanation` Is Still Acceptable as a Skill

This one sits on the boundary between `skill` and `module`.

It is still worth keeping as a skill because:

- the user intent is recognizable
- the response style is stable and reusable
- the `SKILL.md` instructions are doing real work

If it becomes mostly hidden heuristics with little declarative guidance, it should be demoted back into a normal module later.

## Decision Checklist for New Capabilities

Before adding a new feature, ask:

1. Is this mainly fetching/querying something?
   Then it is probably a `tool`.

2. Is this mainly a reusable response strategy the user can implicitly ask for?
   Then it may be a `skill`.

3. Is this mostly internal scoring, mapping, ranking, or state updates?
   Then keep it as a normal module/service.

## Recommended Future Additions

Good `tool` candidates:

- a calculator/statistics helper
- a notebook/code sandbox with strict safety boundaries
- a structured assignment metadata query tool

Good `skill` candidates:

- mistake-review / weak-spot revision
- homework-hinting without direct answer dumping

Not good as standalone skills:

- weak-spot score updates
- concept ranking
- retrieval fusion
- source formatting
