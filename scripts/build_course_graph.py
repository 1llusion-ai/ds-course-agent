"""Build a lightweight course graph from existing course chunks.

This is an experimental, opt-in script for adapting off-the-shelf LLM based
knowledge-graph extraction to an education-specific schema. It supports two
backends:

1. ``prompt`` (default): call the configured chat model with a strict JSON
   extraction prompt. This has no extra dependency beyond the project's LLM
   stack.
2. ``transformer``: use LangChain's optional ``LLMGraphTransformer`` when
   ``langchain-experimental`` is installed. This path is kept lightweight and
   falls back with a clear error if the package is missing.

The generated graph is intentionally not part of the runtime path yet. Use it
for offline inspection and future learner-state-aware retrieval routing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from langchain_core.documents import Document

import utils.config as config
from core.course_graph import (
    ALLOWED_NODE_TYPES,
    ALLOWED_PEDAGOGICAL_TYPES,
    ALLOWED_RELATION_TYPES,
    ChunkConceptTag,
    CourseGraph,
    CourseGraphEdge,
    CourseGraphNode,
    MisconceptionItem,
    merge_course_graphs,
    normalize_concept_id,
)


@dataclass
class SourceChunk:
    chunk_id: str
    text: str
    metadata: dict[str, Any]


NOISE_PATTERNS = (
    "logo of",
    "qr code",
    "contents",
    "目录contents",
    "本书资源使用说明",
    "高等学校“新形态”规划教材",
    "前言",
    "图书在版编目",
    "isbn",
    "出版发行",
    "责任编辑",
    "定价",
)


def _compact_text(text: str, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def is_probably_teaching_chunk(chunk: SourceChunk, min_chars: int = 700) -> bool:
    text = _compact_text(chunk.text, max_chars=500).lower()
    if len(str(chunk.text or "")) < min_chars:
        return False
    if str(chunk.text or "").count(".....") >= 3:
        return False
    if any(pattern in text for pattern in NOISE_PATTERNS):
        return False
    section = str(chunk.metadata.get("section") or "")
    if section.strip() in {"目录", "前言"}:
        return False
    return True


def load_chunks_from_chroma(
    collection_name: str | None = None,
    limit: int | None = None,
    skip_noise: bool = False,
) -> list[SourceChunk]:
    """Load chunks from the active Chroma collection."""
    try:
        import chromadb
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("chromadb is required to load chunks from the vector store") from exc

    client = chromadb.PersistentClient(path=config.CHROMA_PERSIST_DIR)
    collection = client.get_collection(collection_name or config.collection_name)
    payload = collection.get(include=["documents", "metadatas"])

    chunks: list[SourceChunk] = []
    ids = payload.get("ids", []) or []
    docs = payload.get("documents", []) or []
    metas = payload.get("metadatas", []) or []

    for idx, text in enumerate(docs):
        metadata = dict(metas[idx] or {}) if idx < len(metas) else {}
        chunk_id = str(metadata.get("chunk_id") or (ids[idx] if idx < len(ids) else f"chunk_{idx}"))
        chunk = SourceChunk(chunk_id=chunk_id, text=text, metadata=metadata)
        if skip_noise and not is_probably_teaching_chunk(chunk):
            continue
        chunks.append(chunk)
        if limit is not None and len(chunks) >= limit:
            break

    return chunks


def load_chunks_from_json(path: str | Path, limit: int | None = None, skip_noise: bool = False) -> list[SourceChunk]:
    """Load chunks from a JSON/JSONL file for experimentation.

    Supported item fields: ``text``/``content``/``page_content`` and optional
    ``chunk_id``/``metadata``.
    """
    path = Path(path)
    if path.suffix.lower() == ".jsonl":
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("chunks", payload) if isinstance(payload, dict) else payload

    chunks: list[SourceChunk] = []
    for idx, item in enumerate(rows):
        metadata = dict(item.get("metadata", {}))
        chunk_id = str(item.get("chunk_id") or metadata.get("chunk_id") or f"json_chunk_{idx}")
        text = item.get("text") or item.get("content") or item.get("page_content") or ""
        chunk = SourceChunk(chunk_id=chunk_id, text=str(text), metadata=metadata)
        if skip_noise and not is_probably_teaching_chunk(chunk):
            continue
        chunks.append(chunk)
        if limit is not None and len(chunks) >= limit:
            break
    return chunks


def build_extraction_prompt(chunk: SourceChunk, max_chars: int = 2400) -> str:
    chapter = chunk.metadata.get("chapter") or chunk.metadata.get("chapter_no") or ""
    section = chunk.metadata.get("section") or chunk.metadata.get("section_no") or ""
    source = chunk.metadata.get("source") or ""
    text = _compact_text(chunk.text, max_chars=max_chars)

    return f"""
