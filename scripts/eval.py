"""
Offline evaluation script — imports pipeline functions directly, no HTTP.
Usage: python scripts/eval.py
Requires: MISTRAL_API_KEY in environment or .env, vector store already built.
"""

import os
import sys
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from dotenv import load_dotenv
from mistralai import Mistral

from src.ingestion.pipeline import load_bm25_index, load_vector_store
from src.retrieval.pipeline import (
    is_conversational,
    is_pii_query,
    merge_subquery_results,
    retrieve,
)
from src.generation.pipeline import detect_intent_and_decompose, run_generation_pipeline

load_dotenv()

VECTOR_STORE_DIR = Path("vector_store")

EVAL_CASES = [
    {
        "id": "Q1",
        "query": "What is the Coverage A dwelling limit for John Smith?",
        "expected_intent": "retrieval",
        "expected_source_contains": "declarations_john_smith",
        "expected_answer_contains": "500,000",
    },
    {
        "id": "Q2",
        "query": "What is the Business Income coverage limit for Acme Corporation?",
        "expected_intent": "retrieval",
        "expected_source_contains": "declarations_acme_corp",
        "expected_answer_contains": "750,000",
    },
    {
        "id": "Q3",
        "query": "What is the hurricane deductible structure for Florida properties?",
        "expected_intent": "retrieval",
        "expected_source_contains": "amendment_FL",
        "expected_answer_contains": None,
    },
    {
        "id": "Q4",
        "query": "What is the minimum cancellation notice period in California?",
        "expected_intent": "retrieval",
        "expected_source_contains": "amendment_CA",
        "expected_answer_contains": "20",
    },
    {
        "id": "Q5",
        "query": "Does endorsement NX-END-02 override Section 7.3?",
        "expected_intent": "retrieval",
        "expected_source_contains": "endorsement_02",
        "expected_answer_contains": None,
    },
    {
        "id": "Q6",
        "query": "Is water damage from frozen pipes covered if the dwelling was vacant for 65 days?",
        "expected_intent": "retrieval",
        "expected_source_contains": "base_policy_homeowners",
        "expected_answer_contains": None,
    },
    {
        "id": "Q7",
        "query": "Is sewer backup covered under the homeowners policy?",
        "expected_intent": "retrieval",
        "expected_source_contains": "endorsement_03",
        "expected_answer_contains": None,
    },
    {
        "id": "Q8",
        "query": "Hello, what can you help me with?",
        "expected_intent": "conversational",
        "expected_source_contains": None,
        "expected_answer_contains": None,
    },
    {
        "id": "Q9",
        "query": "My SSN is 123-45-6789, am I covered for flood damage?",
        "expected_intent": "pii_sensitive",
        "expected_source_contains": None,
        "expected_answer_contains": None,
    },
    {
        "id": "Q10",
        "query": "What is the coverage for cyber attacks on smart home devices?",
        "expected_intent": "retrieval",
        "expected_source_contains": None,
        "expected_answer_contains": "insufficient",
    },
]

_REFUSAL_INTENTS = {"pii_sensitive", "legal_advice", "out_of_scope"}


def run_case(case: dict, embeddings: np.ndarray, metadata: list, bm25_index: dict, client: Mistral) -> dict:
    q = case["query"]

    # Guard checks (no API calls)
    if is_pii_query(q):
        return {
            "intent": "pii_sensitive",
            "answer": "This query contains sensitive personal information and cannot be processed.",
            "sources": [],
        }
    if is_conversational(q):
        return {
            "intent": "conversational",
            "answer": "I am an insurance policy assistant. Ask me about coverage, exclusions, deductibles, or policy terms.",
            "sources": [],
        }

    analysis = detect_intent_and_decompose(q)
    intent = analysis.get("intent", "retrieval")
    sub_queries = analysis.get("sub_queries", [{"query": q, "doc_type": None}])
    answer_template = analysis.get("answer_template", "general")
    refusal_reason = analysis.get("refusal_reason")

    if intent in _REFUSAL_INTENTS:
        return {"intent": intent, "answer": refusal_reason or "", "sources": []}

    subquery_results = []
    for sub in sub_queries:
        embed_response = client.embeddings.create(
            model="mistral-embed",
            inputs=[sub["query"]],
        )
        query_embedding = np.array(embed_response.data[0].embedding, dtype=np.float32)
        result = retrieve(
            query_embedding=query_embedding,
            query_text=sub["query"],
            embeddings_matrix=embeddings,
            metadata=metadata,
            bm25_index=bm25_index,
            doc_type_filter=sub.get("doc_type"),
        )
        subquery_results.append(result)

    merged = merge_subquery_results(subquery_results)
    generation = run_generation_pipeline(
        query=q,
        chunks=merged["chunks"],
        answer_template=answer_template,
        sufficient_evidence=merged["sufficient_evidence"],
    )

    sources = [s["source"] for s in generation["sources"]]
    return {"intent": intent, "answer": generation["answer"], "sources": sources}


def evaluate_case(case: dict, result: dict) -> bool:
    intent = result["intent"]
    answer = (result["answer"] or "").lower()
    sources = result["sources"]

    exp_intent = case["expected_intent"]
    exp_source = case["expected_source_contains"]
    exp_answer = case["expected_answer_contains"]

    # Guard cases: only intent needs to match
    if exp_intent in ("conversational", "pii_sensitive"):
        return intent == exp_intent

    # Q10 special rule: pass if answer contains "insufficient" OR sources empty
    if case["id"] == "Q10":
        return ("insufficient" in answer) or (len(sources) == 0)

    passed = True
    if exp_source is not None:
        passed = passed and any(exp_source in s for s in sources)
    if exp_answer is not None:
        passed = passed and (exp_answer.lower() in answer)
    return passed


def main():
    if not (VECTOR_STORE_DIR / "embeddings.npy").exists():
        print("ERROR: vector store not found. Run POST /ingest first.")
        sys.exit(1)

    print("Loading vector store and BM25 index...")
    embeddings, metadata = load_vector_store(VECTOR_STORE_DIR)
    bm25_index = load_bm25_index(VECTOR_STORE_DIR)
    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    print(f"Loaded {len(metadata)} chunks.\n")

    passed_count = 0

    for case in EVAL_CASES:
        print(f"{'─' * 70}")
        print(f"[{case['id']}] {case['query']}")
        print(f"  Expected intent : {case['expected_intent']}")

        try:
            result = run_case(case, embeddings, metadata, bm25_index, client)
        except Exception as e:
            print(f"  ERROR: {e}")
            print(f"  Result         : FAIL")
            continue

        intent = result["intent"]
        answer_snippet = (result["answer"] or "")[:120].replace("\n", " ")
        source_names = [Path(s).stem for s in result["sources"]] if result["sources"] else []

        passed = evaluate_case(case, result)
        passed_count += passed
        label = "PASS" if passed else "FAIL"

        print(f"  Actual intent  : {intent}")
        print(f"  Answer (120c)  : {answer_snippet}")
        print(f"  Sources        : {source_names if source_names else '(none)'}")
        print(f"  Result         : {label}")

    print(f"\n{'=' * 70}")
    print(f"SUMMARY: {passed_count}/{len(EVAL_CASES)} passed")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
