"""
终极聊天争霸赛 THE ULTIMATE CHAT BATTLE — Telegram Bot
Python 3.11 + python-telegram-bot 21 + Supabase，部署在 Railway（worker，长轮询）
"""
import csv
import html
import io
import logging
import re
import time as _time
from datetime import datetime, timedelta

from telegram import Update, Message, User, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatType
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters,
)

import config
import db
from msg_filters import check_valid, content_hash, has_link

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("chatbattle")

try:
    import cv2
    import numpy as np
    _QR = cv2.QRCodeDetector()
except Exception:            # 没装 opencv 就跳过 QR 检测
    _QR = None


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------
_admin_cache: dict[int, tuple[float, set[int]]] = {}


async def is_admin(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> bool:
    if user_id in config.ADMIN_IDS or user_id in config.REVIEWER_IDS:
        return True
    if chat_id > 0:
        return False
    ts, ids = _admin_cache.get(chat_id, (0.0, set()))
    if _time.time() - ts > 600:
        try:
            admins = await context.bot.get_chat_administrators(chat_id)
            ids = {a.user.id for a in admins}
            _admin_cache[chat_id] = (_time.time(), ids)
        except Exception as e:
            log.warning("get admins failed: %s", e)
    return user_id in ids


def in_event_group(update: Update) -> bool:
    chat = update.effective_chat
    return chat is not None and chat.type in (ChatType.GROUP, ChatType.SUPERGROUP) \
        and (not config.GROUP_IDS or chat.id in config.GROUP_IDS)


def display_name(row: dict) -> str:
    name = (row.get("full_name") or "").strip() or "玩家"
    if len(name) > 16:
        name = name[:16] + "…"
    return html.escape(name)


def mention(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{name}</a>'


async def send_log(context: ContextTypes.DEFAULT_TYPE, text: str):
    if config.LOG_CHAT_ID:
        try:
            await context.bot.send_message(config.LOG_CHAT_ID, text, parse_mode=ParseMode.HTML)
        except Exception as e:
            log.warning("log send failed: %s", e)




# --------------------------------------------------------------------------
# 自动删除：Bot 在群里的回复过一段时间自动删掉（时间在 config.py / Railway Variables 设）
# --------------------------------------------------------------------------
async def _delete_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id, message_ids = context.job.data
    for mid in message_ids:
        try:
            await context.bot.delete_message(chat_id, mid)
        except Exception:
            pass


def _delete_seconds(kind: str) -> int:
    return {
        "congrats": config.CONGRATS_DELETE_SEC,
        "warning": config.WARNING_DELETE_SEC,
        "keep": 0,
    }.get(kind, config.REPLY_DELETE_SEC)


# 玩家用来叫 Bot 的中文关键字（和指令一样，会被一起自动删除）
TEXT_TRIGGERS = re.compile(r"^\s*(分数|积分|查分|我的分数|我的积分|任务|今日任务|我的任务)\s*$")


def _is_trigger(text: str | None) -> bool:
    return bool(text) and (text.startswith("/") or bool(TEXT_TRIGGERS.match(text)))


async def reply(context, msg: Message, text: str, kind: str = "reply", **kw):
    """所有群里的回复都走这里。
    kind: congrats（恭喜）/ reply（一般指令）/ warning（违规、dq、undq）/ keep（/topX /rulesX，不删）"""
    m = await msg.reply_text(text, **kw)
    if m.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP) or not context.job_queue:
        return m
    secs = _delete_seconds(kind)
    if secs > 0:
        context.job_queue.run_once(_delete_job, secs, data=(m.chat_id, [m.message_id]))
    # 玩家 / 审核人员打的指令本身（/points、分数、/topX…）也删掉，保持群干净
    if (config.DELETE_COMMAND_MSG and kind in ("reply", "keep") and _is_trigger(msg.text)
            and config.REPLY_DELETE_SEC > 0):
        context.job_queue.run_once(_delete_job, config.REPLY_DELETE_SEC, data=(msg.chat_id, [msg.message_id]))
    return m


# --------------------------------------------------------------------------
# 活动开关：/eventstart /eventend（只有审核人员 / 管理员）
# 关闭时：不计分、不抓链接、玩家的 /points /quest /top /rules / 分数 / 任务 都不能用、周一不自动发名单
# 状态存在 Supabase（cb_settings），Bot 重启也会记得
# --------------------------------------------------------------------------
EVENT_ON = True
CLOSED_TEXT = "⏸ 【终极聊天争霸赛】目前没有进行中，等活动开始后再来哦！"


async def load_event_state(app=None):
    global EVENT_ON
    try:
        EVENT_ON = (await db.get_setting("event_on", "1")) != "0"
    except Exception as e:
        log.warning("读取活动开关失败（是否跑了 add_event_switch.sql？），先当作开启: %s", e)
        EVENT_ON = True
    log.info("活动状态: %s", "进行中" if EVENT_ON else "已结束")


async def player_allowed(update: Update, context) -> bool:
    """活动关闭时，玩家指令一律回复「没有进行中」；审核人员 / 管理员不受影响。"""
    if EVENT_ON:
        return True
    if await is_admin(context, update.effective_chat.id, update.effective_user.id):
        return True
    await reply(context, update.effective_message, CLOSED_TEXT)
    return False


async def _announce(context, text: str):
    for gid in config.GROUP_IDS:
        try:
            await context.bot.send_message(gid, text, parse_mode=ParseMode.HTML)
        except Exception as e:
            log.warning("announce to %s failed: %s", gid, e)


async def cmd_event_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global EVENT_ON
    if not await _require_admin(update, context):
        return
    if EVENT_ON:
        return await reply(context, update.effective_message, "活动本来就在进行中 ✅", kind="keep")
    await db.set_setting("event_on", "1", update.effective_user.id)
    EVENT_ON = True
    await reply(context, update.effective_message, "✅ 活动已开始，计分和所有指令恢复。", kind="keep")
    if config.ANNOUNCE_EVENT_SWITCH:
        await _announce(context, "🏁 <b>终极聊天争霸赛 开始啦！</b>\n从现在起在群里聊天就能拿积分，输入 /rules 查看规则。")


async def cmd_event_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global EVENT_ON
    if not await _require_admin(update, context):
        return
    if not EVENT_ON:
        return await reply(context, update.effective_message, "活动本来就是结束状态 ⏸", kind="keep")
    await db.set_setting("event_on", "0", update.effective_user.id)
    EVENT_ON = False
    await reply(context, update.effective_message,
                "⏸ 活动已结束：停止计分，玩家指令暂停。\n积分会保留，/eventstart 重新开始。\n"
                "需要名单的话打 /report", kind="keep")
    if config.ANNOUNCE_EVENT_SWITCH:
        await _announce(context, "⏸ <b>终极聊天争霸赛 已结束</b>\n现在聊天不会再计分，感谢大家参与！")


async def cmd_event_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/eventreset → 本周清零；/eventreset all → 全部清零（测试用）。都要按按钮确认。"""
    if not await _require_admin(update, context):
        return
    all_weeks = bool(context.args) and context.args[0].lower() == "all"
    event = config.current_event()
    if all_weeks:
        text = ("⚠️ <b>确定要全部清零吗？</b>\n\n会删除<b>所有周</b>的积分、任务、违规记录和玩家资料，"
                "之前所有名单都拿不回来。\n（适合测试完、正式开始前用）\n\n清零前会先把本周名单发给你备份。")
    else:
        start, end = config.event_range(event)
        text = (f"⚠️ <b>确定要把本周清零吗？</b>\n本周：{start:%d/%m %H:%M} – {end:%d/%m %H:%M}\n\n"
                "所有人本周积分、今日任务、重复记录、违规记录、取消资格都会归零。\n"
                "以前几周的资料<b>不受影响</b>。\n\n清零前会先把本周名单发给你备份。")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🗑 确定清零", callback_data=f"rst:{event:%Y%m%d}:{'all' if all_weeks else 'wk'}"),
        InlineKeyboardButton("取消", callback_data="rst:cancel"),
    ]])
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def on_reset_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    u = q.from_user
    if not (u.id in config.REVIEWER_IDS | config.ADMIN_IDS
            or await is_admin(context, q.message.chat.id, u.id)):
        return await q.answer("只有审核人员 / 管理员可以操作", show_alert=True)
    parts = q.data.split(":")
    if parts[1] == "cancel":
        await q.answer("已取消")
        return await q.edit_message_text("已取消，没有清零。")
    event = datetime.strptime(parts[1], "%Y%m%d").date()
    all_weeks = parts[2] == "all"
    if event != config.current_event():
        await q.answer("这个按钮已过期", show_alert=True)
        return await q.edit_message_text("按钮已过期（已经换周），请重新打 /eventreset。")
    await q.answer("清零中…")
    # 1) 先备份：本周名单私讯给按按钮的人
    try:
        await send_report(context, event, chat_id=u.id, announce=False)
    except Exception as e:
        log.warning("reset backup failed: %s", e)
    # 2) 清零
    try:
        r = await db.reset(event, all_weeks)
    except Exception as e:
        log.exception("reset failed")
        return await q.edit_message_text(
            f"❌ 清零失败：<code>{html.escape(str(e)[:200])}</code>\n"
            "（是否已在 Supabase 跑 add_reset.sql？）", parse_mode=ParseMode.HTML)
    who = f"@{u.username}" if u.username else u.full_name
    scope = "全部资料" if all_weeks else "本周积分"
    await q.edit_message_text(
        f"✅ 已清零{scope}（{r.get('players', 0)} 位玩家）— {html.escape(who)}\n"
        f"清零前的名单已私讯给你备份。", parse_mode=ParseMode.HTML)
    log.info("RESET %s by %s: %s", "ALL" if all_weeks else event, u.id, r)
    await send_log(context, f"🗑 <b>{scope}已清零</b> — {html.escape(who)} (<code>{u.id}</code>)")


async def cmd_event_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_admin(update, context):
        return
    await reply(context, update.effective_message,
                f"活动状态：{'✅ 进行中' if EVENT_ON else '⏸ 已结束'}", kind="keep")


# --------------------------------------------------------------------------
# 违规处理：发 Link / QR
# --------------------------------------------------------------------------
REASONS = {
    "link": ("发送链接",
             "在群内发送了网址 / Telegram 链接。活动规则：发送链接属于违规，"
             "可取消本期【终极聊天争霸赛】资格（防止广告、钓鱼）。"),
    "qr": ("发送二维码",
           "在群内发送了含二维码的图片。活动规则：发送二维码属于违规，"
           "可取消本期【终极聊天争霸赛】资格（二维码常被用来钓鱼 / 引流）。"),
}


def message_link(chat, message_id: int) -> str | None:
    if chat.username:
        return f"https://t.me/{chat.username}/{message_id}"
    s = str(chat.id)
    if s.startswith("-100"):
        return f"https://t.me/c/{s[4:]}/{message_id}"
    return None


async def flag_violation(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str, snippet: str):
    """不删消息、不 Ban、不自动取消资格：
    1) 在群里发警告  2) 把详情 + 原因私讯给审核人员，由审核人员按按钮决定。"""
    msg, user, chat = update.effective_message, update.effective_user, update.effective_chat
    event = config.current_event()
    label, why = REASONS.get(kind, (kind, "违反活动规则。"))
    name = mention(user.id, html.escape(user.full_name))

    try:
        warn_count = await db.flag(event, user.id, user.username, user.full_name, kind, snippet)
        history = await db.lifetime_valid(user.id)
        stats = await db.my_stats(event, config.today(), user.id)
    except Exception as e:
        log.exception("flag failed: %s", e)
        warn_count, history, stats = 1, 0, {}

    # 1) 群警告（记住这条警告的位置，审核人员按「忽略」时会把它删掉）
    warn_ref = ""
    try:
        wm = await reply(context, msg,
            f"⚠️ {name} 请勿在群内{label}。\n"
            f"这违反了【终极聊天争霸赛】规则，已提交管理员审核，"
            f"可能会被取消本期活动资格。（本期第 {warn_count} 次警告）",
            kind="warning", parse_mode=ParseMode.HTML)
        warn_ref = f":{wm.chat_id}:{wm.message_id}"
    except Exception as e:
        log.warning("group warning failed: %s", e)

    # 2) 私讯审核人员
    link = message_link(chat, msg.message_id)
    hint = ""
    if history < config.NEWBIE_THRESHOLD:
        hint = f"\n🎣 <b>疑似钓鱼号</b>：之前只有 {history} 条有效发言就{label}，建议管理员在群里手动处理。"
    status = "（已被取消资格）" if stats.get("disqualified") else ""
    report = (
        f"🚨 <b>终极聊天争霸赛 · 违规审核</b>\n\n"
        f"👤 玩家：{name}{status}\n"
        f"🆔 ID：<code>{user.id}</code>\n"
        f"🔗 Username：@{html.escape(user.username) if user.username else '-'}\n"
        f"👥 群：{html.escape(chat.title or str(chat.id))}\n"
        f"⭐ 本期积分：{stats.get('points', 0)} 分  |  排名：{('#' + str(stats['rank'])) if stats.get('rank') else '未上榜'}\n"
        f"🔁 本期违规次数：{warn_count}\n\n"
        f"❗ <b>为什么可能被取消资格：</b>\n{why}{hint}\n\n"
        f"📝 内容：<code>{html.escape((snippet or '')[:300])}</code>"
        + (f'\n📎 <a href="{link}">查看原消息</a>' if link else "")
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ 取消本期资格", callback_data=f"dq:{event:%Y%m%d}:{user.id}{warn_ref}"),
        InlineKeyboardButton("✅ 忽略", callback_data=f"ok:{event:%Y%m%d}:{user.id}{warn_ref}"),
    ]])
    targets = list(config.REVIEWER_IDS) + ([config.LOG_CHAT_ID] if config.LOG_CHAT_ID else [])
    for t in targets:
        try:
            await context.bot.send_message(t, report, parse_mode=ParseMode.HTML,
                                           reply_markup=kb, disable_web_page_preview=True)
        except Exception as e:
            log.warning("report to %s failed（审核人员要先私讯 Bot 按 /start）: %s", t, e)


async def on_review_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    reviewer = q.from_user
    if reviewer.id not in config.REVIEWER_IDS | config.ADMIN_IDS:
        return await q.answer("只有审核人员可以操作", show_alert=True)
    try:
        parts = q.data.split(":")
        action, ev, uid = parts[0], parts[1], int(parts[2])
        event = datetime.strptime(ev, "%Y%m%d").date()
        # 群警告的位置（旧的报告按钮没有这个资料）
        warn_chat, warn_msg = (int(parts[3]), int(parts[4])) if len(parts) >= 5 else (None, None)
    except Exception:
        return await q.answer("按钮数据错误", show_alert=True)

    who = f"@{reviewer.username}" if reviewer.username else reviewer.full_name
    if action == "dq":
        await db.disqualify(event, uid, None, None, "reviewed", f"dq_by_{reviewer.id}", "")
        result = f"\n\n❌ <b>已取消本期资格</b> — {html.escape(who)}"
        await q.answer("已取消资格")
    else:
        result = f"\n\n✅ <b>已忽略</b> — {html.escape(who)}"
        # 忽略 = 不算违规，把群里那条 ⚠️ 警告删掉
        if warn_chat and warn_msg:
            try:
                await context.bot.delete_message(warn_chat, warn_msg)
                result += "\n🗑 群里的警告已删除"
            except Exception as e:
                log.warning("delete warning failed: %s", e)
                result += "\n⚠️ 群里的警告删不掉（可能已被删除，或超过 48 小时），请手动删除"
        await q.answer("已忽略")
    try:
        await q.edit_message_text(q.message.text_html + result, parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception:
        pass


def _decode_qr(data: bytes) -> str | None:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    text, points, _ = _QR.detectAndDecode(img)
    if text:
        return text
    return "QR" if points is not None and len(points) else None


async def check_photo_qr(msg: Message, context) -> str | None:
    if not (_QR and config.QR_CHECK):
        return None
    try:
        photo = msg.photo[-1] if msg.photo else None
        doc = msg.document if msg.document and (msg.document.mime_type or "").startswith("image/") else None
        target = photo or doc
        if not target or (target.file_size or 0) > 8_000_000:
            return None
        f = await context.bot.get_file(target.file_id)
        data = bytes(await f.download_as_bytearray())
        import asyncio
        return await asyncio.to_thread(_decode_qr, data)
    except Exception as e:
        log.warning("qr check failed: %s", e)
        return None


# --------------------------------------------------------------------------
# 主逻辑：群消息
# --------------------------------------------------------------------------
async def on_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not EVENT_ON:
        return
    if not in_event_group(update):
        log.info("skip: chat %s (%s) 不在 GROUP_IDS=%s", chat.id if chat else None,
                 chat.type if chat else None, config.GROUP_IDS)
        return
    msg, user = update.effective_message, update.effective_user
    if not user or user.is_bot or msg.sender_chat:          # 频道/匿名管理员发言不算
        return

    text = msg.text or msg.caption or ""
    entities = (msg.entities or ()) + (msg.caption_entities or ())
    admin = await is_admin(context, msg.chat_id, user.id)

    # 1) Link / QR —— 管理员豁免
    if not admin:
        if has_link(text, entities):
            return await flag_violation(update, context, "link", text)
        if msg.photo or msg.document:
            qr = await check_photo_qr(msg, context)
            if qr:
                return await flag_violation(update, context, "qr", f"[QR] {qr}")

    # 2) 计分：只算普通文字（转发、贴纸、纯图片不算；管理员不参加）
    if admin or not text or msg.forward_origin or text.startswith("/"):
        log.info("skip: user %s admin=%s text=%s forward=%s", user.id, admin, bool(text), bool(msg.forward_origin))
        return
    ok, reason, norm = check_valid(text)
    if not ok:
        log.info("skip: user %s 无效发言 (%s)", user.id, reason)
        return

    try:
        res = await db.record_message(config.current_event(), config.today(), user, content_hash(norm))
    except Exception as e:
        log.exception("record failed: %s", e)
        return

    log.info("user %s → %s", user.id, res)
    if res.get("status") == "ok" and res.get("bonus"):
        daily = res["daily"]
        if daily == 5:
            t = f"🎯 {mention(user.id, html.escape(user.first_name))} 完成今日 5 条有效发言任务，+5 分！"
        else:
            t = (f"🔥 {mention(user.id, html.escape(user.first_name))} 完成今日 10 条有效发言任务 +5，"
                 f"全部任务达成再 +5！当前 {res['points']} 分")
        try:
            await reply(context, msg, t, kind="congrats", parse_mode=ParseMode.HTML, disable_notification=True)
        except Exception:
            pass


# --------------------------------------------------------------------------
# 指令
# --------------------------------------------------------------------------
def format_stats(user: User, s: dict) -> str:
    event = config.current_event()
    start, end = config.event_range(event)
    lines = [f"🏆 <b>终极聊天争霸赛</b>  {start:%d/%m} – {end:%d/%m}",
             f"👤 {html.escape(user.full_name)}"]
    if s.get("disqualified"):
        lines.append("❌ 本期资格已取消（违规发送链接 / 二维码）")
        return "\n".join(lines)
    today = s.get("today", 0)
    rank = s.get("rank")
    lines += [
        f"⭐ 本期积分：<b>{s.get('points', 0)}</b> 分",
        f"📊 当前排名：<b>#{rank}</b>" if rank else "📊 当前排名：未上榜",
        f"💬 今日有效发言：{today} 条",
    ]
    if today < 5:
        lines.append(f"🎯 再聊 {5 - today} 条完成【5条任务】+5 分")
    elif today < 10:
        lines.append(f"🎯 再聊 {10 - today} 条完成【10条任务】+5，并解锁【全部任务】+5")
    else:
        lines.append("✅ 今日任务全部完成！继续聊天每条 +1 分（无上限）")
    if rank and rank <= config.TOP_N:
        lines.append(f"🔥 你在 Top {config.TOP_N} 内，保持住！")
    return "\n".join(lines)


async def cmd_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await player_allowed(update, context):
        return
    user, msg = update.effective_user, update.effective_message
    s = await db.my_stats(config.current_event(), config.today(), user.id)
    await reply(context, msg, format_stats(user, s), parse_mode=ParseMode.HTML)


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str = "reply"):
    if kind == "reply" and not await player_allowed(update, context):
        return
    msg = update.effective_message
    rows = await db.leaderboard(config.current_event(), 10)
    if not rows:
        text = "🏆 本期还没有人上榜，快来聊天抢第一！"
    else:
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        body = "\n".join(f"{medals.get(r['rank'], str(r['rank']) + '.')} {display_name(r)} — {r['points']} 分"
                         for r in rows)
        text = f"🏆 <b>终极聊天争霸赛 · 实时 Top 10</b>\n\n{body}\n\n输入 /points 查看自己的分数"
    await reply(context, msg, text, kind=kind, parse_mode=ParseMode.HTML)


RULES = (
    "🏆 <b>终极聊天争霸赛 THE ULTIMATE CHAT BATTLE</b>\n"
    "⏰ 每周一 {roll} 至下周一 {roll}，周一 {rep} 公布结果\n\n"
    "<b>积分方式</b>\n"
    "1. 每条有效发言 +1 分\n"
    "2. 每天发送 5 条有效消息 +5 分\n"
    "3. 每天发送 10 条有效消息 额外 +5 分\n"
    "4. 完成以上全部任务 额外 +5 分\n"
    "分数没有上限！\n\n"
    "🎁 积分 Top {n} 各得 {prize}（需有 {turn} 流水才能领取）\n\n"
    "✅ 和群友轻松聊天、参与讨论、分享心得\n"
    "❌ 重复内容 / 只发表情或符号 / 单个字 / 纯数字 / 刷屏 / 转发 / 贴纸图片 不计分\n"
    "🚫 发链接、二维码会被警告，经审核可能取消本期资格\n\n"
    "输入 /points 查看分数，/quest 查看今日任务，/top 查看排行榜"
)


async def cmd_rules(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str = "reply"):
    if kind == "reply" and not await player_allowed(update, context):
        return
    await reply(context, update.effective_message,
        RULES.format(roll=config.ROLLOVER_TIME.strftime("%H:%M"), rep=config.REPORT_TIME.strftime("%H:%M"),
                     n=config.TOP_N, prize=config.PRIZE_TEXT, turn=config.TURNOVER_REQ),
        kind=kind, parse_mode=ParseMode.HTML)


# /topX /rulesX：只有审核人员 / 管理员能用，Bot 的回复会一直留在群里（不自动删除）
async def cmd_top_keep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await _require_admin(update, context):
        await cmd_top(update, context, kind="keep")


async def cmd_rules_keep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await _require_admin(update, context):
        await cmd_rules(update, context, kind="keep")


async def _require_admin(update: Update, context) -> bool:
    if not await is_admin(context, update.effective_chat.id, update.effective_user.id):
        await reply(context, update.effective_message, "只有审核人员 / 管理员可以使用这个指令。")
        return False
    return True


async def resolve_target(update: Update, args: list[str]):
    """找出要处理的玩家：回复消息 / user_id / @username。返回 (uid, username, name, snippet, 错误讯息)"""
    target = update.effective_message.reply_to_message
    if target and target.from_user and not target.from_user.is_bot:
        u = target.from_user
        return u.id, u.username, u.full_name, target.text or "", None
    if not args:
        return None, None, None, "", "missing"
    key = args.pop(0)
    if key.lstrip("-").isdigit():
        return int(key), None, None, "", None
    rows = await db.find_by_username(key)
    if not rows:
        return None, None, None, "", (f"找不到 {html.escape(key)}。\n这个人可能没在群里发过言，或者改了 username。"
                                       f"\n可以在群里回复他的消息打指令，或用违规报告里的 🆔 ID。")
    r = rows[0]
    return r["user_id"], r.get("username"), r.get("full_name"), "", None


def format_quest(name: str, s: dict) -> str:
    today = s.get("today", 0)
    def box(done): return "✅" if done else "⬜"
    lines = [f"📋 <b>今日任务</b>  {config.today():%d/%m}", f"👤 {name}", ""]
    if s.get("disqualified"):
        lines.append("❌ 本期资格已取消（违规发送链接 / 二维码）")
        return "\n".join(lines)
    lines += [
        f"{box(today >= 1)} 有效发言  每条 +1 分（已发 {today} 条，无上限）",
        f"{box(today >= 5)} 发满 5 条  +5 分（{min(today, 5)}/5）",
        f"{box(today >= 10)} 发满 10 条  +5 分（{min(today, 10)}/10）",
        f"{box(today >= 10)} 完成全部任务  +5 分",
        "",
    ]
    earned = today + (5 if today >= 5 else 0) + (10 if today >= 10 else 0)
    lines.append(f"⭐ 今日已得 <b>{earned}</b> 分  |  本期总分 <b>{s.get('points', 0)}</b> 分")
    if today < 5:
        lines.append(f"🎯 再聊 {5 - today} 条拿 +5 分")
    elif today < 10:
        lines.append(f"🎯 再聊 {10 - today} 条拿 +10 分（10条任务 + 全部完成）")
    else:
        lines.append("🔥 今日任务全部完成！继续聊天每条 +1 分")
    lines.append("⏰ 任务每天 00:00（马来西亚时间）重置")
    return "\n".join(lines)


async def cmd_quest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/quest 看自己的今日任务；reviewer / 管理员可以 /quest @username 看别人的"""
    if not await player_allowed(update, context):
        return
    msg, user = update.effective_message, update.effective_user
    args = list(context.args or [])
    uid, name = user.id, html.escape(user.full_name)
    if args or (msg.reply_to_message and msg.reply_to_message.from_user):
        if not await is_admin(context, update.effective_chat.id, user.id):
            return await reply(context, msg, "只有管理员 / 审核人员可以查看别人的任务。")
        uid, uname, fname, _, err = await resolve_target(update, args)
        if err:
            return await reply(context, msg, err if err != "missing" else "用法：/quest @username", parse_mode=ParseMode.HTML)
        name = html.escape(f"@{uname}" if uname else (fname or str(uid))) + f" (<code>{uid}</code>)"
    s = await db.my_stats(config.current_event(), config.today(), uid)
    await reply(context, msg, format_quest(name, s), parse_mode=ParseMode.HTML)


