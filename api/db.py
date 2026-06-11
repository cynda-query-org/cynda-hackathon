"""Shared database layer — schema init and helpers used across all channels."""
import json
import os
import secrets

import psycopg2
import psycopg2.extras

from api.security import decrypt_credentials, encrypt_credentials


def _get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def init_db() -> None:
    with _get_conn() as conn:
        with conn.cursor() as cur:
            # ------------------------------------------------------------------
            # Core identity
            # ------------------------------------------------------------------
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    email         TEXT UNIQUE NOT NULL,
                    name          TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at    TIMESTAMPTZ DEFAULT NOW(),
                    last_login_at TIMESTAMPTZ
                )
            """)

            # ------------------------------------------------------------------
            # Channel identities (slack_user_id, web session owner, etc.)
            # ------------------------------------------------------------------
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_channels (
                    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    channel         TEXT NOT NULL,
                    channel_user_id TEXT,
                    created_at      TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE (channel, channel_user_id)
                )
            """)

            # ------------------------------------------------------------------
            # Database connections (one row per source per user)
            # ------------------------------------------------------------------
            cur.execute("""
                CREATE TABLE IF NOT EXISTS database_connections (
                    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    db_type     TEXT NOT NULL,
                    name        TEXT NOT NULL,
                    credentials JSONB,
                    created_at  TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            # Ensure credentials column is JSONB; if it was previously migrated to
            # TEXT, wrap any bare Fernet tokens as {"_enc":"..."} and cast back.
            cur.execute("""
                DO $$ BEGIN
                    IF (SELECT data_type FROM information_schema.columns
                        WHERE table_name='database_connections' AND column_name='credentials') = 'text' THEN
                        UPDATE database_connections
                        SET credentials = jsonb_build_object('_enc', credentials)::text
                        WHERE credentials IS NOT NULL AND credentials NOT LIKE '{%';
                        ALTER TABLE database_connections
                            ALTER COLUMN credentials TYPE JSONB USING credentials::JSONB;
                    END IF;
                END $$
            """)

            # ------------------------------------------------------------------
            # Web sessions
            # ------------------------------------------------------------------
            cur.execute("""
                CREATE TABLE IF NOT EXISTS web_sessions (
                    token      TEXT PRIMARY KEY,
                    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS oauth_states (
                    state      TEXT PRIMARY KEY,
                    data       TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS password_reset_tokens (
                    token      TEXT PRIMARY KEY,
                    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            # Allow Google-only users (no password)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS referrals (
                    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id    UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
                    token      TEXT NOT NULL UNIQUE,
                    use_count  INT NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS google_id TEXT UNIQUE")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS newsletter_opt_in BOOLEAN NOT NULL DEFAULT TRUE")
            cur.execute("ALTER TABLE database_connections ADD COLUMN IF NOT EXISTS org_context TEXT")

            # ------------------------------------------------------------------
            # Chat history
            # ------------------------------------------------------------------
            cur.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    connection_id    UUID NOT NULL REFERENCES database_connections(id) ON DELETE CASCADE,
                    title            TEXT NOT NULL,
                    channel          TEXT NOT NULL DEFAULT 'web',
                    slack_thread_ts  TEXT,
                    slack_channel_id TEXT,
                    slack_team_id    TEXT,
                    created_at       TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'web';")
            cur.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS slack_thread_ts TEXT;")
            cur.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS slack_channel_id TEXT;")
            cur.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS slack_team_id TEXT;")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role            TEXT NOT NULL,
                    content         TEXT NOT NULL,
                    sql_generated   TEXT,
                    success         BOOLEAN,
                    error_message   TEXT,
                    latency_ms      INTEGER,
                    created_at      TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("ALTER TABLE conversation_messages ADD COLUMN IF NOT EXISTS sql_generated TEXT;")
            cur.execute("ALTER TABLE conversation_messages ADD COLUMN IF NOT EXISTS success BOOLEAN;")
            cur.execute("ALTER TABLE conversation_messages ADD COLUMN IF NOT EXISTS error_message TEXT;")
            cur.execute("ALTER TABLE conversation_messages ADD COLUMN IF NOT EXISTS latency_ms INTEGER;")

            # ------------------------------------------------------------------
            # Slack workspace ↔ connection linking
            # ------------------------------------------------------------------
            cur.execute("""
                CREATE TABLE IF NOT EXISTS slack_workspaces (
                    workspace_id  TEXT PRIMARY KEY,
                    team_name     TEXT NOT NULL,
                    bot_token     TEXT,
                    bot_user_id   TEXT,
                    connection_id UUID REFERENCES database_connections(id) ON DELETE SET NULL,
                    installed_by  UUID REFERENCES users(id) ON DELETE SET NULL,
                    created_at    TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            # Idempotent migrations for existing deployments
            cur.execute("ALTER TABLE slack_workspaces ADD COLUMN IF NOT EXISTS bot_token TEXT;")
            cur.execute("ALTER TABLE slack_workspaces ADD COLUMN IF NOT EXISTS bot_user_id TEXT;")
            cur.execute("""
                DO $$ BEGIN
                    ALTER TABLE slack_workspaces ALTER COLUMN connection_id DROP NOT NULL;
                EXCEPTION WHEN others THEN NULL;
                END $$;
            """)
            cur.execute("""
                DO $$ BEGIN
                    ALTER TABLE slack_workspaces DROP CONSTRAINT slack_workspaces_connection_id_fkey;
                EXCEPTION WHEN undefined_object THEN NULL;
                END $$;
            """)
            cur.execute("""
                DO $$ BEGIN
                    ALTER TABLE slack_workspaces ADD CONSTRAINT slack_workspaces_connection_id_fkey
                        FOREIGN KEY (connection_id) REFERENCES database_connections(id) ON DELETE SET NULL;
                EXCEPTION WHEN duplicate_object THEN NULL;
                END $$;
            """)
            # OAuth state tokens (PKCE-style, short-lived)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS slack_oauth_states (
                    state       TEXT PRIMARY KEY,
                    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at  TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            # ------------------------------------------------------------------
            # Per-user Google tokens (for BigQuery OAuth mode)
            # ------------------------------------------------------------------
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_google_tokens (
                    user_id       UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    access_token  TEXT NOT NULL,
                    refresh_token TEXT,
                    updated_at    TIMESTAMPTZ DEFAULT NOW()
                )
            """)
        conn.commit()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def create_user(email: str, name: str, password_hash: str) -> dict:
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO users (email, name, password_hash) VALUES (%s, %s, %s) RETURNING id, email, name, created_at",
                (email.lower().strip(), name.strip(), password_hash),
            )
            row = cur.fetchone()
        conn.commit()
    return dict(row)


def get_user_by_email(email: str) -> dict | None:
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, email, name, password_hash, created_at, last_login_at FROM users WHERE email = %s",
                (email.lower().strip(),),
            )
            row = cur.fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: str) -> dict | None:
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, email, name, created_at, last_login_at FROM users WHERE id = %s",
                (user_id,),
            )
            row = cur.fetchone()
    return dict(row) if row else None


