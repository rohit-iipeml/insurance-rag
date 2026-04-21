import json
import os
import re

from dotenv import load_dotenv
from mistralai import Mistral

load_dotenv()

GENERATION_MODEL          = "mistral-small-latest"
INSUFFICIENT_EVIDENCE_MSG = (
    "Insufficient evidence in the knowledge base to answer this query. "
    "Please consult the original policy documents or a licensed insurance professional."
)

_INTENT_SYSTEM_PROMPT = """\
You are an insurance RAG query analyzer. Given a user query about insurance policies, \
return a JSON object with exactly these fields:
- intent: classify as one of: retrieval, conversational, pii_sensitive, legal_advice, out_of_scope
- answer_template: if intent is retrieval, classify output format as: \
coverage_determination, limit_lookup, override_conflict, definition, general. Otherwise null.
- sub_queries: if intent is retrieval, decompose the query into 2-4 targeted sub-queries. \
Each sub-query should have 'query' (string) and 'doc_type' \
(one of: base_policy, endorsement, amendment, declarations, or null if any doc type is acceptable). \
Otherwise empty list.
- refusal_reason: if intent is pii_sensitive, legal_advice, or out_of_scope, provide a brief \
user-facing refusal message. Otherwise null.

Return only valid JSON. No explanation, no markdown."""

_TEMPLATE_INSTRUCTIONS: dict[str, str] = {
    "coverage_determination": (
        "Start your answer with 'COVERED: Yes', 'COVERED: No', or 'COVERED: Conditional'. "
        "Then explain the applicable conditions and any exclusions that affect coverage."
    ),
    "limit_lookup": (
        "State the specific limit or deductible value at the start of your answer. "
        "Then provide the surrounding policy context."
    ),
    "override_conflict": (
        "Structure your answer in three labelled parts: "
        "BASE RULE (from the base policy), MODIFIER (from the endorsement or amendment), "
        "and NET EFFECT (the resulting rule as it applies to the insured)."
    ),
    "definition": (
        "Quote the definition directly from the policy verbatim, then explain it in plain language."
    ),
    "general": (
        "Answer in clear prose with inline citations after each factual claim."
    ),
}

_GENERATION_SYSTEM_PROMPT = """\
You are an insurance policy analyst assistant. Answer questions using ONLY the context \
provided below. Never use knowledge outside the provided context.

Citation format: after every factual claim, add [SOURCE: <chunk_id>, page <N>, section <title>] where chunk_id is the exact chunk_id value shown in the context header, not the filename. For example: [SOURCE: base_policy_homeowners_chunk_20, page 3, section 7.3 Vacancy].

If the context does not contain sufficient information to answer the question, say so explicitly \
rather than guessing.

{template_instruction}"""


def detect_intent_and_decompose(query: str) -> dict:
    # Single API call handles intent detection AND query decomposition together —
    # folding both into one call saves 300-500ms latency vs two sequential calls.
    # Sub-queries with doc_type targets enable cross-document retrieval by routing
    # each sub-query to the most relevant document category.
    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    try:
        response = client.chat.complete(
            model=GENERATION_MODEL,
            messages=[
                {"role": "system", "content": _INTENT_SYSTEM_PROMPT},
                {"role": "user",   "content": query},
            ],
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)
    except Exception:
        return {
            "intent":          "retrieval",
            "answer_template": "general",
            "sub_queries":     [{"query": query, "doc_type": None}],
            "refusal_reason":  None,
        }