async def cmd_dq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消资格：回复玩家消息 /dq 原因，或 /dq <user_id 或 @username> 原因"""
    if not await _require_admin(update, context):
        return
    msg = update.effective_message
    args = list(context.args)
    uid, uname, fname, snippet, err = await resolve_target(update, args)
    if err == "missing":
        return await reply(context, msg, "用法：/dq @username 原因\n或 /dq <user_id> 原因\n或在群里回复玩家消息打 /dq 原因")
    if err:
        return await reply(context, msg, err, parse_mode=ParseMode.HTML)
    reason = " ".join(args) or "manual"
    await db.disqualify(config.current_event(), uid, uname, fname, "manual", reason, snippet)
    who = f"@{uname}" if uname else (fname or "")
    await reply(context, msg, f"❌ 已取消 {html.escape(who)} (<code>{uid}</code>) 本期资格。", kind="warning", parse_mode=ParseMode.HTML)


async def cmd_undq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """恢复资格：/undq @username，或 /undq <user_id>，或在群里回复玩家消息 /undq"""
    if not await _require_admin(update, context):
        return
    msg = update.effective_message
    uid, uname, fname, _, err = await resolve_target(update, list(context.args))
    if err == "missing":
        return await reply(context, msg, "用法：/undq @username\n或 /undq <user_id>\n或在群里回复玩家消息打 /undq")
    if err:
        return await reply(context, msg, err, parse_mode=ParseMode.HTML)
    s = await db.my_stats(config.current_event(), config.today(), uid)
    await db.undq(config.current_event(), uid)
    who = f"@{uname}" if uname else (fname or "")
    await reply(context, msg, f"✅ 已恢复 {html.escape(who)} (<code>{uid}</code>) 本期资格，积分 {s.get('points', 0)} 分保留。",
                         kind="warning", parse_mode=ParseMode.HTML)


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """拿名单（任何一周都可以，资料不会删）：
    /report            → 本周实时名单
    /report last       → 上一周（= /report 1）
    /report 2          → 两周前，以此类推
    /report 2026-10-26 → 包含这一天的那一周
    """
    if not await _require_admin(update, context):
        return
    msg = update.effective_message
    event = config.current_event()
    arg = context.args[0].lower() if context.args else ""
    try:
        if arg in ("last", "上周"):
            event -= timedelta(days=7)
        elif arg.isdigit():
            event -= timedelta(days=7 * int(arg))
        elif arg:
            d = datetime.strptime(arg, "%Y-%m-%d").replace(hour=12, tzinfo=config.TZ)
            event = config.event_key_for(d)
    except ValueError:
        return await reply(context, msg, "用法：/report、/report last、/report 2、/report 2026-10-26", kind="keep")
    await send_report(context, event, chat_id=update.effective_chat.id, announce=False)


COMMAND_LIST = """📖 <b>终极聊天争霸赛 · 指令清单</b>

