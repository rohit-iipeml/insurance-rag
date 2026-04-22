import json
import os
import re
import time

from dotenv import load_dotenv
from mistralai import Mistral

load_dotenv()

GENERATION_MODEL          = "mistral-large-latest"
INSUFFICIENT_EVIDENCE_MSG = (
    "Insufficient evidence in the knowledge base to answer this query. "
    "Please consult the original policy documents or a licensed insurance professional."
)

_INTENT_SYSTEM_PROMPT = """\
You are an insurance RAG query analyzer. Given a user query about insurance policies, \
return a JSON object with exactly these fields:
- intent: classify as one of: retrieval, conversational, pii_sensitive, legal_advice, out_of_scope
- IMPORTANT: Named individuals in insurance policy documents (e.g. "John Smith", "Jane Doe", "Acme Corporation") are policy document identifiers, NOT personal PII. Queries asking about coverage limits, deductibles, or policy terms for named insureds in the knowledge base should be classified as: intent=retrieval, NOT pii_sensitive.
- Only classify as pii_sensitive if the query contains actual sensitive data formats: SSN (###-##-####), credit card numbers, bank account numbers, or medical record numbers.
- answer_template: if intent is retrieval, classify output format as one of:\n  \
- coverage_determination: ONLY for yes/no/conditional coverage questions \
(e.g. "is X covered?", "will I get a claim for Y?")\n  \
- limit_lookup: for questions asking for a specific dollar amount, limit, deductible, or premium value\n  \
- override_conflict: for questions about whether one document overrides, modifies, or conflicts with another\n  \
- definition: for questions asking what a term means\n  \
- general: for all other retrieval questions including multi-part or ambiguous queries\n  \
Never use coverage_determination for factual lookups of dollar amounts or deductible values.\n  \
Otherwise null.
- sub_queries: if intent is retrieval, decompose the query into 2-4 targeted sub-queries. \
Each sub-query should have 'query' (string) and 'doc_type' \
(one of: base_policy, endorsement, amendment, declarations, or null if any doc type is acceptable). \
- IMPORTANT: If the query mentions a specific state, jurisdiction, or location (e.g. Florida, Texas, California, NY), always include at least one sub-query with doc_type set to 'amendment' targeting that state's specific rules or modifications. \
Otherwise empty list.
- refusal_reason: if intent is pii_sensitive, legal_advice, or out_of_scope, provide a brief \
user-facing refusal message. Otherwise null.

Return only valid JSON. No explanation, no markdown."""

