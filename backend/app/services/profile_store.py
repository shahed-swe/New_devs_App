"""
Local Postgres persistence for user profiles, preferences and notification
preferences. The Supabase client runs in Challenge Mode (mock) in this
environment, so profile data is stored in the local database instead.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

import asyncpg

from ..config import settings

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None
_pool_lock = asyncio.Lock()

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS user_profiles (
    id TEXT PRIMARY KEY,
    user_id TEXT UNIQUE NOT NULL,
    display_name TEXT,
    bio TEXT,
    phone TEXT,
    department TEXT,
    job_title TEXT,
    location TEXT,
    timezone TEXT NOT NULL DEFAULT 'UTC',
    language TEXT NOT NULL DEFAULT 'en',
    theme TEXT NOT NULL DEFAULT 'light',
    avatar_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_preferences (
    id TEXT PRIMARY KEY,
    user_id TEXT UNIQUE NOT NULL,
    notification_email BOOLEAN NOT NULL DEFAULT TRUE,
    notification_push BOOLEAN NOT NULL DEFAULT TRUE,
    notification_desktop BOOLEAN NOT NULL DEFAULT TRUE,
    notification_sound BOOLEAN NOT NULL DEFAULT TRUE,
    auto_refresh BOOLEAN NOT NULL DEFAULT TRUE,
    compact_view BOOLEAN NOT NULL DEFAULT FALSE,
    sidebar_collapsed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS notification_preferences (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    category TEXT NOT NULL,
    email_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    push_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    desktop_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    sound_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, category)
);
"""

PROFILE_FIELDS = {
    "display_name", "bio", "phone", "department", "job_title",
    "location", "timezone", "language", "theme", "avatar_url",
}

PREFERENCE_FIELDS = {
    "notification_email", "notification_push", "notification_desktop",
    "notification_sound", "auto_refresh", "compact_view", "sidebar_collapsed",
}

NOTIFICATION_FIELDS = {
    "email_enabled", "push_enabled", "desktop_enabled", "sound_enabled",
}


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        async with _pool_lock:
            if _pool is None:
                pool = await asyncpg.create_pool(
                    settings.database_url, min_size=1, max_size=5
                )
                async with pool.acquire() as conn:
                    await conn.execute(SCHEMA_SQL)
                logger.info("Profile store initialized against local Postgres")
                _pool = pool
    return _pool


def _default_display_name(email: Optional[str]) -> str:
    return email.split("@")[0] if email else "User"


async def _ensure_profile_row(conn: asyncpg.Connection, user_id: str, email: Optional[str]) -> None:
    await conn.execute(
        """
        INSERT INTO user_profiles (id, user_id, display_name)
        VALUES ('profile-' || $1, $1, $2)
        ON CONFLICT (user_id) DO NOTHING
        """,
        user_id,
        _default_display_name(email),
    )


async def _ensure_preferences_row(conn: asyncpg.Connection, user_id: str) -> None:
    await conn.execute(
        """
        INSERT INTO user_preferences (id, user_id)
        VALUES ('prefs-' || $1, $1)
        ON CONFLICT (user_id) DO NOTHING
        """,
        user_id,
    )


async def get_profile(user_id: str) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM user_profiles WHERE user_id = $1", user_id
        )
        return dict(row) if row else None


async def get_preferences(user_id: str) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM user_preferences WHERE user_id = $1", user_id
        )
        return dict(row) if row else None


async def get_notification_preferences(user_id: str) -> List[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM notification_preferences WHERE user_id = $1 ORDER BY category",
            user_id,
        )
        return [dict(row) for row in rows]


def _build_set_clause(updates: Dict[str, Any], allowed: set, start_index: int):
    sets, values = [], []
    index = start_index
    for field, value in updates.items():
        if field not in allowed:
            continue
        sets.append(f"{field} = ${index}")
        values.append(value)
        index += 1
    return sets, values


async def update_profile(user_id: str, email: Optional[str], updates: Dict[str, Any]) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _ensure_profile_row(conn, user_id, email)
        sets, values = _build_set_clause(updates, PROFILE_FIELDS, 2)
        if sets:
            await conn.execute(
                f"UPDATE user_profiles SET {', '.join(sets)}, updated_at = NOW() WHERE user_id = $1",
                user_id,
                *values,
            )
        row = await conn.fetchrow(
            "SELECT * FROM user_profiles WHERE user_id = $1", user_id
        )
        return dict(row)


async def update_preferences(user_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _ensure_preferences_row(conn, user_id)
        sets, values = _build_set_clause(updates, PREFERENCE_FIELDS, 2)
        if sets:
            await conn.execute(
                f"UPDATE user_preferences SET {', '.join(sets)}, updated_at = NOW() WHERE user_id = $1",
                user_id,
                *values,
            )
        row = await conn.fetchrow(
            "SELECT * FROM user_preferences WHERE user_id = $1", user_id
        )
        return dict(row)


async def update_notification_preference(
    user_id: str, category: str, updates: Dict[str, Any]
) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO notification_preferences (id, user_id, category)
            VALUES ($1 || ':' || $2, $1, $2)
            ON CONFLICT (user_id, category) DO NOTHING
            """,
            user_id,
            category,
        )
        sets, values = _build_set_clause(updates, NOTIFICATION_FIELDS, 3)
        if sets:
            await conn.execute(
                f"UPDATE notification_preferences SET {', '.join(sets)}, updated_at = NOW() "
                "WHERE user_id = $1 AND category = $2",
                user_id,
                category,
                *values,
            )
        row = await conn.fetchrow(
            "SELECT * FROM notification_preferences WHERE user_id = $1 AND category = $2",
            user_id,
            category,
        )
        return dict(row)


async def set_avatar_url(user_id: str, email: Optional[str], avatar_url: Optional[str]) -> Dict[str, Any]:
    return await update_profile(user_id, email, {"avatar_url": avatar_url})