def update_last_login(user_id: str) -> None:
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET last_login_at = NOW() WHERE id = %s", (user_id,))
        conn.commit()


# ---------------------------------------------------------------------------
# Web sessions
# ---------------------------------------------------------------------------

SESSION_TTL_DAYS = 30


def create_session(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO web_sessions (token, user_id, expires_at) VALUES (%s, %s, NOW() + INTERVAL '%s days')",
                (token, user_id, SESSION_TTL_DAYS),
            )
        conn.commit()
    return token


def get_session_user(token: str) -> dict | None:
    """Return the user for a valid (non-expired) session token, or None."""
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT u.id, u.email, u.name, u.newsletter_opt_in, u.created_at, u.last_login_at
                FROM web_sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token = %s AND s.expires_at > NOW()
                """,
                (token,),
            )
            row = cur.fetchone()
    return dict(row) if row else None


def update_user_profile(user_id: str, name: str | None, newsletter_opt_in: bool | None) -> None:
    fields, values = [], []
    if name is not None:
        fields.append("name = %s")
        values.append(name.strip())
    if newsletter_opt_in is not None:
        fields.append("newsletter_opt_in = %s")
        values.append(newsletter_opt_in)
    if not fields:
        return
    values.append(user_id)
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = %s", values)
        conn.commit()


def delete_session(token: str) -> None:
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM web_sessions WHERE token = %s", (token,))
        conn.commit()


# ---------------------------------------------------------------------------
# Database connections
# ---------------------------------------------------------------------------

def get_connections(user_id: str) -> list[dict]:
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, db_type, name, org_context, created_at FROM database_connections WHERE user_id = %s ORDER BY created_at",
                (user_id,),
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def create_connection(user_id: str, db_type: str, name: str, credentials: dict | None, org_context: str | None = None) -> dict:
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO database_connections (user_id, db_type, name, credentials, org_context) VALUES (%s, %s, %s, %s, %s) RETURNING id, db_type, name, org_context, created_at",
                (user_id, db_type, name, encrypt_credentials(credentials) if credentials else None, org_context),
            )
            row = cur.fetchone()
        conn.commit()
    return dict(row)


def get_connection(connection_id: str, user_id: str) -> dict | None:
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, db_type, name, credentials, org_context, created_at FROM database_connections WHERE id = %s AND user_id = %s",
                (connection_id, user_id),
            )
            row = cur.fetchone()
    if not row:
        return None
    result = dict(row)
    if result.get("credentials"):
        result["credentials"] = decrypt_credentials(result["credentials"])
    return result


def update_connection_org_context(connection_id: str, user_id: str, org_context: str | None) -> bool:
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE database_connections SET org_context = %s WHERE id = %s AND user_id = %s",
                (org_context, connection_id, user_id),
            )
            updated = cur.rowcount > 0
        conn.commit()
    return updated


# ---------------------------------------------------------------------------
# Google OAuth (web channel)
# ---------------------------------------------------------------------------

def get_user_by_google_id(google_id: str) -> dict | None:
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, email, name, created_at, last_login_at FROM users WHERE google_id = %s",
                (google_id,),
            )
            row = cur.fetchone()
    return dict(row) if row else None


def create_google_user(email: str, name: str, google_id: str) -> dict:
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO users (email, name, google_id) VALUES (%s, %s, %s) RETURNING id, email, name, created_at",
                (email.lower().strip(), name.strip(), google_id),
            )
            row = cur.fetchone()
        conn.commit()
    return dict(row)


def link_google_account(user_id: str, google_id: str) -> None:
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET google_id = %s WHERE id = %s", (google_id, user_id))
        conn.commit()


def create_web_oauth_state() -> str:
    state = secrets.token_urlsafe(32)
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO oauth_states (state, data) VALUES (%s, %s)",
                (state, '{"type":"web"}'),
            )
        conn.commit()
    return state


def consume_web_oauth_state(state: str) -> bool:
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM oauth_states WHERE state = %s AND data = '{\"type\":\"web\"}' AND created_at > NOW() - INTERVAL '10 minutes' RETURNING state",
                (state,),
            )
            row = cur.fetchone()
        conn.commit()
    return row is not None


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------

def create_reset_token(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM password_reset_tokens WHERE user_id = %s", (user_id,))
            cur.execute(
                "INSERT INTO password_reset_tokens (token, user_id, expires_at) VALUES (%s, %s, NOW() + INTERVAL '1 hour')",
                (token, user_id),
            )
        conn.commit()
    return token


def consume_reset_token(token: str) -> str | None:
    """Atomically validate and delete a reset token; returns user_id or None."""
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM password_reset_tokens WHERE token = %s AND expires_at > NOW() RETURNING user_id",
                (token,),
            )
            row = cur.fetchone()
        conn.commit()
    return str(row[0]) if row else None


def update_password(user_id: str, password_hash: str) -> None:
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET password_hash = %s WHERE id = %s", (password_hash, user_id))
        conn.commit()


def get_mock_connection(user_id: str) -> dict | None:
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, db_type, name, created_at FROM database_connections WHERE user_id = %s AND db_type = 'mock' LIMIT 1",
                (user_id,),
            )
            row = cur.fetchone()
    return dict(row) if row else None


def delete_connection(connection_id: str, user_id: str) -> bool:
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM database_connections WHERE id = %s AND user_id = %s",
                (connection_id, user_id),
            )
            deleted = cur.rowcount > 0
        conn.commit()
    return deleted


# ---------------------------------------------------------------------------
# Referrals
# ---------------------------------------------------------------------------

def get_or_create_referral(user_id: str) -> dict:
    """Return the referral row for a user, creating it on first call."""
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT token, use_count FROM referrals WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            if row:
                return dict(row)
            token = secrets.token_urlsafe(16)
            cur.execute(
                "INSERT INTO referrals (user_id, token) VALUES (%s, %s) RETURNING token, use_count",
                (user_id, token),
            )
            row = cur.fetchone()
        conn.commit()
    return dict(row)


def record_referral_use(token: str) -> str | None:
    """Increment use_count for a referral token; returns the referrer's user_id or None."""
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE referrals SET use_count = use_count + 1 WHERE token = %s RETURNING user_id",
                (token,),
            )
            row = cur.fetchone()
        conn.commit()
    return str(row[0]) if row else None


