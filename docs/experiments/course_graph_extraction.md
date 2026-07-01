# Experimental Course Graph Extraction

This branch adds a lightweight, optional course-graph extraction prototype for
learner-state-aware RAG routing experiments.

## Files

- `core/course_graph.py`: JSON-native course graph schema.
- `scripts/build_course_graph.py`: offline extractor from Chroma chunks or a JSON/JSONL chunks file.

The extractor is not wired into runtime RAG yet. It is intended for generating
`data/course_graph_v2.json` and inspecting whether the schema/prompt is useful.

## Backends

### Prompt backend, default

Uses the configured chat model and an education-specific JSON prompt.

Dry run one chunk:

```bash
python scripts/build_course_graph.py --limit 1 --dry-run
```

Generate a small graph:

```bash
python scripts/build_course_graph.py --limit 5 --llm-timeout 120 --max-chars 1200 --output data/course_graph_v2.json
```

For SiliconFlow models that are slow through LangChain wrappers, use direct HTTP mode:

```bash
REMOTE_MODEL_NAME=deepseek-ai/DeepSeek-V4-Pro python scripts/build_course_graph.py --backend prompt --llm-provider direct --limit 1 --llm-timeout 360 --max-chars 800 --max-output-tokens 1600 --output data/course_graph_v2_v4pro.json
```

By default, the script skips likely cover, publisher, preface, and table-of-contents chunks. To inspect raw chunks without filtering:

```bash
python scripts/build_course_graph.py --limit 1 --dry-run --no-skip-noise
```

### LangChain LLMGraphTransformer backend, optional

Requires optional dependency:

```bash
pip install langchain-experimental
```

Run:

```bash
python scripts/build_course_graph.py --backend transformer --limit 5 --output data/course_graph_v2.json
```

This backend is useful as an off-the-shelf KG extraction baseline. In early testing, the prompt backend produced more course-specific Chinese concepts, definitions, and rationales, while the transformer backend produced broader generic entities. Prefer the prompt backend for dataset construction unless you specifically need a LangChain transformer baseline.

For long runs, start with 3-5 chunks. The script prints per-chunk progress and skips failed chunks instead of aborting the whole job.

## Education schema

Node types:

- `Concept`
- `Algorithm`
- `Method`
- `Formula`
- `Metric`
- `Example`
- `Chapter`
- `Section`
- `Misconception`

Relation types:

- `part_of`
- `prerequisite_of`
- `related_to`
- `confusable_with`
- `used_for`
- `mitigates`
- `evaluated_by`
- `example_of`
- `evidence_in`

Chunk pedagogical types:

- `definition`
- `example`
- `formula`
- `procedure`
- `contrast`
- `summary`
- `exercise`
- `misconception_correction`
- `other`

## Intended use for the paper direction

The graph construction itself is not the main contribution. It is a lightweight
supporting layer for:

```text
query + learner profile -> retrieval route / query expansion / reranking
```

Recommended first experiment:

1. Generate `course_graph_v2.json` for 20-50 high-quality chunks.
2. Inspect whether `prerequisite_of` and `confusable_with` are reliable enough.
3. Use the graph only as query-time expansion signals before building a full router.
