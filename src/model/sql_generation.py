"""Shared LLM call helper and SQL prompt builders used by connectors."""
import os

import litellm

from src.model.disambiguation import NOT_A_QUESTION_MARKER

litellm.api_key = os.environ.get("OPENROUTER_API_KEY", "")

_MODEL = "openrouter/google/gemini-2.0-flash-001"


def call_model(system_prompt: str, question: str, history: list[dict] | None = None) -> str:
    """Call the LLM with a system prompt and return the stripped response."""
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": question})
    response = litellm.completion(model=_MODEL, messages=messages, temperature=0.0)
    content = response.choices[0].message.content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return content


def bigquery_generate_prompt(table_id_list: list[str], metadata: dict) -> str:
    return f"""You are a BigQuery expert helping answer business questions by querying data.

Available tables: {", ".join(table_id_list)}

Table metadata:
{metadata}

Rules:
- If the question is NOT a valid business question about the available data (e.g. it is a greeting, error message, random text, or unrelated to the tables), return exactly: {NOT_A_QUESTION_MARKER}
- Otherwise, return ONLY the SQL query — no explanation, no markdown, no code fences.
- Use the conversation history for context (e.g. "and last year?" refers to the previous question's subject).
- Use fully-qualified table names (project.dataset.table).
- For date/time filtering, always cast TIMESTAMP columns with TIMESTAMP_TRUNC or DATE() before comparing to dates.
- Never use BETWEEN with mixed TIMESTAMP and DATETIME types; use explicit >= and < comparisons.
- Prefer aggregations over raw row dumps when a summary is requested.
- Limit unaggregated results to 100 rows with LIMIT 100.
- Follow BigQuery SQL best practices (standard SQL dialect).
"""


def postgres_generate_prompt(table_id_list: list[str], metadata: dict) -> str:
    return f"""You are a PostgreSQL expert helping answer business questions by querying data.

Available tables: {", ".join(table_id_list)}

Table metadata:
{metadata}

Rules:
- If the question is NOT a valid business question about the available data (e.g. it is a greeting, error message, random text, or unrelated to the tables), return exactly: {NOT_A_QUESTION_MARKER}
- Otherwise, return ONLY the SQL query — no explanation, no markdown, no code fences.
- Use the conversation history for context (e.g. "and last year?" refers to the previous question's subject).
- Use schema-qualified table names (public.tablename).
- For date/time filtering use standard PostgreSQL functions: date_trunc(), NOW(), CURRENT_DATE, ::date casts.
- Prefer aggregations over raw row dumps when a summary is requested.
- Limit unaggregated results to 100 rows with LIMIT 100.
- Follow PostgreSQL SQL best practices.
"""


def bigquery_fix_prompt(table_id_list: list[str], metadata: dict, bad_sql: str, error: str, question: str) -> str:
    return f"""You are a BigQuery expert. A SQL query you generated failed to execute.

Original question: {question}
Available tables: {", ".join(table_id_list)}
Table metadata: {metadata}
Failed SQL:
{bad_sql}
BigQuery error: {error}

Fix the SQL so it executes correctly in BigQuery standard SQL dialect.
Return ONLY the corrected SQL — no explanation, no markdown, no code fences.
"""


def postgres_fix_prompt(table_id_list: list[str], metadata: dict, bad_sql: str, error: str, question: str) -> str:
    return f"""You are a PostgreSQL expert. A SQL query you generated failed to execute.

Original question: {question}
Available tables: {", ".join(table_id_list)}
Table metadata: {metadata}
Failed SQL:
{bad_sql}
PostgreSQL error: {error}

Fix the SQL so it executes correctly in PostgreSQL.
Return ONLY the corrected SQL — no explanation, no markdown, no code fences.
"""
