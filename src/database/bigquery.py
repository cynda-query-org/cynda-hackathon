import json
import os

from google.cloud import bigquery

from src.database.base import BaseConnector, ColumnMetadata, TableMetadata
from src.model.sql_generation import bigquery_generate_prompt, bigquery_fix_prompt, call_model

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "cynda-query")


def get_bq_client(project_id: str = PROJECT_ID) -> bigquery.Client:
    creds_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if creds_json:
        from google.oauth2 import service_account

        info = json.loads(creds_json)
        credentials = service_account.Credentials.from_service_account_info(
            info,
            scopes=["https://www.googleapis.com/auth/bigquery"],
        )
        return bigquery.Client(project=project_id, credentials=credentials)
    return bigquery.Client(project=project_id)


def get_bq_client_with_user_token(
    project_id: str,
    access_token: str,
    refresh_token: str,
) -> bigquery.Client:
    from google.oauth2.credentials import Credentials

    credentials = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
    )
    return bigquery.Client(project=project_id, credentials=credentials)


class BigQueryConnector(BaseConnector):
    def __init__(
        self,
        billing_project: str,
        data_project: str | None = None,
        sa_json: str | None = None,
        access_token: str | None = None,
        refresh_token: str | None = None,
    ):
        self._billing_project = billing_project
        self._data_project = data_project or billing_project
        self._sa_json = sa_json
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._client_cache: bigquery.Client | None = None

    def _get_client(self) -> bigquery.Client:
        if self._client_cache is None:
            if self._sa_json:
                from google.oauth2 import service_account
                info = json.loads(self._sa_json)
                credentials = service_account.Credentials.from_service_account_info(
                    info, scopes=["https://www.googleapis.com/auth/bigquery"]
                )
                self._client_cache = bigquery.Client(project=self._billing_project, credentials=credentials)
            elif self._access_token:
                from google.oauth2.credentials import Credentials
                credentials = Credentials(
                    token=self._access_token,
                    refresh_token=self._refresh_token,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=os.environ["GOOGLE_CLIENT_ID"],
                    client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
                )
                self._client_cache = bigquery.Client(project=self._billing_project, credentials=credentials)
            else:
                self._client_cache = get_bq_client(self._billing_project)
        return self._client_cache

    def list_tables(self) -> list[str]:
        client = self._get_client()
        result = []
        for dataset in client.list_datasets(project=self._data_project):
            for table in client.list_tables(f"{self._data_project}.{dataset.dataset_id}"):
                result.append(f"{self._data_project}.{dataset.dataset_id}.{table.table_id}")
        return result

    def get_table_metadata(self, table_id_list: list[str]) -> dict[str, TableMetadata]:
        client = self._get_client()
        metadata: dict[str, TableMetadata] = {}
        for table_id in table_id_list:
            table = client.get_table(table_id)
            metadata[table_id] = {
                "description": table.description,
                "columns": [
                    {
                        "name": col.name,
                        "type": col.field_type,
                        "mode": col.mode,
                        "description": col.description,
                    }
                    for col in table.schema
                ],
            }
        return metadata

    def execute_query(self, sql: str, max_rows: int = 100) -> list[dict]:
        query_job = self._get_client().query(sql)
        rows = query_job.result(max_results=max_rows)
        return [dict(row) for row in rows]

    def generate_sql(
        self,
        question: str,
        table_id_list: list[str],
        metadata: dict,
        history: list[dict] | None = None,
    ) -> str:
        prompt = bigquery_generate_prompt(table_id_list, metadata)
        return call_model(prompt, question, history)

    def fix_sql(
        self,
        question: str,
        table_id_list: list[str],
        metadata: dict,
        bad_sql: str,
        error: str,
    ) -> str:
        prompt = bigquery_fix_prompt(table_id_list, metadata, bad_sql, error, question)
        return call_model(prompt, question)
