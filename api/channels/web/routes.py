"""Web channel routes — auth, database connections, and the protected /demo endpoint."""
import asyncio
import os
import re as _re
from collections import defaultdict
from time import time as _time

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr

from api.channels.web.auth import get_current_user, hash_password, verify_password
import api.db as db
from src import pipeline

router = APIRouter()

MOCK_TABLE_IDS = [
    "cynda-query.demo.customers",
    "cynda-query.demo.geolocation",
    "cynda-query.demo.order_items",
    "cynda-query.demo.order_payments",
    "cynda-query.demo.order_reviews",
    "cynda-query.demo.orders",
    "cynda-query.demo.product_category_translation",
    "cynda-query.demo.products",
    "cynda-query.demo.sellers",
]

_public_demo_calls: dict[str, list[float]] = defaultdict(list)


def _strip_markdown_tables(text: str) -> str:
    """Remove pipe-separated markdown table lines the LLM may emit alongside a rendered table."""
    lines = [l for l in text.splitlines() if not l.strip().startswith('|')]
    return _re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()


def _allow_public_demo(ip: str, max_calls: int = 20, window: int = 3600) -> bool:
    now = _time()
    calls = _public_demo_calls[ip]
    _public_demo_calls[ip] = [t for t in calls if now - t < window]
    if len(_public_demo_calls[ip]) >= max_calls:
        return False
    _public_demo_calls[ip].append(now)
    return True


# ---------------------------------------------------------------------------
# Auth models
# ---------------------------------------------------------------------------

class SignupRequest(BaseModel):
    email: EmailStr
    name: str
    password: str
    ref_token: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    newsletter_opt_in: bool = True
    token: str | None = None


class UpdateProfileRequest(BaseModel):
    name: str | None = None
    newsletter_opt_in: bool | None = None


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

