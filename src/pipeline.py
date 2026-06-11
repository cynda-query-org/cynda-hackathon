"""ADK-based pipeline entry point.

Creates (or resumes) a persistent ADK session keyed by conversation_id,
injects connection config into session state, runs root_agent, and extracts
results from session state when the agent finishes.

Session state contract (set by this module, read by cynda_agent tools):
    db_type           — "bigquery" | "postgres"
    connection_config — connector-specific params dict

Session state contract (set by cynda_agent tools, read here):
    last_sql        — executed SQL, or NOT_A_QUESTION_MARKER for non-questions
    last_rows       — list[dict] query results (may be empty)
    last_table_html — HTML <table> built from last_rows (may be None)
"""
import os
import uuid

from google.adk.runners import Runner
from google.genai.types import Content, Part
from sqlalchemy.pool import NullPool

from cynda_agent.agent import root_agent
from src.model.disambiguation import NOT_A_QUESTION_MARKER

_APP_NAME = "cynda_query"
_USER_ID = "pipeline"


def _make_session_service():
    raw = os.environ.get("DATABASE_URL", "")
    if raw.startswith("postgresql://"):
        db_url = "postgresql+asyncpg://" + raw[len("postgresql://"):]
    elif raw.startswith("postgres://"):
        db_url = "postgresql+asyncpg://" + raw[len("postgres://"):]
    else:
        db_url = raw

    if db_url and "postgresql" in db_url:
        from google.adk.sessions import DatabaseSessionService
        return DatabaseSessionService(db_url, poolclass=NullPool)

    from google.adk.sessions import InMemorySessionService
    return InMemorySessionService()


async def run(
    question: str,
    table_id_list: list[str],
    conversation_id: str | None = None,
    db_type: str = "bigquery",
    connection_config: dict | None = None,
    org_context: str | None = None,
    max_table_rows: int | None = None,
) -> tuple[str, list[dict], str, str | None]:
    """Run the full pipeline via the ADK multi-agent system.

    Args:
        question:          User's business question.
        table_id_list:     Tables available for querying.
        conversation_id:   Existing conversation ID to resume, or None to start fresh.
        db_type:           Database dialect — "bigquery" or "postgres".
        connection_config: Connector-specific credentials/params dict.
        org_context:       Free-text business context about the company (sector, terminology, KPIs).
        max_table_rows:    Maximum rows to render as a table (None = use tool default).

    Returns:
        (sql, rows, summary, table_html)
    """
    session_service = _make_session_service()
    session_id = conversation_id or str(uuid.uuid4())

    per_call_state = {
        "db_type": db_type,
        "connection_config": connection_config or {},
        "last_sql": None,
        "last_rows": None,
        "last_table_html": None,
        "max_table_rows": max_table_rows,
    }

    session = await session_service.get_session(
        app_name=_APP_NAME, user_id=_USER_ID, session_id=session_id
    )
    if session:
        # update_session was removed from the ADK public API; inject state
        # changes as an event with a state_delta so the runner sees them.
        from google.adk.events import Event, EventActions
        await session_service.append_event(
            session=session,
            event=Event(
                author="user",
                actions=EventActions(state_delta=per_call_state),
            ),
        )
    else:
        session = await session_service.create_session(
            app_name=_APP_NAME,
            user_id=_USER_ID,
            session_id=session_id,
            state=per_call_state,
        )

    runner = Runner(
        app_name=_APP_NAME,
        agent=root_agent,
        session_service=session_service,
    )

    tables_str = ", ".join(table_id_list)
    full_question = f"Database type: {db_type}\nAvailable tables: {tables_str}"
    # Inject org_context only on the first turn — subsequent turns see it via conversation history.
    if org_context and session is None:
        full_question += f"\n\nBusiness context:\n{org_context}"
    full_question += f"\n\nQuestion: {question}"

    final_response = ""
    async for event in runner.run_async(
        user_id=_USER_ID,
        session_id=session_id,
        new_message=Content(role="user", parts=[Part(text=full_question)]),
    ):
        if event.is_final_response() and event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    final_response = part.text
                    break

    updated_session = await session_service.get_session(
        app_name=_APP_NAME, user_id=_USER_ID, session_id=session_id
    )
    last_sql: str | None = updated_session.state.get("last_sql")
    last_rows: list[dict] = updated_session.state.get("last_rows") or []
    last_table_html: str | None = updated_session.state.get("last_table_html")

    if not last_sql or last_sql == NOT_A_QUESTION_MARKER:
        return NOT_A_QUESTION_MARKER, [], final_response, None

    if not last_rows:
        return last_sql, [], "The query returned no results for that question.", None

    return last_sql, last_rows, final_response, last_table_html
