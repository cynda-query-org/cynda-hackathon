"""PostgreSQL connector — schema discovery and query execution."""
import psycopg2
import psycopg2.extras

from src.database.base import BaseConnector, ColumnMetadata, TableMetadata
from src.model.sql_generation import postgres_generate_prompt, postgres_fix_prompt, call_model


class PostgresConnector(BaseConnector):
    def __init__(self, connection_url: str):
        self._url = connection_url

    def _connect(self):
        return psycopg2.connect(self._url)

    def list_tables(self) -> list[str]:
        """Return all base tables in the public schema as 'public.tablename'."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT table_name FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                """)
                rows = cur.fetchall()
        return [f"public.{r[0]}" for r in rows]

    def get_table_metadata(self, table_id_list: list[str]) -> dict[str, TableMetadata]:
        table_names = [t.split(".")[-1] for t in table_id_list]
        with self._connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT table_name, column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = ANY(%s)
                    ORDER BY table_name, ordinal_position
                """, (table_names,))
                rows = cur.fetchall()

        tables: dict[str, list[ColumnMetadata]] = {}
        for row in rows:
            t = row["table_name"]
            tables.setdefault(t, []).append({
                "name": row["column_name"],
                "type": row["data_type"],
                "mode": "NULLABLE" if row["is_nullable"] == "YES" else "REQUIRED",
                "description": None,
            })

        return {
            tid: {"description": None, "columns": tables.get(tid.split(".")[-1], [])}
            for tid in table_id_list
        }

    def execute_query(self, sql: str, max_rows: int = 100) -> list[dict]:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql)
                rows = cur.fetchmany(max_rows)
        return [dict(r) for r in rows]

    def generate_sql(
        self,
        question: str,
        table_id_list: list[str],
        metadata: dict,
        history: list[dict] | None = None,
    ) -> str:
        prompt = postgres_generate_prompt(table_id_list, metadata)
        return call_model(prompt, question, history)

    def fix_sql(
        self,
        question: str,
        table_id_list: list[str],
        metadata: dict,
        bad_sql: str,
        error: str,
    ) -> str:
        prompt = postgres_fix_prompt(table_id_list, metadata, bad_sql, error, question)
        return call_model(prompt, question)
