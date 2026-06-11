"""ADK tool functions for Cynda agents.

Auth and connection config are read from session state so callers never pass
credentials directly to tools.

Session state keys consumed:
    db_type           — "bigquery" | "postgres" (default: "bigquery")
    connection_config — dict with connector-specific params:
        bigquery: billing_project, data_project, sa_json, access_token, refresh_token
        postgres:  url

Session state keys produced:
    last_sql        — most-recently executed SQL, or NOT_A_QUESTION_MARKER
    last_rows       — rows returned by the last query (list of dicts)
    last_table_html — HTML <table> built from last_rows (optional)
"""
import json
import os

from google.adk.tools.tool_context import ToolContext

from src.database.bigquery import BigQueryConnector
from src.model.disambiguation import NOT_A_QUESTION_MARKER


def _get_connector(tool_context: ToolContext):
    state = tool_context.state
    db_type = state.get("db_type", "bigquery")
    config = state.get("connection_config") or {}

    if db_type == "postgres":
        from src.database.postgres import PostgresConnector
        return PostgresConnector(config["url"])

    return BigQueryConnector(
        billing_project=config.get("billing_project", os.environ.get("GCP_PROJECT_ID", "cynda-query")),
        data_project=config.get("data_project"),
        sa_json=config.get("sa_json"),
        access_token=config.get("access_token"),
        refresh_token=config.get("refresh_token"),
    )


def get_table_metadata(table_ids: list[str], tool_context: ToolContext) -> str:
    """Retrieve table schemas (column names, types, descriptions).

    Args:
        table_ids: Fully-qualified table IDs (project.dataset.table for BQ, schema.table for PG).
        tool_context: ADK context providing session state.

    Returns:
        JSON string mapping each table ID to its schema metadata.
    """
    connector = _get_connector(tool_context)
    metadata = connector.get_table_metadata(table_ids)
    return json.dumps(metadata)


def execute_sql(sql: str, tool_context: ToolContext) -> str:
    """Execute a SQL query and return results as JSON.

    Stores the executed SQL and result rows in session state.

    Args:
        sql: SQL query in the dialect of the configured database.
        tool_context: ADK context providing session state.

    Returns:
        JSON string of query results (list of row dicts), or an error
        message prefixed with "ERROR:" if execution fails.
    """
    connector = _get_connector(tool_context)
    try:
        rows = connector.execute_query(sql)
        tool_context.state["last_sql"] = sql
        # Round-trip through JSON to convert datetimes and other non-serializable
        # types to strings before storing in session state (persisted as JSONB).
        serializable_rows = json.loads(json.dumps(rows, default=str))
        tool_context.state["last_rows"] = serializable_rows
        return json.dumps(serializable_rows)
    except Exception as e:
        return f"ERROR: {e}"


def flag_not_a_question(tool_context: ToolContext) -> str:
    """Signal that the user's input is not a business data question.

    Args:
        tool_context: ADK context providing session state.

    Returns:
        Confirmation string.
    """
    tool_context.state["last_sql"] = NOT_A_QUESTION_MARKER
    return NOT_A_QUESTION_MARKER


_MAX_TABLE_ROWS = 50


def build_table(tool_context: ToolContext) -> str:
    """Build an HTML table from the last SQL query results and store it in session state.

    Reads last_rows (populated by execute_sql) from session state.
    Stores the rendered <table> HTML in last_table_html.
    Only renders tables with at most max_table_rows rows (from session state, default _MAX_TABLE_ROWS).

    Args:
        tool_context: ADK context providing session state.

    Returns:
        Confirmation string, or an error message if no rows are available.
    """
    rows = tool_context.state.get("last_rows") or []
    if not rows:
        return "No query results available to build a table."
    max_rows = tool_context.state.get("max_table_rows") or _MAX_TABLE_ROWS
    if len(rows) > max_rows:
        return f"Table skipped: {len(rows)} rows exceeds the {max_rows}-row display limit. Summarise the data instead."

    columns = list(rows[0].keys())

    def _esc(v: object) -> str:
        return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    thead = "".join(f"<th>{_esc(col)}</th>" for col in columns)
    tbody = "".join(
        "<tr>" + "".join(f"<td>{_esc(row.get(col, ''))}</td>" for col in columns) + "</tr>"
        for row in rows
    )
    html = f'<table class="cynda-table"><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>'
    tool_context.state["last_table_html"] = html
    return "Table built successfully."