# ---------------------------------------------------------------------------
# Conversations / chat history
# ---------------------------------------------------------------------------

def create_conversation(
    user_id: str, connection_id: str, title: str,
    channel: str = "web",
    slack_thread_ts: str | None = None,
    slack_channel_id: str | None = None,
    slack_team_id: str | None = None,
) -> dict:
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO conversations
                   (user_id, connection_id, title, channel, slack_thread_ts, slack_channel_id, slack_team_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   RETURNING id, title, created_at""",
                (user_id, connection_id, title, channel, slack_thread_ts, slack_channel_id, slack_team_id),
            )
            row = cur.fetchone()
        conn.commit()
    return dict(row)


def get_or_create_slack_conversation(
    user_id: str, connection_id: str, title: str,
    slack_thread_ts: str, slack_channel_id: str, slack_team_id: str,
) -> dict:
    """Return existing conversation for this Slack thread, or create one."""
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT id, title, created_at FROM conversations
                   WHERE slack_thread_ts = %s AND slack_channel_id = %s AND slack_team_id = %s""",
                (slack_thread_ts, slack_channel_id, slack_team_id),
            )
            row = cur.fetchone()
            if row:
                return dict(row)
            cur.execute(
                """INSERT INTO conversations
                   (user_id, connection_id, title, channel, slack_thread_ts, slack_channel_id, slack_team_id)
                   VALUES (%s, %s, %s, 'slack', %s, %s, %s)
                   RETURNING id, title, created_at""",
                (user_id, connection_id, title, slack_thread_ts, slack_channel_id, slack_team_id),
            )
            row = cur.fetchone()
        conn.commit()
    return dict(row)


