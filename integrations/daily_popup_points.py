"""
把 /points 放进 Daily Popup Bot
================================
Daily Popup Bot 和 Chat Battle Bot 共用同一个 Supabase，
所以 Daily Popup Bot 只要调用 cb_my_stats 就能查到分数，不需要再统计。

用法（Daily Popup Bot 是 python-telegram-bot 的话）：
1. 把这个文件复制到 Daily Popup Bot 的项目里
2. Daily Popup Bot 的 Railway Variables 加上：
     SUPABASE_URL, SUPABASE_SERVICE_KEY, TZ_NAME=Asia/Kuala_Lumpur, ROLLOVER_TIME=10:30
   （和 Chat Battle Bot 用一样的值）
3. 在 Daily Popup Bot 的 main() 里加一行：
     from daily_popup_points import register_points
     register_points(app)

如果 Daily Popup Bot 是 Node.js，直接调用 Supabase RPC 即可：
     supabase.rpc('cb_my_stats', { p_event: '2026-10-26', p_day: '2026-10-28', p_user: 123456 })
   p_event = 本期开始的周一日期（周一 10:30 之前算上一期），p_day = 今天（马来西亚时间）。
"""
import asyncio
import html
import os
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from supabase import create_client
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

_TZ = ZoneInfo(os.getenv("TZ_NAME", "Asia/Kuala_Lumpur"))
_h, _m = os.getenv("ROLLOVER_TIME", "10:30").split(":")
_ROLL = time(int(_h), int(_m))
_sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])


def _event_and_day():
    now = datetime.now(_TZ)
    monday = (now - timedelta(days=now.weekday())).date()
    if now < datetime.combine(monday, _ROLL, _TZ):
        monday -= timedelta(days=7)
    return monday, now.date()


def _stats(user_id: int) -> dict:
    ev, day = _event_and_day()
    return _sb.rpc("cb_my_stats", {
        "p_event": ev.isoformat(), "p_day": day.isoformat(), "p_user": user_id,
    }).execute().data or {}


async def cmd_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    s = await asyncio.to_thread(_stats, user.id)
    if s.get("disqualified"):
        text = "❌ 你本期【终极聊天争霸赛】资格已取消（违规发送链接 / 二维码）"
    else:
        today = s.get("today", 0)
        rank = s.get("rank")
        tip = (f"再聊 {5 - today} 条完成5条任务 +5" if today < 5 else
               f"再聊 {10 - today} 条完成10条任务 +10" if today < 10 else
               "今日任务全部完成，继续聊天每条 +1")
        text = (f"🏆 <b>终极聊天争霸赛</b>\n👤 {html.escape(user.full_name)}\n"
                f"⭐ 本期积分：<b>{s.get('points', 0)}</b> 分\n"
                f"📊 排名：{'#' + str(rank) if rank else '未上榜'}\n"
                f"💬 今日有效发言：{today} 条\n🎯 {tip}")
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


def register_points(app: Application):
    app.add_handler(CommandHandler(["points", "score"], cmd_points))
