"""Slack bot — Bolt app setup, event/action/view handlers, and query execution."""
import asyncio
import os
import re

from src import pipeline
from src.formatters import to_slack_mrkdwn

# ---------------------------------------------------------------------------
# Bolt app initialisation (optional — disabled when env vars are absent)
# ---------------------------------------------------------------------------

_slack_token = os.environ.get("SLACK_BOT_TOKEN")  # legacy fallback
_slack_secret = os.environ.get("SLACK_SIGNING_SECRET")
slack_enabled = bool(_slack_secret)

if slack_enabled:
    from slack_bolt.async_app import AsyncApp
    from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
    from slack_bolt.authorization import AuthorizeResult
    from slack_sdk import WebClient

    async def _authorize(enterprise_id, team_id, logger):
        import api.db as _db
        workspace = await asyncio.to_thread(_db.get_slack_workspace, team_id)
        if workspace and workspace.get("bot_token"):
            return AuthorizeResult(
                enterprise_id=enterprise_id,
                team_id=team_id,
                bot_token=workspace["bot_token"],
                bot_user_id=workspace.get("bot_user_id"),
            )
        if _slack_token:
            return AuthorizeResult(enterprise_id=enterprise_id, team_id=team_id, bot_token=_slack_token)
        raise ValueError(f"No Cynda installation found for workspace {team_id}")

    bolt_app = AsyncApp(signing_secret=_slack_secret, authorize=_authorize)
    slack_client = WebClient(token=_slack_token) if _slack_token else None
else:
    bolt_app = None
    slack_client = None

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

QUERY_TIMEOUT_SECONDS = 240

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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_dm(channel: str) -> bool:
    return channel.startswith("D")


def _classify_error(e: Exception) -> str:
    msg = str(e)
    if "401" in msg or "invalid_grant" in msg or "Token has been expired" in msg:
        return ":lock: Your Google credentials have expired. Please re-authenticate by sending me a new message."
    if "403" in msg or "Access Denied" in msg or "does not have bigquery" in msg:
        return ":no_entry: Access denied. Make sure your account has BigQuery access to this project and table."
    if "404" in msg or "Not found" in msg:
        return ":mag: Table not found. Double-check the table path (`project.dataset.table`)."
    if "timeout" in msg.lower() or "Timeout" in msg:
        return ":hourglass: The query timed out. Try a simpler query or a smaller table."
    return f":x: Something went wrong: {msg}"


def _fetch_thread_history(channel: str, thread_ts: str) -> list[dict]:
    """Read the Slack thread and return LLM-friendly [{role, content}] pairs.

    Keeps user questions and bot summaries only. Falls back to [] on any error.
    """
    if not slack_client:
        return []
    try:
        result = slack_client.conversations_replies(channel=channel, ts=thread_ts)
        history = []
        for msg in result.get("messages", []):
            text = (msg.get("text") or "").strip()
            if not text:
                continue
            if msg.get("bot_id"):
                if text.startswith("*Summary:*"):
                    history.append({"role": "assistant", "content": text[len("*Summary:*"):].strip()})
            else:
                content = re.sub(r"<@\w+>", "", text).strip()
                if content:
                    history.append({"role": "user", "content": content})
        return history
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Workspace-connection aware handler
# ---------------------------------------------------------------------------

async def _resolve_slack_connection(connection: dict, workspace: dict) -> tuple[list[str], str, dict] | None:
    """Return (table_ids, db_type, connection_config) or None on auth failure."""
    import api.db as db_module

    if connection["db_type"] == "mock":
        return MOCK_TABLE_IDS, "bigquery", {}

    if connection["db_type"] == "postgres":
        pg_config = {"url": connection["credentials"]["url"]}
        from src.database.postgres import PostgresConnector
        table_ids = await asyncio.to_thread(PostgresConnector(pg_config["url"]).list_tables)
        return table_ids, "postgres", pg_config

    if connection["db_type"] == "bigquery":
        creds = connection.get("credentials") or {}
        bq_config = {
            "billing_project": creds.get("billing_project") or os.environ.get("GCP_PROJECT_ID", "cynda-query"),
            "data_project": creds.get("data_project"),
        }
        auth_mode = creds.get("auth_mode", "sa")
        if auth_mode == "sa":
            bq_config["sa_json"] = creds.get("sa_json")
        elif auth_mode == "oauth":
            installed_by = str(workspace.get("installed_by") or "")
            token = await asyncio.to_thread(db_module.get_user_google_token, installed_by) if installed_by else None
            if not token:
                return None  # caller will send the auth error message
            bq_config["access_token"] = token["access_token"]
            bq_config["refresh_token"] = token["refresh_token"]
        else:
            return None

        from src.database.bigquery import BigQueryConnector
        table_ids = await asyncio.to_thread(BigQueryConnector(**bq_config).list_tables)
        return table_ids, "bigquery", bq_config

    return None


