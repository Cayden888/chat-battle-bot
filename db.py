"""Supabase 调用（全部通过 schema.sql 里的 RPC 函数，计分是原子操作）。"""
import asyncio
from datetime import date, datetime, timezone

from supabase import create_client, Client

import config

_client: Client | None = None


def client() -> Client:
    global _client
    if _client is None:
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
    return _client


def _rpc(fn: str, params: dict):
    return client().rpc(fn, params).execute().data


async def rpc(fn: str, params: dict):
    # supabase-py 是同步的，丢到线程里跑，避免卡住 Bot
    return await asyncio.to_thread(_rpc, fn, params)


async def record_message(event: date, day: date, user, content_hash: str) -> dict:
    return await rpc("cb_record_message", {
        "p_event": event.isoformat(),
        "p_day": day.isoformat(),
        "p_user": user.id,
        "p_username": user.username,
        "p_name": user.full_name,
        "p_hash": content_hash,
        "p_min_interval": config.MIN_INTERVAL_SEC,
    })


async def disqualify(event: date, user_id: int, username, name, kind: str, action: str, snippet: str):
    await rpc("cb_disqualify", {
        "p_event": event.isoformat(), "p_user": user_id,
        "p_username": username, "p_name": name,
        "p_kind": kind, "p_action": action, "p_snippet": snippet or "",
    })


async def flag(event: date, user_id: int, username, name, kind: str, snippet: str) -> int:
    return await rpc("cb_flag", {
        "p_event": event.isoformat(), "p_user": user_id,
        "p_username": username, "p_name": name,
        "p_kind": kind, "p_snippet": snippet or "",
    }) or 1


async def undq(event: date, user_id: int):
    await rpc("cb_undq", {"p_event": event.isoformat(), "p_user": user_id})


async def leaderboard(event: date, limit: int) -> list[dict]:
    return await rpc("cb_leaderboard", {"p_event": event.isoformat(), "p_limit": limit}) or []


async def my_stats(event: date, day: date, user_id: int) -> dict:
    return await rpc("cb_my_stats", {
        "p_event": event.isoformat(), "p_day": day.isoformat(), "p_user": user_id,
    }) or {}


async def lifetime_valid(user_id: int) -> int:
    def _q():
        r = client().table("cb_users").select("lifetime_valid").eq("user_id", user_id).execute().data
        return r[0]["lifetime_valid"] if r else 0
    return await asyncio.to_thread(_q)


async def find_by_username(username: str) -> list[dict]:
    """用 @username 找玩家（不分大小写）。只找得到在群里发过言 / 被记录过的人。"""
    name = username.lstrip("@").strip()
    def _q():
        return client().table("cb_users").select("user_id, username, full_name") \
            .ilike("username", name).limit(5).execute().data or []
    return await asyncio.to_thread(_q)


async def get_setting(key: str, default: str | None = None) -> str | None:
    def _q():
        r = client().table("cb_settings").select("value").eq("key", key).execute().data
        return r[0]["value"] if r else default
    return await asyncio.to_thread(_q)


async def set_setting(key: str, value: str, by: int | None = None):
    def _q():
        client().table("cb_settings").upsert(
            {"key": key, "value": value, "updated_by": by,
             "updated_at": datetime.now(timezone.utc).isoformat()}).execute()
    await asyncio.to_thread(_q)