def get_conversations(user_id: str, connection_id: str) -> list[dict]:
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, title, channel, created_at FROM conversations WHERE user_id = %s AND connection_id = %s ORDER BY created_at DESC",
                (user_id, connection_id),
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_all_conversations(user_id: str) -> list[dict]:
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT c.id, c.title, c.created_at, c.connection_id,
                          dc.db_type, dc.name AS connection_name
                   FROM conversations c
                   JOIN database_connections dc ON dc.id = c.connection_id
                   WHERE c.user_id = %s
                   ORDER BY c.created_at DESC""",
                (user_id,),
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def add_messages(
    conversation_id: str,
    messages: list[dict],
) -> None:
    """Insert messages. Each dict must have 'role' and 'content'; other fields optional."""
    with _get_conn() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(
                cur,
                """INSERT INTO conversation_messages
                   (conversation_id, role, content, sql_generated, success, error_message, latency_ms)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                [
                    (
                        conversation_id,
                        m["role"],
                        m["content"],
                        m.get("sql_generated"),
                        m.get("success"),
                        m.get("error_message"),
                        m.get("latency_ms"),
                    )
                    for m in messages
                ],
            )
        conn.commit()


def get_messages(conversation_id: str, user_id: str) -> list[dict] | None:
    """Return messages for a conversation, or None if not found / not owned by user."""
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id FROM conversations WHERE id = %s AND user_id = %s",
                (conversation_id, user_id),
            )
            if not cur.fetchone():
                return None
            cur.execute(
                "SELECT role, content, sql_generated, success, error_message, latency_ms, created_at FROM conversation_messages WHERE conversation_id = %s ORDER BY created_at",
                (conversation_id,),
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Slack workspace ↔ connection linking
# ---------------------------------------------------------------------------

def get_connection_by_id(connection_id: str) -> dict | None:
    """Internal lookup without user ownership check (used by Slack handler)."""
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, db_type, name, credentials, org_context FROM database_connections WHERE id = %s",
                (connection_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    result = dict(row)
    if result.get("credentials"):
        result["credentials"] = decrypt_credentials(result["credentials"])
    return result


def store_slack_oauth_state(state: str, user_id: str) -> None:
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM slack_oauth_states WHERE created_at < NOW() - INTERVAL '10 minutes'",
            )
            cur.execute(
                "INSERT INTO slack_oauth_states (state, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (state, user_id),
            )
        conn.commit()


def consume_slack_oauth_state(state: str) -> str | None:
    """Return user_id and delete the state row (one-time use)."""
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "DELETE FROM slack_oauth_states WHERE state = %s RETURNING user_id",
                (state,),
            )
            row = cur.fetchone()
        conn.commit()
    return str(row["user_id"]) if row else None