_TEMPLATE_INSTRUCTIONS: dict[str, str] = {
    "coverage_determination": (
        "Start your answer with exactly one of: 'COVERED: Yes', 'COVERED: No', or 'COVERED: Conditional'. "
        "After the verdict, output a blank line, then begin your explanation on a new line. "
        "Format strictly as:\nCOVERED: Yes/No/Conditional\n\n[explanation text]\n\n"
        "Do not run the verdict and explanation together on the same line."
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
You are a knowledgeable insurance policy analyst assistant helping insurance agents \
quickly understand policy coverage, terms, and conditions.

Answer questions using ONLY the context provided below. Never use knowledge outside \
the provided context. Write in clear, professional prose as a senior insurance analyst \
would explain to a colleague — complete sentences, full explanations, no truncation.

Answer length: provide thorough answers of at least 3-4 complete sentences. \
If the question involves coverage determination, explain the reasoning fully, \
not just the verdict. If the question involves a dollar amount, state it clearly \
then explain what it means in context.

Citation format: the context chunks below are numbered [1], [2], [3] etc. \
After every factual claim, cite the chunk number inline as [1] or [2] etc. \
Use only the numbers corresponding to chunks that actually support the claim. \
Do not use chunk_id strings. Do not use [SOURCE: ...] format.

Always start your answer with a capital letter. Never start mid-sentence. \
Never start with a citation number like [1] or [2] — always start with a word.

If the context does not contain sufficient information to answer the question, \
say so explicitly in a complete sentence rather than guessing.

{template_instruction}"""


def _mistral_with_retry(fn, retries: int = 3, base_delay: float = 15.0):
    """Retries a Mistral API call on 429 rate limit errors."""
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            if "429" in str(e) or "rate" in str(e).lower() or "capacity" in str(e).lower():
                if attempt < retries - 1:
                    wait = base_delay * (attempt + 1)
                    print(f"[RETRY] Rate limited, waiting {wait}s (attempt {attempt+1}/{retries})")
                    time.sleep(wait)
                    continue
            raise
    raise RuntimeError("Max retries exceeded on Mistral API call")


def detect_intent_and_decompose(query: str) -> dict:
    # Single API call handles intent detection AND query decomposition together —
    # folding both into one call saves 300-500ms latency vs two sequential calls.
    # Sub-queries with doc_type targets enable cross-document retrieval by routing
    # each sub-query to the most relevant document category.
    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    try:
        response = _mistral_with_retry(
            lambda: client.chat.complete(
                model=GENERATION_MODEL,
                messages=[
                    {"role": "system", "content": _INTENT_SYSTEM_PROMPT},
                    {"role": "user",   "content": query},
                ],
                response_format={"type": "json_object"},
            )
        )
        return json.loads(response.choices[0].message.content)
    except Exception:
        return {
            "intent":          "retrieval",
            "answer_template": "general",
            "sub_queries":     [{"query": query, "doc_type": None}],
            "refusal_reason":  None,
        }


_REWRITE_SYSTEM_PROMPT = """\
You are a query rewriter for an insurance policy RAG system.
Given a conversation history and a follow-up question, rewrite the follow-up question \
into a fully self-contained standalone question that includes all necessary context \
from the conversation history.

Rules:
- If the question is already self-contained, return it unchanged
- If the question refers to "it", "this", "that", "the policy", "the same", etc., \
replace with the specific subject from history
- Never add information not present in the history or question
- Return only the rewritten question, nothing else, no explanation
- Preserve any specific identifiers from the history such as section numbers, endorsement codes, dollar amounts, and named policy forms verbatim in the rewritten question"""


def rewrite_query_with_history(query: str, chat_history: list[dict]) -> str:
    """Rewrites a follow-up query into a standalone question using chat history.
    Returns the original query unchanged if history is empty or rewriting fails."""
    if not chat_history:
        return query

    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    try:
        history_text = "\n".join(
            f"{m['role'].upper()}: {m['content'][:800]}"
            for m in chat_history[-4:]  # last 2 exchanges only
        )
        response = _mistral_with_retry(
            lambda: client.chat.complete(
                model="mistral-small-latest",
                messages=[
                    {"role": "system", "content": _REWRITE_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Conversation history:\n{history_text}\n\nFollow-up question: {query}\n\nRewritten standalone question:"},
                ],
            )
        )
        rewritten = response.choices[0].message.content.strip()
        return rewritten if rewritten else query
    except Exception:
        return query


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
            f"[{i}] chunk_id: {meta.get('chunk_id', 'unknown')}\n"
            f"source: {meta.get('source', 'unknown')}\n"
            f"page: {meta.get('page_start', '?')}\n"
            f"section: {meta.get('section_title', 'unknown')}\n"
            f"{chunk.get('text', meta.get('text', ''))}"
        )

    user_prompt = "\n\n---\n\n".join(context_lines) + f"\n\n---\n\nQuestion: {query}"
    return system_prompt, user_prompt


def build_generation_messages(
    query: str,
    chunks: list[dict],
    answer_template: str,
    chat_history: list[dict] | None = None,
) -> list[dict]:
    """Returns the messages list for the generation call.
    Used by the streaming endpoint so it can construct the prompt without
    calling generate_answer (which blocks until the full response arrives)."""
    system_prompt, user_prompt = build_generation_prompt(query, chunks, answer_template)
    messages = [{"role": "system", "content": system_prompt}]
    if chat_history:
        messages.extend(chat_history)
    messages.append({"role": "user", "content": user_prompt})
    return messages


def generate_answer(query: str, chunks: list[dict], answer_template: str, chat_history: list[dict] | None = None) -> str:
    # Raw answer returned here — citation verification happens in a separate
    # step so the two concerns stay cleanly separated.
    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    messages = build_generation_messages(query, chunks, answer_template, chat_history)
    response = client.chat.complete(
        model=GENERATION_MODEL,
        messages=messages,
    )
    return response.choices[0].message.content


def verify_citations(answer: str, retrieved_chunks: list[dict]) -> dict:
    # Citation verification catches fabricated source references — the most
    # dangerous hallucination in insurance Q&A where a wrong citation could
    # lead an adjuster to a non-existent policy clause. Verification happens
    # in Python, not via LLM prompt, so it is deterministic and cannot be
    # overridden by prompt injection.
    cited_nums = re.findall(r"\[(\d+)\]", answer)
    cited_nums = [n for n in dict.fromkeys(cited_nums)]  # deduplicate, preserve order

    valid_range = set(str(i) for i in range(1, len(retrieved_chunks) + 1))

    verified:     list[str] = []
    hallucinated: list[str] = []
    for n in cited_nums:
        (verified if n in valid_range else hallucinated).append(n)

    return {
        "verified_citations":    verified,
        "hallucinated_citations": hallucinated,
        "is_clean":              len(hallucinated) == 0,
    }


def format_sources(chunks: list[dict]) -> list[dict]:
    seen_chunk_ids: set[str] = set()
    seen_sources: set[str] = set()
    sources: list[dict] = []
    for chunk in chunks:
        meta = chunk.get("metadata", chunk)
        cid = meta.get("chunk_id", "unknown")
        source = meta.get("source", "unknown")
        if cid in seen_chunk_ids:
            continue
        seen_chunk_ids.add(cid)
        # Also deduplicate by source filename — same file appearing
        # twice with different chunk_ids adds noise without value
        if source in seen_sources:
            continue
        seen_sources.add(source)
        sources.append({
            "chunk_id": cid,
            "source":   source,
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
    chat_history: list[dict] | None = None,
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

    answer          = generate_answer(query, chunks, answer_template, chat_history)
    citation_check  = verify_citations(answer, chunks)
    sources         = format_sources(chunks)

    return {
        "answer":             answer,
        "sources":            sources,
        "citation_check":     citation_check,
        "answer_template":    answer_template,
        "sufficient_evidence": True,
    }