你是一个教育知识图谱抽取器。请从教材片段中抽取课程教学所需的轻量知识图谱。

目标不是抽取所有名词，而是抽取能服务个性化教学 RAG 的信息：核心概念、算法/方法、公式/指标、易混淆关系、前置关系、教材证据、以及可选的常见误解。

严格约束：
1. 只能使用以下节点类型：{', '.join(ALLOWED_NODE_TYPES)}。
2. 只能使用以下关系类型：{', '.join(ALLOWED_RELATION_TYPES)}。
3. pedagogical_type 只能是：{', '.join(ALLOWED_PEDAGOGICAL_TYPES)}。
4. 每个节点和关系必须能被当前 chunk 支持；没有证据就不要生成。
5. prerequisite_of 表示 source 是 target 的前置知识，例如 “训练集/测试集 prerequisite_of 交叉验证”。
6. confusable_with 只用于学生容易混淆的概念，例如 “PCA confusable_with KMeans”。
7. 只保留最重要的教学信息：nodes 最多 6 个，edges 最多 8 条，misconceptions 最多 3 条。
8. 输出必须是合法 JSON，不要 markdown，不要解释。

chunk 元信息：
- chunk_id: {chunk.chunk_id}
- source: {source}
- chapter: {chapter}
- section: {section}

教材片段：
{text}

