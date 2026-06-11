"""Google OAuth helpers for the web channel."""
import os
from urllib.parse import urlencode

import requests

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def web_auth_url(state: str) -> str:
    params = {
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "redirect_uri": os.environ["GOOGLE_WEB_REDIRECT_URI"],
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
    }
    return f"{_AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str) -> dict | None:
    """Exchange auth code for Google user info. Returns {google_id, email, name} or None."""
    token_res = requests.post(_TOKEN_URL, data={
        "code": code,
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        "redirect_uri": os.environ["GOOGLE_WEB_REDIRECT_URI"],
        "grant_type": "authorization_code",
    })
    if not token_res.ok:
        return None
    access_token = token_res.json().get("access_token")
    if not access_token:
        return None

    userinfo_res = requests.get(_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
    if not userinfo_res.ok:
        return None

    data = userinfo_res.json()
    return {
        "google_id": data.get("sub"),
        "email": data.get("email"),
        "name": data.get("name") or data.get("email", "").split("@")[0],
    }


def bigquery_auth_url(state: str) -> str:
    params = {
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "redirect_uri": os.environ["GOOGLE_BQ_REDIRECT_URI"],
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/bigquery",
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{_AUTH_URL}?{urlencode(params)}"


def exchange_bq_code(code: str) -> dict | None:
    """Exchange auth code for BigQuery tokens. Returns {access_token, refresh_token} or None."""
    token_res = requests.post(_TOKEN_URL, data={
        "code": code,
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        "redirect_uri": os.environ["GOOGLE_BQ_REDIRECT_URI"],
        "grant_type": "authorization_code",
    })
    if not token_res.ok:
        return None
    data = token_res.json()
    access_token = data.get("access_token")
    if not access_token:
        return None
    return {
        "access_token": access_token,
        "refresh_token": data.get("refresh_token"),
    }
