import json
import re

import httpx
import numpy as np

from src.ingestion.pipeline import bm25_plus_score

SIMILARITY_THRESHOLD = 0.50  # minimum cosine similarity for top chunk — calibrated for mistral-embed on legal text
BM25_WEIGHT          = 1.2   # BM25 weighted slightly higher than semantic for insurance legal text
RRF_K                = 60    # standard RRF constant from literature
TOP_K_PER_METHOD     = 10    # candidates from each retrieval method before fusion
TOP_K_FINAL          = 8     # final chunks after diversity cap
MAX_PER_DOC_TYPE     = 3     # diversity cap — prevents semantic collapse into one document type

_PII_PATTERNS = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),                              # SSN
    re.compile(r"\b\d{3}[\s.\-]\d{3}[\s.\-]\d{4}\b"),                  # phone
    re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b"),  # email
    re.compile(r"\b\d{4}[\s\-]\d{4}[\s\-]\d{4}[\s\-]\d{4}\b"),        # credit card
]

_CONVERSATIONAL_EXACT = {
    "hello", "hi", "hey", "good morning", "good afternoon", "good evening",
    "thanks", "thank you", "bye", "goodbye",
}

_CONVERSATIONAL_PREFIXES = (
    "what can you do", "how do you work", "who are you", "what are you",
)


def is_pii_query(query: str) -> bool:
    # PII is checked before any API call — sensitive data must never reach
    # a third-party LLM. Regex is deterministic unlike LLM-based detection.
    return any(p.search(query) for p in _PII_PATTERNS)


def is_conversational(query: str) -> bool:
    # Conversational queries are caught before retrieval to avoid burning
    # embedding API calls on inputs that need no document context.
    normalised = query.lower().strip()
    if normalised in _CONVERSATIONAL_EXACT:
        return True
    return any(normalised.startswith(prefix) for prefix in _CONVERSATIONAL_PREFIXES)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    # Implemented from scratch — no scipy or sklearn. Cosine similarity
    # measures angle between vectors, not magnitude, which is correct for
    # comparing embeddings of different-length text chunks.
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def semantic_search(
    query_embedding: np.ndarray,
    embeddings_matrix: np.ndarray,
    metadata: list[dict],
    top_k: int = TOP_K_PER_METHOD,
    doc_type_filter: str | None = None,
) -> list[dict]:
    # Exact cosine search over all chunks — O(N) but fast at this scale.
    # At >100k chunks we would switch to approximate nearest neighbour (HNSW).
    # doc_type_filter lets sub-queries target specific document categories,
    # which is critical for cross-document reasoning in insurance.
    scores: list[tuple[int, float]] = []
    for i, row in enumerate(embeddings_matrix):
        if doc_type_filter and metadata[i].get("doc_type") != doc_type_filter:
            continue
        scores.append((i, cosine_similarity(query_embedding, row)))

    scores.sort(key=lambda x: x[1], reverse=True)
    return [
        {
            "chunk_index": i,
            "chunk_id":    metadata[i]["chunk_id"],
            "score":       score,
            "method":      "semantic",
            "metadata":    metadata[i],
        }
        for i, score in scores[:top_k]
    ]


def keyword_search(
    query: str,
    bm25_index: dict,
    metadata: list[dict],
    top_k: int = TOP_K_PER_METHOD,
    doc_type_filter: str | None = None,
) -> list[dict]:
    # BM25+ excels at exact legal identifiers — 'Section 7.3', 'NX-END-02' —
    # that semantic search blurs because embeddings treat similar tokens as close.
    raw = bm25_plus_score(query, bm25_index)
    results: list[dict] = []
    for chunk_index, score in raw:
        if doc_type_filter and metadata[chunk_index].get("doc_type") != doc_type_filter:
            continue
        results.append({
            "chunk_index": chunk_index,
            "chunk_id":    metadata[chunk_index]["chunk_id"],
            "score":       score,
            "method":      "bm25",
            "metadata":    metadata[chunk_index],
        })
        if len(results) == top_k:
            break
    return results


def reciprocal_rank_fusion(
    result_lists: list[list[dict]],
    bm25_weight: float = BM25_WEIGHT,
    k: int = RRF_K,
) -> list[dict]:
    # RRF combines rankings without needing score normalisation — adding raw
    # BM25 scores to cosine similarities would be meaningless. k=60 is the
    # standard constant; it dampens the advantage of top-1 vs top-2 rankings.
    # BM25 gets weight 1.2 over semantic 1.0 because insurance queries
    # frequently contain exact identifiers that BM25 handles more reliably.
    fused: dict[int, dict] = {}

    for result_list in result_lists:
        for rank, result in enumerate(result_list):
            idx    = result["chunk_index"]
            weight = bm25_weight if result["method"] == "bm25" else 1.0
            contribution = weight / (k + rank)

            if idx not in fused:
                fused[idx] = {
                    "chunk_index":    idx,
                    "chunk_id":       result["chunk_id"],
                    "fused_score":    0.0,
                    "methods":        [],
                    "metadata":       result["metadata"],
                    "semantic_score": None,
                    "bm25_score":     None,
                }

            fused[idx]["fused_score"] += contribution
            if result["method"] not in fused[idx]["methods"]:
                fused[idx]["methods"].append(result["method"])

            if result["method"] == "semantic":
                fused[idx]["semantic_score"] = result["score"]
            elif result["method"] == "bm25":
                fused[idx]["bm25_score"] = result["score"]

    return sorted(fused.values(), key=lambda x: x["fused_score"], reverse=True)


