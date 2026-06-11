# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

Install dependencies:
```bash
pip install -r requirements.txt
```

BigQuery authentication uses Application Default Credentials (ADC). Run `gcloud auth application-default login` before executing locally (service account mode).

## Running

Manual test (edit hardcoded values in `main()` to change table/question):
```bash
python src/tools.py
```

API server locally (Slack + demo endpoint):
```bash
uvicorn api.index:app --host 0.0.0.0 --port 3000
```

The Slack integration is optional — the server starts without `SLACK_BOT_TOKEN`/`SLACK_SIGNING_SECRET`. Only `OPENROUTER_API_KEY` and GCP credentials are required to use the `/demo` endpoint.

Deploy to Cloud Run:
```bash
gcloud run deploy cynda-query-slack --source . --project cynda-query --region europe-west1 --platform managed --allow-unauthenticated --env-vars-file env.yaml
```

The default compute service account needs `roles/bigquery.dataViewer` and `roles/bigquery.jobUser` IAM roles (see `local.sh` for the exact gcloud commands).

## Environment Variables

Store in `.env` locally; use `env.yaml` for Cloud Run deployment.

**Always required:**
- `OPENROUTER_API_KEY` — LiteLLM calls Gemini 2.0 Flash via OpenRouter
- `SLACK_BOT_TOKEN` — Slack bot token
- `SLACK_SIGNING_SECRET` — Slack signing secret

**Required when `BQ_AUTH_MODE=oauth`:**
- `DATABASE_URL` — PostgreSQL connection string (stores user tokens, query logs, OAuth states)
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` — Google OAuth2

**Optional:**
- `GCP_PROJECT_ID` — defaults to `cynda-query`
- `GOOGLE_APPLICATION_CREDENTIALS_JSON` — service account JSON for BigQuery (alternative to ADC)
- `BQ_AUTH_MODE` — `sa` (default, service account) or `oauth` (per-user Google auth)

## Architecture

Two entry points share the core logic in `src/tools.py`:

**Core (`src/tools.py`):**
1. `get_bq_client()` — creates a BigQuery client using a service account or ADC
2. `get_table_metadata(client, table_id_list)` — fetches schema and descriptions for specified tables
3. `generate_sql(question, table_id_list, metadata)` — generates BigQuery SQL via `openrouter/google/gemini-2.0-flash-001`; returns `NOT_A_QUESTION` marker if the input is not a valid business question
4. `fix_sql(question, table_id_list, metadata, bad_sql, error)` — called automatically when `execute_query` fails; feeds the original SQL + BigQuery error back to the model to get a corrected query (one retry)
5. `execute_query(client, sql)` — runs the SQL and returns up to 100 rows as dicts
6. `summarize_results(question, sql, rows)` — produces a concise plain-English answer from the query results
7. `run(project_id, question, table_id_list)` — orchestrates the full pipeline: metadata → SQL → (retry on error) → summarize

**SQL error retry loop** (in `run()`):
```
generate_sql()
    ↓
execute_query() ── BigQuery error? ──→ fix_sql(sql + error) ──→ execute_query()
    ↓ ok
summarize_results()
```
If the second attempt also fails, the exception propagates to the caller.

**Demo endpoint (`api/index.py`):**
- `POST /demo` — accepts `{ question: str, table_ids: list[str] }`, runs the full pipeline, returns `{ answer: str }`
- CORS enabled (all origins) — restrict in production
- Slack integration is loaded only when `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET` are set; the server starts without them

**Slack bot (`api/index.py`):**
- FastAPI app with `SlackRequestHandler` mounted at `POST /slack/events`
- Handles app mentions and DMs; opens a modal form for BigQuery project + table + question
- `TABLE_ID_LIST` is hardcoded — update it to change which tables the bot queries

**Deployment:** Dockerfile runs the API server via uvicorn as a non-root user. Cloud Run deployment uses `env.yaml` for environment variables.
