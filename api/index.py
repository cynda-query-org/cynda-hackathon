"""FastAPI application — routes and lifespan only."""
import asyncio
import contextlib
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from dotenv import load_dotenv
load_dotenv()

from api.db import init_db
from api.channels.slack.handlers import handler, slack_enabled
from api.channels.web.routes import router as web_router
from api.channels.marketing.routes import router as marketing_router


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    if not os.environ.get("DATABASE_URL"):
        raise RuntimeError("DATABASE_URL is required")

    # ADK/Vertex AI uses the standard GOOGLE_APPLICATION_CREDENTIALS env var
    # (path to a JSON file). GOOGLE_APPLICATION_CREDENTIALS_JSON holds the raw
    # JSON content — write it to a temp file so both ADK and BigQuery clients
    # can authenticate without any code changes to either.
    creds_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if creds_json and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        import tempfile
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmp.write(creds_json)
        tmp.close()
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = tmp.name

    await asyncio.to_thread(init_db)
    yield


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("ALLOWED_ORIGINS", "https://cynda.chat").split(","),
    allow_methods=["POST", "GET", "OPTIONS", "DELETE", "PATCH"],
    allow_headers=["Content-Type", "Authorization"],
    allow_credentials=True,
)

app.include_router(web_router)
app.include_router(marketing_router)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------

@app.post("/slack/events")
async def slack_events(req: Request):
    if not slack_enabled or handler is None:
        raise HTTPException(status_code=503, detail="Slack integration not configured")
    if req.headers.get("X-Slack-Retry-Num"):
        return {"ok": True}
    return await handler.handle(req)


