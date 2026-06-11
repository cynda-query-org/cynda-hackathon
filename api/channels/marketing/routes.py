import os
import re

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

router = APIRouter()

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "")


def _airtable_url() -> str:
    base_id = os.environ["AIRTABLE_BASE_ID"]
    table_name = os.environ["AIRTABLE_TABLE_NAME"]
    return f"https://api.airtable.com/v0/{base_id}/{table_name}"


class SubscribeRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("invalid email")
        return v


@router.post("/subscribe")
async def subscribe(payload: SubscribeRequest, request: Request):
    if _ALLOWED_ORIGIN and request.headers.get("origin", "") != _ALLOWED_ORIGIN:
        raise HTTPException(status_code=403, detail="Forbidden")

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            _airtable_url(),
            headers={
                "Authorization": f"Bearer {os.environ['AIRTABLE_API_KEY']}",
                "Content-Type": "application/json",
            },
            json={"fields": {"Email": payload.email}},
        )

    if resp.status_code not in (200, 201):
        raise HTTPException(status_code=500, detail="Failed to save")

    return {"success": True}
