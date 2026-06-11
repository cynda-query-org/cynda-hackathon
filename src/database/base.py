from abc import ABC, abstractmethod
from typing import TypedDict


class ColumnMetadata(TypedDict):
    name: str
    type: str
    mode: str
    description: str | None


class TableMetadata(TypedDict):
    description: str | None
    columns: list[ColumnMetadata]


class BaseConnector(ABC):
    @abstractmethod
    def get_table_metadata(self, table_id_list: list[str]) -> dict[str, TableMetadata]:
        ...

    @abstractmethod
    def execute_query(self, sql: str, max_rows: int = 100) -> list[dict]:
        ...

    @abstractmethod
    def generate_sql(
        self,
        question: str,
        table_id_list: list[str],
        metadata: dict[str, TableMetadata],
        history: list[dict] | None = None,
    ) -> str:
        ...

    @abstractmethod
    def fix_sql(
        self,
        question: str,
        table_id_list: list[str],
        metadata: dict[str, TableMetadata],
        bad_sql: str,
        error: str,
    ) -> str:
        ...