<b>👥 玩家（所有人）</b>
/points 或打「分数」— 我的积分、排名
/quest 或打「任务」— 今日任务进度 ✅⬜
/top — 实时 Top 10
/rules — 活动规则
<i>（群里的回复 20 秒后自动删除）</i>

<b>🛡 审核人员 / 管理员</b>
<u>活动开关</u>
/eventstart — 开始活动
/eventend — 结束活动（停止计分，玩家指令暂停，积分保留）
/eventstatus — 现在是开始还是结束
/eventreset — 本周积分清零（要按按钮确认，会先备份名单）
/eventreset all — 全部资料清零（测试完、正式开始前用）

<u>资格</u>
/dq @username 原因 — 取消本期资格
/undq @username — 恢复资格（积分保留）
<i>也可以用 user_id，或在群里回复玩家的消息打指令</i>

<u>查看</u>
/quest @username — 看某玩家今日任务
/topX — 排行榜（不会自动删除，适合公告）
/rulesX — 规则（不会自动删除）

<u>名单</u>
/report — 本周实时 Top 20 + CSV
/report last — 上一周
/report 2 — 两周前（3、4… 以此类推）
/report 2026-10-26 — 包含这一天的那一周

<u>工具</u>
/debug — 检查 Bot 设定（打在活动群里）
/id — 查 chat_id / user_id
/list — 这个清单

