import os

import litellm

litellm.api_key = os.environ.get("OPENROUTER_API_KEY", "")

_MODEL = "openrouter/google/gemini-2.0-flash-001"


def enhance_results(question: str, sql: str, rows: list[dict]) -> str:
    prompt = f"""You are Cynda, a business analytics assistant. You ran a SQL query to answer a user's question and now need to explain the results clearly.

Business question: {question}

Query results ({len(rows)} row(s)):
{rows}

Instructions:
- Answer the question directly and concisely in 1–3 sentences.
- Include specific numbers and values from the results.
- Do not mention SQL, tables, or technical details.
- Do not use markdown formatting.
- If results are empty or ambiguous, say so plainly.
"""
    response = litellm.completion(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
    )
    return response.choices[0].message.content.strip()


def answer_directly(question: str, history: list[dict] | None = None) -> str:
    messages = list(history) if history else []
    messages.append({"role": "user", "content": question})
    response = litellm.completion(model=_MODEL, messages=messages, temperature=0.7)
    return response.choices[0].message.content.strip()


def generate_title(question: str) -> str:
    """Generate a short conversation title from the user's first question."""
    try:
        response = litellm.completion(
            model=_MODEL,
            messages=[{
                "role": "user",
                "content": (
                    "Generate a concise 3-5 word title for a data conversation based on this question. "
                    "Return only the title, no punctuation at the end, no quotes.\n\n"
                    f"Question: {question}"
                ),
            }],
            temperature=0.3,
            max_tokens=20,
        )
        return response.choices[0].message.content.strip().strip('"\'').strip()[:80]
    except Exception:
        return question[:60]