def upsert_slack_workspace(
    workspace_id: str, team_name: str, bot_token: str,
    installed_by: str, bot_user_id: str | None = None,
    connection_id: str | None = None,
) -> dict:
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO slack_workspaces (workspace_id, team_name, bot_token, bot_user_id, connection_id, installed_by)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (workspace_id) DO UPDATE
                    SET team_name    = EXCLUDED.team_name,
                        bot_token    = EXCLUDED.bot_token,
                        bot_user_id  = COALESCE(EXCLUDED.bot_user_id, slack_workspaces.bot_user_id),
                        installed_by = EXCLUDED.installed_by
                RETURNING workspace_id, team_name, connection_id
            """, (workspace_id, team_name, bot_token, bot_user_id, connection_id, installed_by))
            row = cur.fetchone()
        conn.commit()
    return dict(row)


def get_slack_workspaces_by_user(user_id: str) -> list[dict]:
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT workspace_id, team_name, connection_id FROM slack_workspaces WHERE installed_by = %s ORDER BY created_at",
                (user_id,),
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_slack_workspace(workspace_id: str) -> dict | None:
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT workspace_id, team_name, bot_token, bot_user_id, connection_id, installed_by FROM slack_workspaces WHERE workspace_id = %s",
                (workspace_id,),
            )
            row = cur.fetchone()
    return dict(row) if row else None


def get_slack_workspace_by_connection(connection_id: str) -> dict | None:
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT workspace_id, team_name, connection_id FROM slack_workspaces WHERE connection_id = %s",
                (connection_id,),
            )
            row = cur.fetchone()
    return dict(row) if row else None


def link_slack_workspace_to_connection(workspace_id: str, connection_id: str | None, user_id: str) -> bool:
    """Link (or unlink) a workspace to a connection. Verifies the connection belongs to user."""
    with _get_conn() as conn:
        with conn.cursor() as cur:
            if connection_id:
                cur.execute(
                    "SELECT 1 FROM database_connections WHERE id = %s AND user_id = %s",
                    (connection_id, user_id),
                )
                if not cur.fetchone():
                    return False
            cur.execute(
                "UPDATE slack_workspaces SET connection_id = %s WHERE workspace_id = %s AND installed_by = %s",
                (connection_id, workspace_id, user_id),
            )
            updated = cur.rowcount > 0
        conn.commit()
    return updated


def delete_slack_workspace_by_connection(connection_id: str, user_id: str) -> bool:
    """Unlink a workspace from a connection (sets connection_id to NULL)."""
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE slack_workspaces SET connection_id = NULL
                WHERE connection_id = %s
                  AND installed_by = %s
            """, (connection_id, user_id))
            updated = cur.rowcount > 0
        conn.commit()
    return updated


# ---------------------------------------------------------------------------
# BigQuery OAuth
# ---------------------------------------------------------------------------

def create_bq_oauth_state(user_id: str, connection_id: str) -> str:
    state = secrets.token_urlsafe(32)
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM oauth_states WHERE created_at < NOW() - INTERVAL '10 minutes'",
            )
            cur.execute(
                "INSERT INTO oauth_states (state, data) VALUES (%s, %s)",
                (state, json.dumps({"type": "bigquery", "user_id": user_id, "connection_id": connection_id})),
            )
        conn.commit()
    return state


def consume_bq_oauth_state(state: str) -> dict | None:
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM oauth_states WHERE state = %s AND data::jsonb->>'type' = 'bigquery' AND created_at > NOW() - INTERVAL '10 minutes' RETURNING data",
                (state,),
            )
            row = cur.fetchone()
        conn.commit()
    return json.loads(row[0]) if row else None


def store_user_google_token(user_id: str, access_token: str, refresh_token: str | None) -> None:
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO user_google_tokens (user_id, access_token, refresh_token, updated_at)
                   VALUES (%s, %s, %s, NOW())
                   ON CONFLICT (user_id) DO UPDATE
                       SET access_token  = EXCLUDED.access_token,
                           refresh_token = COALESCE(EXCLUDED.refresh_token, user_google_tokens.refresh_token),
                           updated_at    = NOW()""",
                (user_id, access_token, refresh_token),
            )
        conn.commit()


def get_user_google_token(user_id: str) -> dict | None:
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT access_token, refresh_token FROM user_google_tokens WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
    return dict(row) if row else None