async def _handle_with_workspace_connection(
    team_id: str,
    user_id: str,
    channel: str,
    thread_ts: str,
    question: str,
) -> bool:
    """Try to answer using the workspace's pre-configured connection.

    Returns True if handled (workspace connection found), False otherwise.
    """
    import time
    import api.db as db_module

    workspace = await asyncio.to_thread(db_module.get_slack_workspace, team_id)
    if not workspace or not workspace.get("connection_id"):
        return False

    connection = await asyncio.to_thread(db_module.get_connection_by_id, str(workspace["connection_id"]))
    if not connection:
        return False

    ws_client = WebClient(token=workspace["bot_token"])

    try:
        resolved = await _resolve_slack_connection(connection, workspace)
    except Exception as e:
        await asyncio.to_thread(
            ws_client.chat_postMessage,
            channel=channel, thread_ts=thread_ts,
            text=f":x: Could not connect to the database: {e}",
        )
        return True

    if resolved is None:
        await asyncio.to_thread(
            ws_client.chat_postMessage,
            channel=channel, thread_ts=thread_ts,
            text=":x: BigQuery OAuth credentials not found. Please reconnect BigQuery from the dashboard.",
        )
        return True

    table_ids, db_type, connection_config = resolved

    await asyncio.to_thread(
        ws_client.chat_postMessage,
        channel=channel, thread_ts=thread_ts,
        text=f"On it! _{question}_",
    )

    # Get or create a conversation — its ID becomes the ADK session ID so
    # history is automatically preserved across follow-up messages.
    installed_by = str(workspace.get("installed_by") or "")
    conv = None
    if installed_by:
        conv = await asyncio.to_thread(
            db_module.get_or_create_slack_conversation,
            installed_by, str(workspace["connection_id"]),
            question[:60], thread_ts, channel, team_id,
        )

    conversation_id = str(conv["id"]) if conv else None

    t0 = time.monotonic()
    try:
        sql, _, summary, _iframe = await asyncio.wait_for(
            pipeline.run(question, table_ids, conversation_id=conversation_id, db_type=db_type, connection_config=connection_config),
            timeout=QUERY_TIMEOUT_SECONDS,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        if conv:
            await asyncio.to_thread(
                db_module.add_messages, str(conv["id"]),
                [
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": summary, "sql_generated": sql, "success": True, "latency_ms": latency_ms},
                ],
            )
        await asyncio.to_thread(
            ws_client.chat_postMessage,
            channel=channel, thread_ts=thread_ts,
            text=f"*SQL:*\n```{sql}```",
        )
        await asyncio.to_thread(
            ws_client.chat_postMessage,
            channel=channel, thread_ts=thread_ts,
            text=f"*Summary:*\n{to_slack_mrkdwn(summary)}",
        )
    except asyncio.TimeoutError:
        err = f"Query timed out after {QUERY_TIMEOUT_SECONDS // 60} minutes."
        if conv:
            await asyncio.to_thread(
                db_module.add_messages, str(conv["id"]),
                [
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": err, "success": False, "error_message": "timeout"},
                ],
            )
        await asyncio.to_thread(
            ws_client.chat_postMessage,
            channel=channel, thread_ts=thread_ts,
            text=f":hourglass: {err} Try a simpler question.",
        )
    except Exception as e:
        err_msg = _classify_error(e)
        if conv:
            await asyncio.to_thread(
                db_module.add_messages, str(conv["id"]),
                [
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": err_msg, "success": False, "error_message": str(e)},
                ],
            )
        await asyncio.to_thread(
            ws_client.chat_postMessage,
            channel=channel, thread_ts=thread_ts,
            text=err_msg,
        )

    return True


# ---------------------------------------------------------------------------
# Incoming message routing
# ---------------------------------------------------------------------------

async def _handle_incoming(user_id: str, channel: str, thread_ts: str, message_text: str = "", team_id: str = "") -> None:
    if team_id and message_text:
        handled = await _handle_with_workspace_connection(team_id, user_id, channel, thread_ts, message_text)
        if handled:
            return
async def _handle_thread_followup(user_id: str, channel: str, thread_ts: str, question: str, team_id: str = "") -> None:
    """Handle a follow-up bot mention inside an existing thread."""
    if team_id:
        handled = await _handle_with_workspace_connection(team_id, user_id, channel, thread_ts, question)
        if handled:
            return


# ---------------------------------------------------------------------------
# Bolt event / action / view handlers (registered only when Slack is enabled)
# ---------------------------------------------------------------------------

if bolt_app is not None:

    @bolt_app.event("app_mention")
    async def handle_app_mention(event, body):
        text = event.get("text", "")
        message_text = " ".join(w for w in text.split() if not w.startswith("<@")).strip()
        team_id = body.get("team_id", "")

        thread_ts = event.get("thread_ts")
        is_thread_reply = bool(thread_ts) and thread_ts != event["ts"]

        if is_thread_reply and message_text:
            await _handle_thread_followup(
                user_id=event["user"],
                channel=event["channel"],
                thread_ts=thread_ts,
                question=message_text,
                team_id=team_id,
            )
        else:
            await _handle_incoming(
                user_id=event["user"],
                channel=event["channel"],
                thread_ts=thread_ts or event["ts"],
                message_text=message_text,
                team_id=team_id,
            )

    @bolt_app.message("")
    async def handle_dm(message, body):
        if not message["channel"].startswith("D"):
            return  # channel mentions handled by handle_app_mention
        team_id = body.get("team_id", "")
        await _handle_incoming(
            user_id=message["user"],
            channel=message["channel"],
            thread_ts=message["ts"],
            message_text=message.get("text", ""),
            team_id=team_id,
        )

    handler = AsyncSlackRequestHandler(bolt_app)

else:
    handler = None