<b>🚨 违规报告按钮</b>
❌ 取消本期资格 — 警告保留在群里
✅ 忽略 — 自动删除群里的警告

<b>⏰ 自动</b>
每周一 10:30 换期（新一周从 0 分开始，旧资料保留）
每周一 11:00 名单发给客服群 + 私讯审核人员"""


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """审核人员看全部指令。在群里打会改成私讯，避免玩家看到管理指令。"""
    if not await _require_admin(update, context):
        return
    msg, chat = update.effective_message, update.effective_chat
    if chat.type == ChatType.PRIVATE:
        return await msg.reply_text(COMMAND_LIST, parse_mode=ParseMode.HTML)
    try:
        await context.bot.send_message(update.effective_user.id, COMMAND_LIST, parse_mode=ParseMode.HTML)
        await reply(context, msg, "📖 指令清单已私讯给你。")
    except Exception:
        await reply(context, msg, "请先私讯我按一次 Start，再打 /list。")


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(context, update.effective_message, 
        f"chat_id: <code>{update.effective_chat.id}</code>\nuser_id: <code>{update.effective_user.id}</code>",
        parse_mode=ParseMode.HTML)


async def cmd_debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """在群里打 /debug：一次检查所有可能让计分失败的原因"""
    chat, user, msg = update.effective_chat, update.effective_user, update.effective_message
    lines = ["🔧 <b>Debug</b>"]
    me = await context.bot.get_me()
    can_read = bool(me.can_read_all_group_messages)
    lines.append(f"{'✅' if can_read else '❌'} Privacy 已关闭（能看到普通聊天）"
                 + ("" if can_read else "\n   → @BotFather /setprivacy → Disable，再把 Bot 踢出群重新拉进来"))
    in_group = not config.GROUP_IDS or chat.id in config.GROUP_IDS
    lines.append(f"{'✅' if in_group else '❌'} 这个群在 GROUP_IDS 里"
                 f"\n   这个群: <code>{chat.id}</code>（{chat.type}）"
                 f"\n   GROUP_IDS: <code>{','.join(map(str, config.GROUP_IDS)) or '(空=全部群)'}</code>"
                 + ("" if in_group else f"\n   → Railway 把 GROUP_IDS 改成 {chat.id}"))
    try:
        bm = await context.bot.get_chat_member(chat.id, me.id)
        can_del = bm.status == "administrator" and bool(getattr(bm, "can_delete_messages", False))
    except Exception:
        can_del = False
    lines.append(f"{'✅' if can_del else '⚠️'} Bot 有「删除消息」权限"
                 + ("" if can_del else "（自动删除玩家打的 /points 等指令需要这个权限；Bot 自己的回复不需要）"))
    admin = await is_admin(context, chat.id, user.id)
    lines.append(f"{'⚠️ 你是管理员（不计分）' if admin else '✅ 你不是管理员（会计分）'}  <code>{user.id}</code>")
    try:
        s = await db.my_stats(config.current_event(), config.today(), user.id)
        lines.append(f"✅ Supabase 连接正常（你本期 {s.get('points', 0)} 分）")
        try:
            await db.lifetime_valid(user.id)
            lines.append("✅ Supabase 读表权限正常")
        except Exception as e:
            lines.append(f"❌ Supabase 读表失败: <code>{html.escape(str(e)[:200])}</code>")
    except Exception as e:
        lines.append(f"❌ Supabase 连接失败: <code>{html.escape(str(e)[:300])}</code>"
                     "\n   → 检查 SUPABASE_URL / SUPABASE_SERVICE_KEY（可换 Legacy 的 service_role eyJ... key）")
    if context.args:
        ok, reason, _ = check_valid(" ".join(context.args))
        lines.append(f"{'✅' if ok else '❌'} 「{html.escape(' '.join(context.args))}」→ {reason}")
    lines.append(f"{'✅ 活动进行中' if EVENT_ON else '⏸ 活动已结束（/eventstart 开始）'}")
    lines.append(f"⏰ 本期: {config.current_event()}  今天: {config.today()}")
    await reply(context, msg, "\n".join(lines), parse_mode=ParseMode.HTML)


# --------------------------------------------------------------------------
# 周一派奖：Top N 名单给客服 + 群公告
# --------------------------------------------------------------------------
async def send_report(context, event, chat_id: int, announce: bool):
    rows = await db.leaderboard(event, config.TOP_N)
    start, end = config.event_range(event)
    period = f"{start:%d/%m %H:%M} – {end:%d/%m %H:%M}"

    if not rows:
        await context.bot.send_message(chat_id, f"终极聊天争霸赛 {period}：本期没有符合条件的玩家。")
        return

    buf = io.StringIO()
    buf.write("﻿")                        # Excel 打开中文不乱码
    w = csv.writer(buf)
    w.writerow(["排名", "User ID", "Username", "名字", "积分", "有效发言", "奖励",
                f"流水≥{config.TURNOVER_REQ}（客服核对）", "已派奖"])
    for r in rows:
        w.writerow([r["rank"], r["user_id"], ("@" + r["username"]) if r.get("username") else "",
                    r.get("full_name") or "", r["points"], r["valid_msgs"], config.PRIZE_TEXT, "", ""])
    data = io.BytesIO(buf.getvalue().encode("utf-8"))
    data.name = f"chat_battle_{event:%Y%m%d}.csv"

    lines = [f"{r['rank']:>2}. {mention(r['user_id'], display_name(r))} "
             f"(@{html.escape(r.get('username') or '-')}, <code>{r['user_id']}</code>) — {r['points']} 分"
             for r in rows]
    summary = (f"📋 <b>终极聊天争霸赛 派奖名单</b>\n期间：{period}\n"
               f"奖励：{config.PRIZE_TEXT} × {len(rows)}\n"
               f"⚠️ 领取条件：需有 {config.TURNOVER_REQ} 流水，请客服逐一核对后再派发\n\n" + "\n".join(lines))
    await context.bot.send_message(chat_id, summary, parse_mode=ParseMode.HTML)
    await context.bot.send_document(chat_id, data, caption="完整名单（CSV，可用 Excel 打开）")

    if announce:
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        body = "\n".join(f"{medals.get(r['rank'], str(r['rank']) + '.')} {mention(r['user_id'], display_name(r))} — {r['points']} 分"
                         for r in rows)
        text = (f"🎉 <b>终极聊天争霸赛 本期赢家出炉！</b>\n{period}\n\n{body}\n\n"
                f"🎁 以上 Top {len(rows)} 各得 {config.PRIZE_TEXT}\n"
                f"📌 需有 {config.TURNOVER_REQ} 流水才能领取，请自行联系客服领取奖励\n\n"
                f"新一期已经开始，继续聊天冲榜吧！/points 查分")
        for gid in config.GROUP_IDS:
            try:
                await context.bot.send_message(gid, text, parse_mode=ParseMode.HTML)
            except Exception as e:
                log.warning("announce to %s failed: %s", gid, e)


async def job_weekly_report(context: ContextTypes.DEFAULT_TYPE):
    """周一 REPORT_TIME：上一周的名单发给客服群 + 每个审核人员（私讯），双保险。
    活动关闭时只私讯审核人员，不发群公告。"""
    event = config.current_event() - timedelta(days=7)
    log.info("weekly report for %s (event_on=%s)", event, EVENT_ON)
    targets = []
    if EVENT_ON and config.CS_CHAT_ID:
        targets.append(config.CS_CHAT_ID)
    targets += [r for r in config.REVIEWER_IDS if r not in targets]
    if config.LOG_CHAT_ID and config.LOG_CHAT_ID not in targets:
        targets.append(config.LOG_CHAT_ID)
    announced = False
    for t in targets:
        try:
            await send_report(context, event, chat_id=t, announce=EVENT_ON and not announced)
            announced = True
        except Exception as e:
            log.warning("weekly report to %s failed（审核人员要先私讯 Bot 按 /start）: %s", t, e)


# --------------------------------------------------------------------------
def main():
    app = Application.builder().token(config.BOT_TOKEN).post_init(load_event_state).build()

    app.add_handler(CommandHandler(["points", "score"], cmd_points))
    # 中文也能查分：直接打「分数」「积分」「查分」
    app.add_handler(MessageHandler(filters.Regex(r"^\s*(分数|积分|查分|我的分数|我的积分)\s*$"), cmd_points))
    app.add_handler(CommandHandler(["top", "rank"], cmd_top))
    app.add_handler(CommandHandler("topx", cmd_top_keep))      # /topX（大小写都可以）
    app.add_handler(CommandHandler("rulesx", cmd_rules_keep))  # /rulesX
    app.add_handler(CommandHandler(["rules", "start", "help"], cmd_rules))
    app.add_handler(CommandHandler("dq", cmd_dq))
    app.add_handler(CallbackQueryHandler(on_review_button, pattern=r"^(dq|ok):"))
    app.add_handler(CommandHandler("undq", cmd_undq))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler(["quest", "task"], cmd_quest))
    app.add_handler(MessageHandler(filters.Regex(r"^\s*(任务|今日任务|我的任务)\s*$"), cmd_quest))
    app.add_handler(CommandHandler("debug", cmd_debug))
    app.add_handler(CommandHandler(["list", "help_admin"], cmd_list))
    app.add_handler(CommandHandler("eventstart", cmd_event_start))
    app.add_handler(CommandHandler("eventend", cmd_event_end))
    app.add_handler(CommandHandler("eventstatus", cmd_event_status))
    app.add_handler(CommandHandler("eventreset", cmd_event_reset))
    app.add_handler(CallbackQueryHandler(on_reset_button, pattern=r"^rst:"))
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & ~filters.COMMAND & ~filters.UpdateType.EDITED & ~filters.StatusUpdate.ALL,
        on_group_message))

    # 每周一（days: 0=周日 … 6=周六，PTB 21 用 0=周日）REPORT_TIME 发名单
    app.job_queue.run_daily(
        job_weekly_report, time=config.REPORT_TIME.replace(tzinfo=config.TZ), days=(1,), name="weekly_report")

    log.info("Chat Battle bot started. groups=%s current_event=%s", config.GROUP_IDS, config.current_event())
    app.run_polling(allowed_updates=["message", "callback_query"], drop_pending_updates=False)


if __name__ == "__main__":
    main()