@router.post("/auth/signup", response_model=UserResponse)
async def signup(req: SignupRequest, response: Response):
    if len(req.password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")
    if not req.name.strip():
        raise HTTPException(status_code=422, detail="Name must not be empty")

    existing = await asyncio.to_thread(db.get_user_by_email, req.email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    password_hash = await asyncio.to_thread(hash_password, req.password)
    user = await asyncio.to_thread(db.create_user, req.email, req.name, password_hash)

    if req.ref_token:
        await asyncio.to_thread(db.record_referral_use, req.ref_token)

    token = await asyncio.to_thread(db.create_session, str(user["id"]))

    response.set_cookie(
        key="cynda_session",
        value=token,
        httponly=True,
        samesite="none",
        max_age=db.SESSION_TTL_DAYS * 86400,
        secure=True,
    )
    return UserResponse(id=str(user["id"]), email=user["email"], name=user["name"], token=token)


@router.post("/auth/login", response_model=UserResponse)
async def login(req: LoginRequest, response: Response):
    user = await asyncio.to_thread(db.get_user_by_email, req.email)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    valid = await asyncio.to_thread(verify_password, req.password, user["password_hash"])
    if not valid:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    await asyncio.to_thread(db.update_last_login, str(user["id"]))
    token = await asyncio.to_thread(db.create_session, str(user["id"]))

    response.set_cookie(
        key="cynda_session",
        value=token,
        httponly=True,
        samesite="none",
        max_age=db.SESSION_TTL_DAYS * 86400,
        secure=True,
    )
    return UserResponse(id=str(user["id"]), email=user["email"], name=user["name"], token=token)


@router.get("/auth/google")
async def google_login():
    from api.channels.web.google_auth import web_auth_url
    state = await asyncio.to_thread(db.create_web_oauth_state)
    return RedirectResponse(web_auth_url(state))


@router.get("/auth/google/callback")
async def google_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    from api.channels.web.google_auth import exchange_code
    frontend_url = os.environ.get("FRONTEND_URL", "https://cynda.chat")

    if error or not code or not state:
        return RedirectResponse(f"{frontend_url}/pages/login.html?error=google_cancelled")

    state_valid = await asyncio.to_thread(db.consume_web_oauth_state, state)
    if not state_valid:
        return RedirectResponse(f"{frontend_url}/pages/login.html?error=invalid_state")

    user_info = await asyncio.to_thread(exchange_code, code)
    if not user_info:
        return RedirectResponse(f"{frontend_url}/pages/login.html?error=google_auth_failed")

    user = await asyncio.to_thread(db.get_user_by_google_id, user_info["google_id"])
    if not user:
        existing = await asyncio.to_thread(db.get_user_by_email, user_info["email"])
        if existing:
            await asyncio.to_thread(db.link_google_account, str(existing["id"]), user_info["google_id"])
            user = existing
        else:
            user = await asyncio.to_thread(db.create_google_user, user_info["email"], user_info["name"], user_info["google_id"])

    await asyncio.to_thread(db.update_last_login, str(user["id"]))
    token = await asyncio.to_thread(db.create_session, str(user["id"]))

    redirect = RedirectResponse(f"{frontend_url}/pages/dashboard.html")
    redirect.set_cookie(
        key="cynda_session",
        value=token,
        httponly=True,
        samesite="none",
        max_age=db.SESSION_TTL_DAYS * 86400,
        secure=True,
    )
    return redirect


@router.post("/auth/forgot-password")
async def forgot_password(req: ForgotPasswordRequest):
    from api.email import send_password_reset_email
    user = await asyncio.to_thread(db.get_user_by_email, req.email)
    if user:
        token = await asyncio.to_thread(db.create_reset_token, str(user["id"]))
        frontend_url = os.environ.get("FRONTEND_URL", "https://cynda.chat")
        reset_link = f"{frontend_url}/pages/reset.html?token={token}"
        await asyncio.to_thread(send_password_reset_email, user["email"], reset_link)
    return {"ok": True}


@router.post("/auth/reset-password")
async def reset_password(req: ResetPasswordRequest):
    if len(req.password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")
    user_id = await asyncio.to_thread(db.consume_reset_token, req.token)
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")
    password_hash = await asyncio.to_thread(hash_password, req.password)
    await asyncio.to_thread(db.update_password, user_id, password_hash)
    return {"ok": True}


@router.post("/auth/change-password")
async def change_password(req: ChangePasswordRequest, user: dict = Depends(get_current_user)):
    if len(req.new_password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")
    full_user = await asyncio.to_thread(db.get_user_by_email, user["email"])
    if not await asyncio.to_thread(verify_password, req.current_password, full_user["password_hash"]):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    password_hash = await asyncio.to_thread(hash_password, req.new_password)
    await asyncio.to_thread(db.update_password, str(user["id"]), password_hash)
    return {"ok": True}


@router.post("/auth/logout")
async def logout(response: Response, cynda_session: str | None = Cookie(None)):
    if cynda_session:
        await asyncio.to_thread(db.delete_session, cynda_session)
    response.delete_cookie("cynda_session")
    return {"ok": True}


@router.get("/auth/me", response_model=UserResponse)
async def me(user: dict = Depends(get_current_user)):
    return UserResponse(id=str(user["id"]), email=user["email"], name=user["name"], newsletter_opt_in=user.get("newsletter_opt_in", True))


@router.get("/auth/referral")
async def get_referral(user: dict = Depends(get_current_user)):
    referral = await asyncio.to_thread(db.get_or_create_referral, str(user["id"]))
    frontend_url = os.environ.get("FRONTEND_URL", "https://cynda.chat")
    return {
        "token": referral["token"],
        "use_count": referral["use_count"],
        "link": f"{frontend_url}/?ref={referral['token']}",
    }


@router.put("/auth/me")
async def update_profile(req: UpdateProfileRequest, user: dict = Depends(get_current_user)):
    if req.name is not None and not req.name.strip():
        raise HTTPException(status_code=422, detail="Name must not be empty")
    await asyncio.to_thread(db.update_user_profile, str(user["id"]), req.name, req.newsletter_opt_in)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Database connections
# ---------------------------------------------------------------------------

class ConnectionRequest(BaseModel):
    db_type: str
    name: str
    credentials: dict | None = None
    org_context: str | None = None


class ConnectionResponse(BaseModel):
    id: str
    db_type: str
    name: str
    org_context: str | None = None
    created_at: str | None = None


def _conn_response(c: dict) -> ConnectionResponse:
    created_at = c.get("created_at")
    return ConnectionResponse(
        id=str(c["id"]),
        db_type=c["db_type"],
        name=c["name"],
        org_context=c.get("org_context"),
        created_at=created_at.isoformat() if created_at else None,
    )


@router.get("/connections", response_model=list[ConnectionResponse])
async def list_connections(user: dict = Depends(get_current_user)):
    connections = await asyncio.to_thread(db.get_connections, str(user["id"]))
    return [_conn_response(c) for c in connections]


@router.post("/connections", response_model=ConnectionResponse)
async def create_connection(req: ConnectionRequest, user: dict = Depends(get_current_user)):
    allowed_types = {"mock", "bigquery", "postgres"}
    if req.db_type not in allowed_types:
        raise HTTPException(status_code=422, detail=f"db_type must be one of: {', '.join(allowed_types)}")

    if req.db_type == "postgres" and not req.credentials:
        raise HTTPException(status_code=422, detail="credentials required for postgres connection")

    if req.db_type == "mock":
        existing = await asyncio.to_thread(db.get_mock_connection, str(user["id"]))
        if existing:
            return _conn_response(existing)

    conn = await asyncio.to_thread(
        db.create_connection, str(user["id"]), req.db_type, req.name, req.credentials, req.org_context
    )
    return _conn_response(conn)


@router.delete("/connections/{connection_id}")
async def delete_connection(connection_id: str, user: dict = Depends(get_current_user)):
    deleted = await asyncio.to_thread(db.delete_connection, connection_id, str(user["id"]))
    if not deleted:
        raise HTTPException(status_code=404, detail="Connection not found")
    return {"ok": True}


class UpdateConnectionRequest(BaseModel):
    org_context: str | None = None


@router.patch("/connections/{connection_id}", response_model=ConnectionResponse)
async def update_connection(connection_id: str, req: UpdateConnectionRequest, user: dict = Depends(get_current_user)):
    updated = await asyncio.to_thread(db.update_connection_org_context, connection_id, str(user["id"]), req.org_context)
    if not updated:
        raise HTTPException(status_code=404, detail="Connection not found")
    conn = await asyncio.to_thread(db.get_connection, connection_id, str(user["id"]))
    return _conn_response(conn)


# ---------------------------------------------------------------------------
# Slack OAuth + workspace linking
# ---------------------------------------------------------------------------

@router.get("/slack/enabled")
async def slack_enabled_check():
    return {"enabled": bool(os.environ.get("SLACK_CLIENT_ID"))}


@router.get("/slack/oauth/start")
async def slack_oauth_start(user: dict = Depends(get_current_user)):
    import secrets as _secrets
    client_id = os.environ.get("SLACK_CLIENT_ID")
    redirect_uri = os.environ.get("SLACK_REDIRECT_URI")
    if not client_id or not redirect_uri:
        raise HTTPException(status_code=503, detail="Slack OAuth not configured")
    state = _secrets.token_urlsafe(32)
    await asyncio.to_thread(db.store_slack_oauth_state, state, str(user["id"]))
    scopes = "app_mentions:read,channels:history,chat:write,chat:write.public,groups:history,im:history,im:read,im:write"
    url = (
        f"https://slack.com/oauth/v2/authorize"
        f"?client_id={client_id}"
        f"&scope={scopes}"
        f"&redirect_uri={redirect_uri}"
        f"&state={state}"
    )
    return RedirectResponse(url)


@router.get("/slack/oauth/callback")
async def slack_oauth_callback(code: str = "", state: str = "", error: str = ""):
    import httpx
    frontend_url = os.environ.get("FRONTEND_URL", "https://cynda.chat")
    if error or not code or not state:
        return RedirectResponse(f"{frontend_url}/pages/dashboard.html?slack=error")

    user_id = await asyncio.to_thread(db.consume_slack_oauth_state, state)
    if not user_id:
        return RedirectResponse(f"{frontend_url}/pages/dashboard.html?slack=error")

    client_id = os.environ.get("SLACK_CLIENT_ID")
    client_secret = os.environ.get("SLACK_CLIENT_SECRET")
    redirect_uri = os.environ.get("SLACK_REDIRECT_URI")

    async with httpx.AsyncClient() as client:
        resp = await client.post("https://slack.com/api/oauth.v2.access", data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        })
    data = resp.json()
    if not data.get("ok"):
        return RedirectResponse(f"{frontend_url}/pages/dashboard.html?slack=error")

    bot_token = data["access_token"]
    team_id = data["team"]["id"]
    team_name = data["team"]["name"]
    bot_user_id = data.get("bot_user_id")
    installing_slack_user_id = data.get("authed_user", {}).get("id")

    await asyncio.to_thread(
        db.upsert_slack_workspace,
        team_id, team_name, bot_token, user_id, bot_user_id,
    )

    # Send a welcome DM to the user who installed the app
    if installing_slack_user_id:
        try:
            import slack_sdk
            ws_client = slack_sdk.WebClient(token=bot_token)
            await asyncio.to_thread(
                ws_client.chat_postMessage,
                channel=installing_slack_user_id,
                text=(
                    f"👋 *Cynda was successfully installed in {team_name}!*\n\n"
                    f"To get started, add me to a channel:\n"
                    f">`/invite @cynda`\n\n"
                    f"Then just mention me with your question:\n"
                    f">`@cynda how many sales did we have this month?`\n\n"
                    f"Or send me a DM directly — no channel needed. 🚀"
                ),
            )
        except Exception:
            pass  # DM failure should never block the OAuth flow

    return RedirectResponse(f"{frontend_url}/pages/dashboard.html?slack=installed&workspace={team_name}")


@router.get("/slack/workspaces")
async def list_slack_workspaces(user: dict = Depends(get_current_user)):
    workspaces = await asyncio.to_thread(db.get_slack_workspaces_by_user, str(user["id"]))
    return workspaces


@router.get("/connections/{connection_id}/slack")
async def get_slack_status(connection_id: str, user: dict = Depends(get_current_user)):
    conn = await asyncio.to_thread(db.get_connection, connection_id, str(user["id"]))
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    workspace = await asyncio.to_thread(db.get_slack_workspace_by_connection, connection_id)
    if not workspace:
        return {"connected": False}
    return {"connected": True, "workspace_id": workspace["workspace_id"], "team_name": workspace["team_name"]}


class SlackLinkRequest(BaseModel):
    workspace_id: str


@router.post("/connections/{connection_id}/slack")
async def connect_slack(connection_id: str, body: SlackLinkRequest, user: dict = Depends(get_current_user)):
    conn = await asyncio.to_thread(db.get_connection, connection_id, str(user["id"]))
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    ok = await asyncio.to_thread(
        db.link_slack_workspace_to_connection,
        body.workspace_id, connection_id, str(user["id"]),
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Workspace not found or not owned by you")
    workspace = await asyncio.to_thread(db.get_slack_workspace, body.workspace_id)
    return {"connected": True, "workspace_id": workspace["workspace_id"], "team_name": workspace["team_name"]}


@router.delete("/connections/{connection_id}/slack")
async def disconnect_slack(connection_id: str, user: dict = Depends(get_current_user)):
    unlinked = await asyncio.to_thread(db.delete_slack_workspace_by_connection, connection_id, str(user["id"]))
    if not unlinked:
        raise HTTPException(status_code=404, detail="Slack connection not found")
    return {"ok": True}


@router.get("/auth/bigquery")
async def bigquery_oauth_start(connection_id: str, user: dict = Depends(get_current_user)):
    from api.channels.web.google_auth import bigquery_auth_url
    if not os.environ.get("GOOGLE_CLIENT_ID") or not os.environ.get("GOOGLE_BQ_REDIRECT_URI"):
        raise HTTPException(status_code=503, detail="BigQuery OAuth not configured")
    conn = await asyncio.to_thread(db.get_connection, connection_id, str(user["id"]))
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    state = await asyncio.to_thread(db.create_bq_oauth_state, str(user["id"]), connection_id)
    return RedirectResponse(bigquery_auth_url(state))


@router.get("/auth/bigquery/callback")
async def bigquery_oauth_callback(code: str = "", state: str = "", error: str = ""):
    from api.channels.web.google_auth import exchange_bq_code
    frontend_url = os.environ.get("FRONTEND_URL", "https://cynda.chat")
    if error or not code or not state:
        return RedirectResponse(f"{frontend_url}/pages/dashboard.html?bq=error")

    state_data = await asyncio.to_thread(db.consume_bq_oauth_state, state)
    if not state_data:
        return RedirectResponse(f"{frontend_url}/pages/dashboard.html?bq=error")

    tokens = await asyncio.to_thread(exchange_bq_code, code)
    if not tokens:
        return RedirectResponse(f"{frontend_url}/pages/dashboard.html?bq=error")

    user_id = state_data["user_id"]
    connection_id = state_data["connection_id"]
    await asyncio.to_thread(
        db.store_user_google_token, user_id, tokens["access_token"], tokens.get("refresh_token")
    )
    return RedirectResponse(f"{frontend_url}/pages/demo.html?connection_id={connection_id}")


async def _build_bq_config(conn: dict, user_id: str) -> dict:
    creds = conn.get("credentials") or {}
    auth_mode = creds.get("auth_mode", "sa")
    config = {
        "billing_project": creds.get("billing_project") or os.environ.get("GCP_PROJECT_ID", "cynda-query"),
        "data_project": creds.get("data_project") or None,
    }
    if auth_mode == "sa":
        config["sa_json"] = creds.get("sa_json")
        return config
    if auth_mode == "oauth":
        token = await asyncio.to_thread(db.get_user_google_token, user_id)
        if not token:
            raise HTTPException(
                status_code=401,
                detail="BigQuery not authorized. Please reconnect with Google from the dashboard.",
            )
        config["access_token"] = token["access_token"]
        config["refresh_token"] = token["refresh_token"]
        return config
    raise HTTPException(status_code=422, detail=f"Unknown BigQuery auth mode: {auth_mode}")


@router.get("/connections/{connection_id}/tables")
async def list_tables(connection_id: str, user: dict = Depends(get_current_user)):
    conn = await asyncio.to_thread(db.get_connection, connection_id, str(user["id"]))
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    if conn["db_type"] == "mock":
        return {"db_type": "mock", "name": conn["name"], "tables": MOCK_TABLE_IDS}
    if conn["db_type"] == "postgres":
        from src.database.postgres import PostgresConnector
        pg = PostgresConnector(conn["credentials"]["url"])
        tables = await asyncio.to_thread(pg.list_tables)
        return {"db_type": "postgres", "name": conn["name"], "tables": tables}
    if conn["db_type"] == "bigquery":
        from src.database.bigquery import BigQueryConnector
        config = await _build_bq_config(conn, str(user["id"]))
        bq = BigQueryConnector(**config)
        tables = await asyncio.to_thread(bq.list_tables)
        return {"db_type": "bigquery", "name": conn["name"], "tables": tables}
    raise HTTPException(status_code=422, detail="Table listing not supported for this connection type")


# ---------------------------------------------------------------------------
# Demo (protected)
# ---------------------------------------------------------------------------

class HistoryMessage(BaseModel):
    role: str
    content: str


class DemoRequest(BaseModel):
    question: str
    connection_id: str | None = None
    table_ids: list[str] | None = None
    history: list[HistoryMessage] = []
    conversation_id: str | None = None
    max_table_rows: int | None = None


class DemoResponse(BaseModel):
    answer: str
    conversation_id: str
    table_html: str | None = None


@router.post("/demo", response_model=DemoResponse)
async def demo(req: DemoRequest, user: dict = Depends(get_current_user)):
    import time
    if not req.question.strip():
        raise HTTPException(status_code=422, detail="question must not be empty")

    try:
        table_ids, db_type, connection_config, org_context = await _resolve_connection(req, user)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not connect to data source: {e}")

    # For new conversations, create the DB record first so the conversation ID
    # can be used as the ADK session ID — keeping both in sync from turn one.
    conv_id = req.conversation_id
    if conv_id is None and req.connection_id:
        from src.model.result_enhancement import generate_title
        title = await asyncio.to_thread(generate_title, req.question)
        conv = await asyncio.to_thread(
            db.create_conversation, str(user["id"]), req.connection_id, title
        )
        conv_id = str(conv["id"])

    t0 = time.monotonic()
    sql = None
    try:
        sql, _, summary, table_html = await pipeline.run(
            req.question, table_ids,
            conversation_id=conv_id,
            db_type=db_type,
            connection_config=connection_config,
            org_context=org_context,
            max_table_rows=req.max_table_rows,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    latency_ms = int((time.monotonic() - t0) * 1000)

    if req.connection_id and conv_id:
        await asyncio.to_thread(
            db.add_messages,
            conv_id,
            [
                {"role": "user", "content": req.question},
                {"role": "assistant", "content": summary, "sql_generated": sql, "success": True, "latency_ms": latency_ms},
            ],
        )

    if table_html:
        summary = _strip_markdown_tables(summary)
    return DemoResponse(answer=summary, conversation_id=conv_id or "", table_html=table_html)


@router.get("/conversations")
async def list_all_conversations(user: dict = Depends(get_current_user)):
    convs = await asyncio.to_thread(db.get_all_conversations, str(user["id"]))
    return [
        {
            "id": str(c["id"]),
            "title": c["title"],
            "connection_id": str(c["connection_id"]),
            "db_type": c["db_type"],
            "connection_name": c["connection_name"],
            "created_at": c["created_at"].isoformat(),
        }
        for c in convs
    ]


class PublicDemoRequest(BaseModel):
    question: str
    history: list[HistoryMessage] = []


@router.post("/public-demo")
async def public_demo(req: PublicDemoRequest, request: Request):
    ip = request.client.host
    if not _allow_public_demo(ip):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")
    if not req.question.strip():
        raise HTTPException(status_code=422, detail="question must not be empty")

    try:
        _, _, summary, table_html = await pipeline.run(
            req.question, MOCK_TABLE_IDS,
            db_type="bigquery",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if table_html:
        summary = _strip_markdown_tables(summary)
    return {"answer": summary, "table_html": table_html}


@router.get("/connections/{connection_id}/conversations")
async def list_conversations(connection_id: str, user: dict = Depends(get_current_user)):
    conn = await asyncio.to_thread(db.get_connection, connection_id, str(user["id"]))
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    convs = await asyncio.to_thread(db.get_conversations, str(user["id"]), connection_id)
    return [{"id": str(c["id"]), "title": c["title"], "created_at": c["created_at"].isoformat()} for c in convs]


@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(conversation_id: str, user: dict = Depends(get_current_user)):
    msgs = await asyncio.to_thread(db.get_messages, conversation_id, str(user["id"]))
    if msgs is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return [{"role": m["role"], "content": m["content"]} for m in msgs]


async def _resolve_connection(req: DemoRequest, user: dict) -> tuple[list[str], str, dict, str | None]:
    """Return (table_ids, db_type, connection_config, org_context) for the given request."""
    if req.connection_id:
        conn = await asyncio.to_thread(db.get_connection, req.connection_id, str(user["id"]))
        if not conn:
            raise HTTPException(status_code=404, detail="Connection not found")
        org_context = conn.get("org_context")
        if conn["db_type"] == "mock":
            return MOCK_TABLE_IDS, "bigquery", {}, org_context
        if conn["db_type"] == "postgres":
            pg_config = {"url": conn["credentials"]["url"]}
            if req.table_ids:
                return req.table_ids, "postgres", pg_config, org_context
            from src.database.postgres import PostgresConnector
            table_ids = await asyncio.to_thread(PostgresConnector(pg_config["url"]).list_tables)
            return table_ids, "postgres", pg_config, org_context
        if conn["db_type"] == "bigquery":
            bq_config = await _build_bq_config(conn, str(user["id"]))
            if req.table_ids:
                return req.table_ids, "bigquery", bq_config, org_context
            from src.database.bigquery import BigQueryConnector
            table_ids = await asyncio.to_thread(BigQueryConnector(**bq_config).list_tables)
            return table_ids, "bigquery", bq_config, org_context
        raise HTTPException(status_code=422, detail="table_ids required for this connection type")

    if not req.table_ids:
        raise HTTPException(status_code=422, detail="connection_id or table_ids required")
    return req.table_ids, "bigquery", {}, None