def build_generation_prompt(
    query: str,
    chunks: list[dict],
    answer_template: str,
) -> tuple[str, str]:
    # Template-specific prompts shape the answer structure for the claims adjuster's
    # workflow — a coverage determination needs a clear yes/no/conditional at the top,
    # not a paragraph of prose. Citation format [SOURCE: ...] is parsed post-generation
    # to verify against retrieved chunk IDs.
    template_instruction = _TEMPLATE_INSTRUCTIONS.get(
        answer_template, _TEMPLATE_INSTRUCTIONS["general"]
    )
    system_prompt = _GENERATION_SYSTEM_PROMPT.format(
        template_instruction=template_instruction
    )

    context_lines: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        meta = chunk.get("metadata", chunk)
        context_lines.append(
            f"[{i}] chunk_id: {meta.get('chunk_id', 'unknown')} | "
            f"source: {meta.get('source', 'unknown')} | "
            f"page: {meta.get('page_start', '?')} | "
            f"section: {meta.get('section_title', 'unknown')}\n"
            f"{chunk.get('text', meta.get('text', ''))}"
        )

    user_prompt = "\n\n---\n\n".join(context_lines) + f"\n\n---\n\nQuestion: {query}"
    return system_prompt, user_prompt


def build_generation_messages(
    query: str,
    chunks: list[dict],
    answer_template: str,
) -> list[dict]:
    """Returns the messages list for the generation call.
    Used by the streaming endpoint so it can construct the prompt without
    calling generate_answer (which blocks until the full response arrives)."""
    system_prompt, user_prompt = build_generation_prompt(query, chunks, answer_template)
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_prompt},
    ]


def generate_answer(query: str, chunks: list[dict], answer_template: str) -> str:
    # Raw answer returned here — citation verification happens in a separate
    # step so the two concerns stay cleanly separated.
    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    system_prompt, user_prompt = build_generation_prompt(query, chunks, answer_template)
    response = client.chat.complete(
        model=GENERATION_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
    )
    return response.choices[0].message.content


def verify_citations(answer: str, retrieved_chunks: list[dict]) -> dict:
    # Citation verification catches fabricated source references — the most
    # dangerous hallucination in insurance Q&A where a wrong citation could
    # lead an adjuster to a non-existent policy clause. Verification happens
    # in Python, not via LLM prompt, so it is deterministic and cannot be
    # overridden by prompt injection.
    cited_ids = re.findall(r"\[SOURCE:\s*([^,\]]+)", answer)
    cited_ids = [cid.strip() for cid in cited_ids]

    valid_ids = {
        c.get("chunk_id") or c.get("metadata", {}).get("chunk_id")
        for c in retrieved_chunks
    }

    verified:     list[str] = []
    hallucinated: list[str] = []
    for cid in dict.fromkeys(cited_ids):   # deduplicate while preserving order
        (verified if cid in valid_ids else hallucinated).append(cid)

    return {
        "verified_citations":    verified,
        "hallucinated_citations": hallucinated,
        "is_clean":              len(hallucinated) == 0,
    }


def format_sources(chunks: list[dict]) -> list[dict]:
    seen: set[str] = set()
    sources: list[dict] = []
    for chunk in chunks:
        meta  = chunk.get("metadata", chunk)
        cid   = meta.get("chunk_id", "unknown")
        if cid in seen:
            continue
        seen.add(cid)
        sources.append({
            "chunk_id": cid,
            "source":   meta.get("source",        "unknown"),
            "page":     meta.get("page_start",    0),
            "section":  meta.get("section_title", "unknown"),
            "doc_type": meta.get("doc_type",      "unknown"),
        })
    return sources


def run_generation_pipeline(
    query: str,
    chunks: list[dict],
    answer_template: str,
    sufficient_evidence: bool,
) -> dict:
    # Orchestrates generation → verification → formatting. Keeping these as
    # separate functions means each can be tested independently and swapped
    # without touching the others.
    if not sufficient_evidence:
        return {
            "answer":             INSUFFICIENT_EVIDENCE_MSG,
            "sources":            [],
            "citation_check":     {"verified_citations": [], "hallucinated_citations": [], "is_clean": True},
            "answer_template":    answer_template,
            "sufficient_evidence": False,
        }

    answer          = generate_answer(query, chunks, answer_template)
    citation_check  = verify_citations(answer, chunks)
    sources         = format_sources(chunks)

    return {
        "answer":             answer,
        "sources":            sources,
        "citation_check":     citation_check,
        "answer_template":    answer_template,
        "sufficient_evidence": True,
    }