def apply_diversity_cap(
    fused_results: list[dict],
    max_per_doc_type: int = MAX_PER_DOC_TYPE,
    top_k: int = TOP_K_FINAL,
) -> list[dict]:
    # Without a diversity cap, semantic search collapses into the longest
    # document type (base policies). The cap ensures endorsements and
    # declarations pages are represented even if base policy chunks score
    # higher — critical for cross-document insurance reasoning.
    counts: dict[str, int] = {}
    selected: list[dict] = []

    for result in fused_results:
        doc_type = result["metadata"].get("doc_type", "unknown")
        if counts.get(doc_type, 0) < max_per_doc_type:
            selected.append(result)
            counts[doc_type] = counts.get(doc_type, 0) + 1
        if len(selected) == top_k:
            break

    return selected


def check_sufficient_evidence(results: list[dict]) -> bool:
    # Threshold on semantic score not fused score — fused scores are not
    # normalised and not comparable across queries. 0.50 calibrated for
    # mistral-embed on insurance legal text — relevant chunks typically
    # score 0.55-0.75, irrelevant ones below 0.40.
    if not results:
        return False

    top_sem = results[0].get("semantic_score")
    if top_sem is not None:
        return top_sem >= SIMILARITY_THRESHOLD

    # Top result retrieved only by BM25 — check second result for a semantic score.
    if len(results) > 1:
        second_sem = results[1].get("semantic_score")
        if second_sem is not None:
            return second_sem >= SIMILARITY_THRESHOLD

    # Only BM25 evidence available — exact match is considered sufficient.
    return True


def retrieve(
    query_embedding: np.ndarray,
    query_text: str,
    embeddings_matrix: np.ndarray,
    metadata: list[dict],
    bm25_index: dict,
    doc_type_filter: str | None = None,
) -> dict:
    # Single sub-query retrieval — called once per decomposed sub-query.
    # Results from multiple sub-queries are merged upstream by the caller.
    semantic_results = semantic_search(
        query_embedding, embeddings_matrix, metadata,
        doc_type_filter=doc_type_filter,
    )
    keyword_results = keyword_search(
        query_text, bm25_index, metadata,
        doc_type_filter=doc_type_filter,
    )
    fused   = reciprocal_rank_fusion([semantic_results, keyword_results])
    capped  = apply_diversity_cap(fused)
    sufficient = check_sufficient_evidence(capped)

    top_semantic = capped[0].get("semantic_score") if capped else None

    return {
        "chunks":             capped,
        "sufficient_evidence": sufficient,
        "top_semantic_score": top_semantic,
    }


def merge_subquery_results(subquery_results: list[dict]) -> dict:
    # Sub-query results are merged here so the generator sees a unified
    # context window. Deduplication prevents the same chunk appearing twice
    # if multiple sub-queries retrieve it.
    seen: dict[str, dict] = {}
    for result in subquery_results:
        for chunk in result["chunks"]:
            cid = chunk["chunk_id"]
            if cid not in seen or chunk["fused_score"] > seen[cid]["fused_score"]:
                seen[cid] = chunk

    merged_sorted = sorted(seen.values(), key=lambda x: x["fused_score"], reverse=True)
    capped        = apply_diversity_cap(merged_sorted)
    sufficient    = any(r["sufficient_evidence"] for r in subquery_results)
    top_semantic  = capped[0].get("semantic_score") if capped else None

    return {
        "chunks":             capped,
        "sufficient_evidence": sufficient,
        "top_semantic_score": top_semantic,
    }


async def rerank_chunks(query: str, chunks: list[dict], api_key: str) -> list[dict]:
    if not chunks:
        return chunks
    try:
        chunk_lines = []
        for chunk in chunks:
            text = chunk.get("metadata", {}).get("text", "")[:600]
            chunk_lines.append(f"chunk_id: {chunk['chunk_id']}\n{text}")

        chunks_text = "\n\n".join(chunk_lines)
        prompt = (
            f"You are a relevance ranker for insurance policy documents. "
            f"Given a query and a list of document chunks, return a json object "
            f"with a single key 'ranked_ids' containing an array of chunk_ids ordered "
            f"from most to least relevant to the query. Include every chunk_id exactly once.\n\n"
            f"Query: {query}\n\nChunks:\n{chunks_text}"
        )

        payload = {
            "model": "mistral-small-latest",
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        }

        async with httpx.AsyncClient(timeout=30.0) as http:
            response = await http.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()

        content = response.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)

        if isinstance(parsed, list):
            ranked_ids = parsed
        else:
            ranked_ids = next(
                (v for v in parsed.values() if isinstance(v, list)),
                None,
            )
            if ranked_ids is None:
                return chunks

        if isinstance(ranked_ids, str):
            ranked_ids = json.loads(ranked_ids)

        id_to_chunk = {c["chunk_id"]: c for c in chunks}
        reranked = [id_to_chunk[cid] for cid in ranked_ids if cid in id_to_chunk]
        seen_ids = set(ranked_ids)
        reranked += [c for c in chunks if c["chunk_id"] not in seen_ids]

        # print("[RERANK] original order:", [c["chunk_id"] for c in chunks])
        # print("[RERANK] reranked order:", [c["chunk_id"] for c in reranked])

        return reranked

    except Exception:
        return chunks
