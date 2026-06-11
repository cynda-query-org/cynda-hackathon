# cynda-query

Backend for Cynda — a multi-tenant web app that lets teams query their databases in plain English. Ask a business question, get back the SQL and a plain-English summary of the results. Works via a web chat interface and Slack.

## How it works

```
Question
   │
   ▼
connector.get_metadata()       ← schema from BigQuery / PostgreSQL / mock
   │
   ▼
connector.generate_sql()       ← Gemini 2.0 Flash via OpenRouter
   │
   ├─ NOT_A_QUESTION? ────────► answer_directly()
   │
   ▼
connector.execute_query()
   │
   ├─ error? ─────────────────► connector.fix_sql() → retry once
   │
   ▼
summarize_results()            ← plain-English answer
```

Each database connector (BigQuery, PostgreSQL, Mock) owns its own SQL generation and fix logic via a strategy pattern — `pipeline.py` is dialect-agnostic.

## Supported data sources

| Source | Status |
|--------|--------|
| PostgreSQL | ✅ Beta |
| Mock (Brazilian e-commerce dataset) | ✅ Ready |
| BigQuery (service account per-connection) | ✅ Beta |
| BigQuery (per-user Google OAuth per-connection) | ✅ Beta |

## Channels

### Web
Full-featured chat interface with:
- Email/password and Google OAuth authentication
- Persistent conversation history per connection
- Conversation messages logged with SQL, latency, and success/error status

### Slack
Multi-workspace support via Slack OAuth:
- Customers install the Cynda app in their own Slack workspace
- Each workspace gets its own bot token stored in the database
- Slack threads map 1:1 to conversations (logged the same way as web)
- Admin links a workspace to a database connection from the web dashboard

## Prerequisites

- Python 3.13
- [OpenRouter](https://openrouter.ai) API key (for Gemini 2.0 Flash)
- PostgreSQL database (user auth, connections, conversation history)
- Google Cloud credentials for BigQuery (ADC or service account JSON)

## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file (see all variables below), then run:

```bash
uvicorn api.index:app --host 0.0.0.0 --port 3000
```

## Environment variables

**Always required:**
```env
OPENROUTER_API_KEY=...
DATABASE_URL=postgresql://...
FRONTEND_URL=https://cynda.chat
```

**BigQuery (per-connection credentials):**

Both modes are selected per-connection by the admin when setting up a data source:

- **Service account**: paste SA JSON key into the dashboard form
- **Per-user OAuth**: admin clicks "Connect with Google"; Cynda stores `access_token` + `refresh_token` in `user_google_tokens`

```env
GCP_PROJECT_ID=cynda-query                # default billing project (optional)
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_WEB_REDIRECT_URI=https://<host>/auth/google/callback    # for login
GOOGLE_BQ_REDIRECT_URI=https://<host>/auth/bigquery/callback   # for BigQuery OAuth
```

Add both redirect URIs in Google Cloud Console → APIs & Services → Credentials → OAuth client → Authorized redirect URIs.

Legacy env-level SA (used by Slack's legacy BQ form):
```env
GOOGLE_APPLICATION_CREDENTIALS_JSON=...   # service account JSON string
BQ_AUTH_MODE=sa                           # default
```

**Slack (multi-workspace OAuth):**
```env
SLACK_SIGNING_SECRET=...       # from Slack app "Basic Information"
SLACK_CLIENT_ID=...            # from Slack app "Basic Information"
SLACK_CLIENT_SECRET=...        # from Slack app "Basic Information"
SLACK_REDIRECT_URI=https://<host>/slack/oauth/callback
```

**Email (Resend):**
```env
RESEND_API_KEY=...
```

## Deployment

Deployed on Railway. The Dockerfile runs uvicorn on port 3000 as a non-root user.

```bash
# Deploy via Railway GitHub integration (push to main triggers deploy)
```

## Project structure

```
api/
├── index.py                  — FastAPI app entry point, lifespan, router registration
├── db.py                     — Shared PostgreSQL layer: schema init + all DB helpers
└── channels/
    ├── web/
    │   ├── routes.py         — Auth, connections, /demo, Slack OAuth endpoints
    │   └── auth.py           — JWT + session cookie auth, Google OAuth2 callbacks
    └── slack/
        ├── handlers.py       — Bolt app (multi-workspace authorize), event/action handlers
        ├── auth.py           — Google OAuth for BigQuery (legacy per-user mode)
        └── db.py             — Legacy Slack-specific DB helpers (query logs, OAuth states)

src/
├── pipeline.py               — Dialect-agnostic orchestration: metadata → SQL → execute → summarize
├── database/
│   ├── base.py               — BaseConnector abstract class (generate_sql, fix_sql, execute_query…)
│   ├── bigquery.py           — BigQuery connector
│   ├── postgres.py           — PostgreSQL connector
│   └── mock.py               — Mock connector (Brazilian e-commerce dataset on BigQuery)
└── model/
    ├── sql_generation.py     — Prompt builders + LiteLLM call (Gemini 2.0 Flash via OpenRouter)
    ├── result_enhancement.py — Natural language summary generation
    └── disambiguation.py     — Detects non-business questions (NOT_A_QUESTION)

Dockerfile                    — Container image (uvicorn, non-root, port 3000)
```

## Database schema (key tables)

| Table | Purpose |
|-------|---------|
| `users` | Email/password + Google OAuth accounts |
| `database_connections` | Per-user connections (postgres / mock / bigquery) |
| `conversations` | One per chat session; stores channel (web/slack) and Slack thread coordinates |
| `conversation_messages` | Every Q&A pair with `sql_generated`, `success`, `latency_ms`, `error_message` |
| `slack_workspaces` | workspace_id → bot_token + connection_id mapping |
| `slack_oauth_states` | Short-lived PKCE-style state tokens for Slack OAuth flow |
| `referrals` | One referral token per user, tracks usage count |

## Slack OAuth flow

1. User clicks "Add to Slack" in the Cynda dashboard
2. `GET /slack/oauth/start` generates a state token and redirects to Slack
3. User authorises Cynda in their workspace
4. Slack calls `GET /slack/oauth/callback` with a code
5. Backend exchanges code for a workspace-specific `bot_token` via `oauth.v2.access`
6. Bot sends a welcome DM with `/invite` instructions to the installing user
7. User links the workspace to a database connection from the dashboard
8. All future Slack queries in that workspace run against the linked connection