请输出 JSON，格式如下：
{{
  "nodes": [
    {{
      "id": "stable_snake_case_or_readable_id",
      "name": "概念名",
      "type": "Concept",
      "aliases": ["别名"],
      "chapter": "{chapter}",
      "section": "{section}",
      "definition": "一句话定义，可为空",
      "evidence_chunk_ids": ["{chunk.chunk_id}"],
      "confidence": 0.0
    }}
  ],
  "edges": [
    {{
      "source": "source_node_id",
      "target": "target_node_id",
      "type": "related_to",
      "evidence_chunk_ids": ["{chunk.chunk_id}"],
      "confidence": 0.0,
      "rationale": "为什么有这个关系"
    }}
  ],
  "chunk_tags": [
    {{
      "chunk_id": "{chunk.chunk_id}",
      "concept_ids": ["node_id"],
      "pedagogical_type": "definition",
      "confidence": 0.0
    }}
  ],
  "misconceptions": [
    {{
      "id": "misconception_id",
      "concept_id": "concept_id",
      "wrong_belief": "学生可能的错误理解",
      "correction": "正确理解",
      "confusable_concept_ids": ["other_concept_id"],
      "evidence_chunk_ids": ["{chunk.chunk_id}"],
      "confidence": 0.0
    }}
  ]
}}
""".strip()


def get_chat_model(llm_timeout: float | None = None, max_output_tokens: int | None = None):
    """Return the configured chat model for offline extraction."""
    if config.USE_REMOTE_LLM:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=config.REMOTE_MODEL_NAME,
            api_key=config.API_KEY,
            base_url=config.BASE_URL,
            temperature=0.0,
            timeout=llm_timeout,
            max_retries=1,
            model_kwargs={"max_tokens": max_output_tokens} if max_output_tokens else {},
        )

    from langchain_ollama import ChatOllama

    sync_client_kwargs = {"timeout": llm_timeout} if llm_timeout is not None else {}
    return ChatOllama(
        model=config.MODEL_CHAT,
        base_url=config.BASE_URL_CHAT,
        temperature=0.0,
        sync_client_kwargs=sync_client_kwargs,
    )


def invoke_remote_direct(prompt: str, llm_timeout: float | None = None, max_output_tokens: int | None = None) -> str:
    if not config.USE_REMOTE_LLM:
        raise RuntimeError("--llm-provider direct requires USE_REMOTE_LLM=true")
    url = config.BASE_URL.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.API_KEY}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": config.REMOTE_MODEL_NAME,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }
    if max_output_tokens:
        payload["max_tokens"] = max_output_tokens
    response = requests.post(url, headers=headers, json=payload, timeout=llm_timeout)
    response.raise_for_status()
    data = response.json()
    return str(data["choices"][0]["message"].get("content") or "")


def _extract_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(raw[start : end + 1])
        raise


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def graph_from_payload(payload: dict[str, Any], course_name: str, fallback_chunk: SourceChunk) -> CourseGraph:
    nodes: list[CourseGraphNode] = []
    for item in payload.get("nodes", []) or []:
        if not isinstance(item, dict):
            continue
        node_type = str(item.get("type") or "Concept")
        if node_type not in ALLOWED_NODE_TYPES:
            node_type = "Concept"
        name = str(item.get("name") or item.get("id") or "").strip()
        if not name:
            continue
        node_id = str(item.get("id") or normalize_concept_id(name))
        evidence = item.get("evidence_chunk_ids") or [fallback_chunk.chunk_id]
        nodes.append(
            CourseGraphNode(
                id=normalize_concept_id(node_id),
                name=name,
                type=node_type,
                aliases=[str(v) for v in item.get("aliases", []) if str(v).strip()],
                chapter=str(item.get("chapter") or fallback_chunk.metadata.get("chapter") or fallback_chunk.metadata.get("chapter_no") or ""),
                section=str(item.get("section") or fallback_chunk.metadata.get("section") or fallback_chunk.metadata.get("section_no") or ""),
                definition=str(item.get("definition") or ""),
                evidence_chunk_ids=[str(v) for v in evidence if str(v).strip()],
                confidence=_coerce_float(item.get("confidence")),
            )
        )

    edges: list[CourseGraphEdge] = []
    for item in payload.get("edges", []) or []:
        if not isinstance(item, dict):
            continue
        rel_type = str(item.get("type") or "related_to")
        if rel_type not in ALLOWED_RELATION_TYPES:
            rel_type = "related_to"
        source = normalize_concept_id(str(item.get("source") or ""))
        target = normalize_concept_id(str(item.get("target") or ""))
        if not source or not target or source == "unknown" or target == "unknown":
            continue
        evidence = item.get("evidence_chunk_ids") or [fallback_chunk.chunk_id]
        edges.append(
            CourseGraphEdge(
                source=source,
                target=target,
                type=rel_type,
                evidence_chunk_ids=[str(v) for v in evidence if str(v).strip()],
                confidence=_coerce_float(item.get("confidence")),
                rationale=str(item.get("rationale") or ""),
            )
        )

    tags: list[ChunkConceptTag] = []
    for item in payload.get("chunk_tags", []) or []:
        if not isinstance(item, dict):
            continue
        pedagogical_type = str(item.get("pedagogical_type") or "other")
        if pedagogical_type not in ALLOWED_PEDAGOGICAL_TYPES:
            pedagogical_type = "other"
        concept_ids = [normalize_concept_id(str(v)) for v in item.get("concept_ids", []) if str(v).strip()]
        tags.append(
            ChunkConceptTag(
                chunk_id=str(item.get("chunk_id") or fallback_chunk.chunk_id),
                concept_ids=concept_ids,
                pedagogical_type=pedagogical_type,
                confidence=_coerce_float(item.get("confidence")),
            )
        )

    misconceptions: list[MisconceptionItem] = []
    for item in payload.get("misconceptions", []) or []:
        if not isinstance(item, dict):
            continue
        wrong = str(item.get("wrong_belief") or "").strip()
        correction = str(item.get("correction") or "").strip()
        concept_id = normalize_concept_id(str(item.get("concept_id") or ""))
        if not wrong or not correction or concept_id == "unknown":
            continue
        evidence = item.get("evidence_chunk_ids") or [fallback_chunk.chunk_id]
        item_id = str(item.get("id") or normalize_concept_id(f"{concept_id}_{wrong[:20]}"))
        misconceptions.append(
            MisconceptionItem(
                id=normalize_concept_id(item_id),
                concept_id=concept_id,
                wrong_belief=wrong,
                correction=correction,
                confusable_concept_ids=[normalize_concept_id(str(v)) for v in item.get("confusable_concept_ids", []) if str(v).strip()],
                evidence_chunk_ids=[str(v) for v in evidence if str(v).strip()],
                confidence=_coerce_float(item.get("confidence")),
            )
        )

    return CourseGraph(course_name=course_name, nodes=nodes, edges=edges, chunk_tags=tags, misconceptions=misconceptions)


def extract_with_prompt_backend(
    chunks: Iterable[SourceChunk],
    course_name: str,
    dry_run: bool = False,
    llm_timeout: float | None = None,
    max_chars: int = 1400,
    max_output_tokens: int | None = 900,
    llm_provider: str = "langchain",
) -> list[CourseGraph]:
    chunk_list = list(chunks)
    llm = None
    if not dry_run and llm_provider == "langchain":
        llm = get_chat_model(llm_timeout=llm_timeout, max_output_tokens=max_output_tokens)
    graphs: list[CourseGraph] = []

    for index, chunk in enumerate(chunk_list, start=1):
        prompt = build_extraction_prompt(chunk, max_chars=max_chars)
        if dry_run:
            print(f"\n===== DRY RUN PROMPT #{index} chunk={chunk.chunk_id} =====\n{prompt}\n")
            continue

        print(f"[course-graph] extracting chunk {index}/{len(chunk_list)}: {chunk.chunk_id}", flush=True)
        try:
            if llm_provider == "direct":
                content = invoke_remote_direct(
                    prompt,
                    llm_timeout=llm_timeout,
                    max_output_tokens=max_output_tokens,
                )
            else:
                response = llm.invoke(prompt)
                content = getattr(response, "content", str(response))
        except Exception as exc:
            print(f"[warn] LLM invocation failed for chunk {chunk.chunk_id}: {exc}", flush=True)
            continue
        try:
            payload = _extract_json_object(content)
        except Exception as exc:
            print(f"[warn] failed to parse LLM JSON for chunk {chunk.chunk_id}: {exc}")
            continue
        graphs.append(graph_from_payload(payload, course_name=course_name, fallback_chunk=chunk))

    return graphs


def extract_with_transformer_backend(
    chunks: Iterable[SourceChunk],
    course_name: str,
    llm_timeout: float | None = None,
    max_output_tokens: int | None = 900,
) -> list[CourseGraph]:
    """Use optional LangChain LLMGraphTransformer as a baseline extractor."""
    try:
        from langchain_experimental.graph_transformers import LLMGraphTransformer
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "langchain-experimental is required for --backend transformer. "
            "Install it with: pip install langchain-experimental"
        ) from exc

    llm = get_chat_model(llm_timeout=llm_timeout, max_output_tokens=max_output_tokens)
    education_instructions = (
        "Extract only teaching-relevant course knowledge. Ignore cover pages, "
        "publisher information, logos, QR codes, table-of-contents noise, names, "
        "and non-conceptual metadata. Prefer concepts, algorithms, methods, "
        "formulae, metrics, examples, prerequisite relations, and confusing pairs. "
        "Use prerequisite_of only when one concept is pedagogically required before "
        "another. Use confusable_with only when students may plausibly confuse two "
        "concepts. Do not invent relations without textual evidence."
    )
    transformer = LLMGraphTransformer(
        llm=llm,
        allowed_nodes=list(ALLOWED_NODE_TYPES),
        allowed_relationships=list(ALLOWED_RELATION_TYPES),
        strict_mode=True,
        additional_instructions=education_instructions,
    )

    documents = []
    chunk_by_id = {}
    for chunk in chunks:
        metadata = dict(chunk.metadata)
        metadata["chunk_id"] = chunk.chunk_id
        documents.append(Document(page_content=chunk.text, metadata=metadata))
        chunk_by_id[chunk.chunk_id] = chunk

    graph_documents = transformer.convert_to_graph_documents(documents)
    graphs: list[CourseGraph] = []

    for graph_doc, document in zip(graph_documents, documents):
        chunk_id = str(document.metadata.get("chunk_id") or "")
        fallback = chunk_by_id.get(chunk_id) or SourceChunk(chunk_id=chunk_id, text=document.page_content, metadata=document.metadata)
        nodes: list[CourseGraphNode] = []
        edges: list[CourseGraphEdge] = []

        for node in getattr(graph_doc, "nodes", []) or []:
            raw_id = str(getattr(node, "id", "") or getattr(node, "name", "") or "")
            if not raw_id:
                continue
            node_type = str(getattr(node, "type", "Concept") or "Concept")
            if node_type not in ALLOWED_NODE_TYPES:
                node_type = "Concept"
            nodes.append(
                CourseGraphNode(
                    id=normalize_concept_id(raw_id),
                    name=raw_id,
                    type=node_type,
                    chapter=str(fallback.metadata.get("chapter") or fallback.metadata.get("chapter_no") or ""),
                    section=str(fallback.metadata.get("section") or fallback.metadata.get("section_no") or ""),
                    evidence_chunk_ids=[fallback.chunk_id],
                    confidence=0.5,
                )
            )

        for rel in getattr(graph_doc, "relationships", []) or []:
            source = getattr(rel, "source", None)
            target = getattr(rel, "target", None)
            source_id = normalize_concept_id(str(getattr(source, "id", source) or ""))
            target_id = normalize_concept_id(str(getattr(target, "id", target) or ""))
            rel_type = str(getattr(rel, "type", "related_to") or "related_to").lower()
            rel_type = rel_type.replace(" ", "_").replace("-", "_")
            if rel_type not in ALLOWED_RELATION_TYPES:
                rel_type = "related_to"
            if source_id != "unknown" and target_id != "unknown":
                edges.append(
                    CourseGraphEdge(
                        source=source_id,
                        target=target_id,
                        type=rel_type,
                        evidence_chunk_ids=[fallback.chunk_id],
                        confidence=0.5,
                    )
                )

        tags = [
            ChunkConceptTag(
                chunk_id=fallback.chunk_id,
                concept_ids=[node.id for node in nodes],
                pedagogical_type="other",
                confidence=0.5,
            )
        ] if nodes else []
        graphs.append(CourseGraph(course_name=course_name, nodes=nodes, edges=edges, chunk_tags=tags))

    return graphs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an experimental course graph from course chunks.")
    parser.add_argument("--backend", choices=["prompt", "transformer"], default="prompt")
    parser.add_argument("--input-json", help="Optional JSON/JSONL chunks file. Defaults to Chroma collection.")
    parser.add_argument("--collection-name", default=None, help="Chroma collection name. Defaults to config.collection_name.")
    parser.add_argument("--limit", type=int, default=5, help="Number of chunks to process. Use small limits while testing.")
    parser.add_argument("--output", default="data/course_graph_v2.json")
    parser.add_argument("--course-name", default=config.COURSE_NAME)
    parser.add_argument("--llm-provider", choices=["langchain", "direct"], default="langchain", help="LLM call path for prompt backend.")
    parser.add_argument("--llm-timeout", type=float, default=60.0, help="Per-request LLM timeout in seconds.")
    parser.add_argument("--max-chars", type=int, default=1400, help="Maximum chunk characters sent to the prompt backend.")
    parser.add_argument("--max-output-tokens", type=int, default=900, help="Maximum LLM output tokens per chunk.")
    parser.add_argument("--no-skip-noise", action="store_true", help="Do not skip cover/TOC/noisy chunks before extraction.")
    parser.add_argument("--dry-run", action="store_true", help="Print prompts without calling the LLM. Only for prompt backend.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    skip_noise = not args.no_skip_noise
    if args.input_json:
        chunks = load_chunks_from_json(args.input_json, limit=args.limit, skip_noise=skip_noise)
    else:
        chunks = load_chunks_from_chroma(collection_name=args.collection_name, limit=args.limit, skip_noise=skip_noise)

    if not chunks:
        raise SystemExit("No chunks found for graph extraction.")

    print(f"[course-graph] backend={args.backend} chunks={len(chunks)} course={args.course_name}")

    if args.backend == "prompt":
        graphs = extract_with_prompt_backend(
            chunks,
            course_name=args.course_name,
            dry_run=args.dry_run,
            llm_timeout=args.llm_timeout,
            max_chars=args.max_chars,
            max_output_tokens=args.max_output_tokens,
            llm_provider=args.llm_provider,
        )
    else:
        if args.dry_run:
            raise SystemExit("--dry-run is only supported by --backend prompt")
        graphs = extract_with_transformer_backend(
            chunks,
            course_name=args.course_name,
            llm_timeout=args.llm_timeout,
            max_output_tokens=args.max_output_tokens,
        )

    if args.dry_run:
        return

    merged = merge_course_graphs(
        course_name=args.course_name,
        graphs=graphs,
        metadata={
            "generated_at": datetime.now().isoformat(),
            "backend": args.backend,
            "chunk_count": len(chunks),
            "collection_name": args.collection_name or config.collection_name,
        },
    )
    merged.save(args.output)
    print(
        f"[course-graph] saved {args.output}: "
        f"nodes={len(merged.nodes)} edges={len(merged.edges)} "
        f"chunk_tags={len(merged.chunk_tags)} misconceptions={len(merged.misconceptions)}"
    )


if __name__ == "__main__":
    main()
