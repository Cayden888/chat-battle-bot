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

from telegram import Update, Message, User, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.constants import ParseMode, ChatType
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters,
)

import config
import db
from msg_filters import check_valid, content_hash, has_link
from texts import t

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


def lang_of(update: Update) -> str:
    """这个对话用哪种语言：群看 GROUP_LANGS；私聊看玩家 Telegram 的语言设定。"""
    chat, user = update.effective_chat, update.effective_user
    if chat and chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        return config.GROUP_LANGS.get(chat.id, "zh")
    code = (getattr(user, "language_code", None) or "").lower()
    return "ms" if code.startswith(("ms", "id")) else "zh"


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
POINTS_WORDS = r"分数|积分|查分|我的分数|我的积分|markah|skor|mata saya|markah saya"
QUEST_WORDS = r"任务|今日任务|我的任务|misi|misi saya|misi hari ini|tugasan"
TEXT_TRIGGERS = re.compile(rf"^\s*({POINTS_WORDS}|{QUEST_WORDS})\s*$", re.IGNORECASE)


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
STAFF_IDS: set[int] = set()   # 客服 / 工作人员：不计分、不上榜、发链接不警告（/staff 管理，存在 Supabase）


async def load_event_state(app=None):
    global EVENT_ON
    try:
        EVENT_ON = (await db.get_setting("event_on", "1")) != "0"
    except Exception as e:
        log.warning("读取活动开关失败（是否跑了 add_event_switch.sql？），先当作开启: %s", e)
        EVENT_ON = True
    log.info("活动状态: %s", "进行中" if EVENT_ON else "已结束")
    # 用 /setgroup 设过的活动群，优先于 Railway 的 GROUP_IDS
    try:
        saved = await db.get_setting("group_ids")
        if saved:
            config.GROUP_IDS.clear()
            config.GROUP_IDS.update(int(x) for x in saved.split(",") if x.strip())
    except Exception as e:
        log.warning("读取活动群设定失败，使用 Railway 的 GROUP_IDS: %s", e)
    try:
        STAFF_IDS.clear()
        STAFF_IDS.update(int(x) for x in (await db.get_setting("staff_ids", "") or "").split(",") if x.strip())
    except Exception as e:
        log.warning("读取工作人员名单失败: %s", e)
    try:
        saved_langs = await db.get_setting("group_langs")
        if saved_langs:
            config.GROUP_LANGS.update(config._langs(saved_langs))
    except Exception as e:
        log.warning("读取群语言设定失败: %s", e)
    log.info("活动群: %s  语言: %s", config.GROUP_IDS or "(全部群)", config.GROUP_LANGS)


async def player_allowed(update: Update, context) -> bool:
    """活动关闭时，玩家指令一律回复「没有进行中」；审核人员 / 管理员不受影响。"""
    if EVENT_ON:
        return True
    if await is_admin(context, update.effective_chat.id, update.effective_user.id):
        return True
    await reply(context, update.effective_message, t(lang_of(update), "closed"))
    return False


async def _announce(context, key: str):
    """发公告到每个活动群，各用自己群的语言（texts.py 的 key）"""
    for gid in config.GROUP_IDS:
        try:
            await context.bot.send_message(gid, t(config.GROUP_LANGS.get(gid, "zh"), key), parse_mode=ParseMode.HTML)
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
        await _announce(context, "event_started")


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
        await _announce(context, "event_ended")


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


async def _save_groups(by: int | None = None):
    await db.set_setting("group_ids", ",".join(str(g) for g in sorted(config.GROUP_IDS)), by)
    await db.set_setting("group_langs", ",".join(f"{g}:{l}" for g, l in sorted(config.GROUP_LANGS.items())), by)


async def cmd_setgroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """在活动群里打：
    /setgroup          → 只用这个群（其他群移除）
    /setgroup add      → 加上这个群（多群，分数合并）
    后面可以加语言：/setgroup add ms（马来文）、/setgroup zh（华语）
    """
    if not await _require_admin(update, context):
        return
    chat, msg = update.effective_chat, update.effective_message
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return await reply(context, msg, "请在要做活动的群里打 /setgroup", kind="keep")
    args = [a.lower() for a in (context.args or [])]
    adding = "add" in args
    lang = next((a for a in args if a in ("zh", "ms")), None)
    if not adding:
        config.GROUP_IDS.clear()
    config.GROUP_IDS.add(chat.id)
    if lang:
        config.GROUP_LANGS[chat.id] = lang
    await _save_groups(update.effective_user.id)
    note = ""
    if chat.type == ChatType.GROUP:
        note = "\n⚠️ 这是普通群，以后 Telegram 可能自动升级成超级群，Bot 会自动跟上新 ID。"
    names = {"zh": "华语", "ms": "马来文"}
    listing = "\n".join(f"• <code>{g}</code> — {names[config.GROUP_LANGS.get(g, 'zh')]}" for g in sorted(config.GROUP_IDS))
    await reply(context, msg,
                f"✅ 已{'加上' if adding else '设为'}活动群：<code>{chat.id}</code>"
                f"（{names[config.GROUP_LANGS.get(chat.id, 'zh')]}）\n\n现在的活动群：\n{listing}{note}",
                kind="keep", parse_mode=ParseMode.HTML)


async def cmd_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """审核人员看现在绑定了哪些活动群（名字、ID、语言、Bot 权限）"""
    if not await _require_admin(update, context):
        return
    if not config.GROUP_IDS:
        return await reply(context, update.effective_message,
                           "⚠️ 还没有绑定活动群（现在所有群都会计分）。\n在活动群里打 /setgroup 绑定。", kind="keep")
    me = await context.bot.get_me()
    names = {"zh": "华语", "ms": "马来文"}
    lines = [f"📌 <b>已绑定的活动群（{len(config.GROUP_IDS)}）</b>", ""]
    for gid in sorted(config.GROUP_IDS):
        try:
            c = await context.bot.get_chat(gid)
            title = html.escape(c.title or str(gid))
            try:
                m = await context.bot.get_chat_member(gid, me.id)
                if m.status == "administrator":
                    can_del = getattr(m, "can_delete_messages", False)
                    can_mute = getattr(m, "can_restrict_members", False)
                    perm = (f"管理员  {'✅' if can_del else '❌'} 删除消息  "
                            f"{'✅' if can_mute else '❌'} 封禁用户（禁言要用）")
                elif m.status in ("left", "kicked"):
                    perm = "❌ Bot 不在群里"
                else:
                    perm = "⚠️ 不是管理员（玩家的指令删不掉）"
            except Exception:
                perm = "❓ 查不到权限"
        except Exception:
            title, perm = "（读不到群资料）", "❌ Bot 可能不在这个群，或群 ID 已变"
        lines += [f"<b>{title}</b>",
                  f"   ID：<code>{gid}</code>",
                  f"   语言：{names.get(config.GROUP_LANGS.get(gid, 'zh'))}",
                  f"   Bot：{perm}", ""]
    lines.append(f"活动状态：{'✅ 进行中' if EVENT_ON else '⏸ 已结束'}")
    lines.append("改：在群里打 /setgroup（只用这个群）或 /setgroup add ms / zh（加上）")
    await reply(context, update.effective_message, "\n".join(lines), kind="keep", parse_mode=ParseMode.HTML)


async def on_migrate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """普通群被升级成超级群时，Telegram 会换一个新的群 ID —— 自动把活动群换成新 ID。"""
    msg = update.effective_message
    if msg.migrate_to_chat_id:                 # 旧群收到的消息
        old, new = msg.chat_id, msg.migrate_to_chat_id
    elif msg.migrate_from_chat_id:             # 新群收到的消息
        old, new = msg.migrate_from_chat_id, msg.chat_id
    else:
        return
    if old not in config.GROUP_IDS or new in config.GROUP_IDS:
        return
    config.GROUP_IDS.discard(old)
    config.GROUP_IDS.add(new)
    if old in config.GROUP_LANGS:
        config.GROUP_LANGS[new] = config.GROUP_LANGS.pop(old)
    await _save_groups()
    log.info("group migrated %s -> %s", old, new)
    await send_log(context, f"🔄 活动群升级成超级群，ID 已自动更新：<code>{old}</code> → <code>{new}</code>")


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


# ---- 禁言阶梯（config.MUTE_STEPS，例：1d,7d,perm）----
def _step_for(n: int) -> str | None:
    """第 n 次警告要禁言多久：'2h' / '1d' / 'perm' / None（不禁言）"""
    if not config.MUTE_STEPS or n < 1:
        return None
    return config.MUTE_STEPS[min(n, len(config.MUTE_STEPS)) - 1]


def _step_seconds(step: str) -> int | None:
    """None = 永久"""
    if step == "perm":
        return None
    num, unit = int(step[:-1]), step[-1]
    return num * (3600 if unit == "h" else 86400)


def _dur_text(lang: str, step: str) -> str:
    if step == "perm":
        return t(lang, "dur_perm")
    return t(lang, "dur_h" if step.endswith("h") else "dur_d", n=int(step[:-1]))


def mute_rule_text(lang: str) -> str:
    """/rules 里那一行：第 1 次 1 天、第 2 次 7 天、之后每次 永久禁言"""
    if not config.MUTE_STEPS:
        return t(lang, "mute_rule", steps="-")
    parts = [t(lang, "nth", n=i + 1, d=_dur_text(lang, st)) for i, st in enumerate(config.MUTE_STEPS)]
    if config.MUTE_STEPS[-1] != "perm":
        parts.append(t(lang, "nth_more", d=_dur_text(lang, config.MUTE_STEPS[-1])))
    return t(lang, "mute_rule", steps=("、" if lang == "zh" else ", ").join(parts))


async def mute_user(context, chat_id: int, user_id: int, step: str) -> tuple[bool, str]:
    """禁言（还在群里、看得到消息，只是不能发言）。返回 (成功?, 失败原因)"""
    secs = _step_seconds(step)
    until = None if secs is None else datetime.now(config.TZ) + timedelta(seconds=secs)
    try:
        await context.bot.restrict_chat_member(chat_id, user_id, permissions=ChatPermissions.no_permissions(),
                                               until_date=until)
        return True, ""
    except Exception as e:
        log.warning("mute %s in %s failed: %s", user_id, chat_id, e)
        return False, str(e)


async def unmute_user(context, chat_id: int, user_id: int) -> tuple[bool, str]:
    try:
        await context.bot.restrict_chat_member(chat_id, user_id, permissions=ChatPermissions.all_permissions())
        return True, ""
    except Exception as e:
        log.warning("unmute %s in %s failed: %s", user_id, chat_id, e)
        return False, str(e)


async def flag_violation(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str, snippet: str):
    """发链接：记一次警告 → 按次数禁言（1 天 / 7 天 / 永久）→ 群里警告（2 小时后删）→ 私讯审核人员。
    不删玩家的消息、不踢人、不自动取消资格。"""
    msg, user, chat = update.effective_message, update.effective_user, update.effective_chat
    event = config.current_event()
    label, why = REASONS.get(kind, (kind, "违反活动规则。"))
    name = mention(user.id, html.escape(user.full_name))
    lang = lang_of(update)
    week_scope = config.WARN_COUNT_SCOPE == "week"

    try:
        await db.flag(event, user.id, user.username, user.full_name, kind, snippet)
        warn_count = await db.warn_count(user.id, event if week_scope else None)
        history = await db.lifetime_valid(user.id)
        stats = await db.my_stats(event, config.today(), user.id)
    except Exception as e:
        log.exception("flag failed: %s", e)
        warn_count, history, stats = 1, 0, {}

    # 1) 禁言
    step = _step_for(warn_count)
    muted, mute_err = (await mute_user(context, chat.id, user.id, step)) if step else (False, "")
    if muted:
        penalty = t(lang, "mute_perm") if step == "perm" else t(lang, "mute_for", dur=_dur_text(lang, step))
    else:
        penalty = ""

    # 2) 群警告（2 小时后自动删；审核人员按「忽略」也会删）
    count_txt = t(lang, "warn_count_week" if week_scope else "warn_count_all", n=warn_count)
    warn_mid = 0
    try:
        wm = await reply(context, msg,
            t(lang, "warning", name=name, label=t(lang, f"label_{kind}"), count=count_txt, penalty=penalty),
            kind="warning", parse_mode=ParseMode.HTML)
        warn_mid = wm.message_id
    except Exception as e:
        log.warning("group warning failed: %s", e)
    warn_ref = f":{chat.id}:{warn_mid}"

    # 3) 私讯审核人员
    link = message_link(chat, msg.message_id)
    hint = ""
    if history < config.NEWBIE_THRESHOLD:
        hint = f"\n🎣 <b>疑似钓鱼号</b>：之前只有 {history} 条有效发言就{label}。"
    if muted:
        pen_line = f"🔇 已自动禁言：{_dur_text('zh', step)}"
    elif step:
        pen_line = ("⚠️ <b>禁言失败</b>：Bot 需要群管理员的「封禁用户 / 限制成员」权限"
                    f"\n   <code>{html.escape(mute_err[:120])}</code>")
    else:
        pen_line = "🔇 没有设定禁言（MUTE_STEPS 是空的）"
    status = "（已被取消资格）" if stats.get("disqualified") else ""
    report = (
        f"🚨 <b>终极聊天争霸赛 · 违规审核</b>\n\n"
        f"👤 玩家：{name}{status}\n"
        f"🆔 ID：<code>{user.id}</code>\n"
        f"🔗 Username：@{html.escape(user.username) if user.username else '-'}\n"
        f"👥 群：{html.escape(chat.title or str(chat.id))}\n"
        f"⭐ 本期积分：{stats.get('points', 0)} 分  |  排名：{('#' + str(stats['rank'])) if stats.get('rank') else '未上榜'}\n"
        f"🔁 {'本周' if week_scope else '累计'}违规次数：{warn_count}\n"
        f"{pen_line}\n\n"
        f"❗ <b>为什么可能被取消资格：</b>\n{why}{hint}\n\n"
        f"📝 内容：<code>{html.escape((snippet or '')[:300])}</code>"
        + (f'\n📎 <a href="{link}">查看原消息</a>' if link else "")
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ 取消本期资格", callback_data=f"dq:{event:%Y%m%d}:{user.id}{warn_ref}"),
        InlineKeyboardButton("✅ 忽略（解除禁言）", callback_data=f"ok:{event:%Y%m%d}:{user.id}{warn_ref}"),
    ]])
    targets = list(config.REVIEWER_IDS) + ([config.LOG_CHAT_ID] if config.LOG_CHAT_ID else [])
    for tgt in targets:
        try:
            await context.bot.send_message(tgt, report, parse_mode=ParseMode.HTML,
                                           reply_markup=kb, disable_web_page_preview=True)
        except Exception as e:
            log.warning("report to %s failed（审核人员要先私讯 Bot 按 /start）: %s", tgt, e)


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
        # 忽略 = 不算违规：这次警告不算次数 + 解除禁言 + 删群里的警告
        try:
            await db.unflag(uid)
            result += "\n↩️ 这次警告不算次数"
        except Exception as e:
            log.warning("unflag failed: %s", e)
        if warn_chat:
            ok_, err_ = await unmute_user(context, warn_chat, uid)
            result += "\n🔊 已解除禁言" if ok_ else f"\n⚠️ 解除禁言失败：<code>{html.escape(err_[:100])}</code>"
        if warn_chat and warn_msg:
            try:
                await context.bot.delete_message(warn_chat, warn_msg)
                result += "\n🗑 群里的警告已删除"
            except Exception as e:
                log.warning("delete warning failed: %s", e)
                result += "\n🗑 群里的警告已经不在了（2 小时后会自动删除）"
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
    admin = user.id in STAFF_IDS or await is_admin(context, msg.chat_id, user.id)

    # 1) Link / QR —— 管理员 / 工作人员豁免
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
        who = mention(user.id, html.escape(user.first_name))
        if daily == 5:
            text = t(lang_of(update), "congrats5", name=who)
        else:
            text = t(lang_of(update), "congrats10", name=who, points=res["points"])
        try:
            await reply(context, msg, text, kind="congrats", parse_mode=ParseMode.HTML, disable_notification=True)
        except Exception:
            pass


# --------------------------------------------------------------------------
# 指令
# --------------------------------------------------------------------------
def format_stats(user: User, s: dict, lang: str = "zh") -> str:
    event = config.current_event()
    start, end = config.event_range(event)
    lines = [t(lang, "stats_title", start=f"{start:%d/%m}", end=f"{end:%d/%m}"),
             f"👤 {html.escape(user.full_name)}"]
    if s.get("disqualified"):
        lines.append(t(lang, "dq_status"))
        return "\n".join(lines)
    today = s.get("today", 0)
    rank = s.get("rank")
    lines += [
        t(lang, "stats_points", p=s.get("points", 0)),
        t(lang, "stats_rank", r=rank) if rank else t(lang, "stats_norank"),
        t(lang, "stats_today", n=today),
    ]
    if today < 5:
        lines.append(t(lang, "stats_need5", n=5 - today))
    elif today < 10:
        lines.append(t(lang, "stats_need10", n=10 - today))
    else:
        lines.append(t(lang, "stats_done"))
    if rank and rank <= config.TOP_N:
        lines.append(t(lang, "stats_intop", n=config.TOP_N))
    return "\n".join(lines)


async def cmd_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await player_allowed(update, context):
        return
    user, msg = update.effective_user, update.effective_message
    s = await db.my_stats(config.current_event(), config.today(), user.id)
    await reply(context, msg, format_stats(user, s, lang_of(update)), parse_mode=ParseMode.HTML)


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str = "reply"):
    if kind == "reply" and not await player_allowed(update, context):
        return
    msg = update.effective_message
    lang = lang_of(update)
    rows = await db.leaderboard(config.current_event(), 10)
    if not rows:
        text = t(lang, "top_empty")
    else:
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        body = "\n".join(f"{medals.get(r['rank'], str(r['rank']) + '.')} {display_name(r)} — {r['points']} {t(lang, 'pts')}"
                         for r in rows)
        text = f"{t(lang, 'top_title')}\n\n{body}\n\n{t(lang, 'top_footer')}"
    await reply(context, msg, text, kind=kind, parse_mode=ParseMode.HTML)


async def cmd_rules(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str = "reply"):
    if kind == "reply" and not await player_allowed(update, context):
        return
    await reply(context, update.effective_message,
        t(lang_of(update), "rules", roll=config.ROLLOVER_TIME.strftime("%H:%M"),
          rep=config.REPORT_TIME.strftime("%H:%M"), n=config.TOP_N, prize=config.PRIZE_TEXT,
          turn=config.TURNOVER_REQ, mute_rule=mute_rule_text(lang_of(update))),
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
        await reply(context, update.effective_message, t(lang_of(update), "admin_only"))
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


def format_quest(name: str, s: dict, lang: str = "zh") -> str:
    today = s.get("today", 0)
    def box(done): return "✅" if done else "⬜"
    lines = [t(lang, "quest_title", date=f"{config.today():%d/%m}"), f"👤 {name}", ""]
    if s.get("disqualified"):
        lines.append(t(lang, "dq_status"))
        return "\n".join(lines)
    lines += [
        t(lang, "quest_1", b=box(today >= 1), n=today),
        t(lang, "quest_5", b=box(today >= 5), x=min(today, 5)),
        t(lang, "quest_10", b=box(today >= 10), x=min(today, 10)),
        t(lang, "quest_all", b=box(today >= 10)),
        "",
    ]
    earned = today + (5 if today >= 5 else 0) + (10 if today >= 10 else 0)
    lines.append(t(lang, "quest_earned", e=earned, p=s.get("points", 0)))
    if today < 5:
        lines.append(t(lang, "quest_need5", n=5 - today))
    elif today < 10:
        lines.append(t(lang, "quest_need10", n=10 - today))
    else:
        lines.append(t(lang, "quest_done"))
    lines.append(t(lang, "quest_reset"))
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
            return await reply(context, msg, t(lang_of(update), "quest_others_only"))
        uid, uname, fname, _, err = await resolve_target(update, args)
        if err:
            return await reply(context, msg, err if err != "missing" else "用法：/quest @username", parse_mode=ParseMode.HTML)
        name = html.escape(f"@{uname}" if uname else (fname or str(uid))) + f" (<code>{uid}</code>)"
    s = await db.my_stats(config.current_event(), config.today(), uid)
    await reply(context, msg, format_quest(name, s, lang_of(update)), parse_mode=ParseMode.HTML)


async def _save_staff(by=None):
    await db.set_setting("staff_ids", ",".join(str(x) for x in sorted(STAFF_IDS)), by)


async def cmd_staff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/staff @username（或回复他的消息 / user_id）→ 加进工作人员名单：不计分、不上榜、发链接不警告。
    本周已有的分数会被移出排行榜。"""
    if not await _require_admin(update, context):
        return
    msg = update.effective_message
    uid, uname, fname, _, err = await resolve_target(update, list(context.args))
    if err == "missing":
        return await reply(context, msg, "用法：/staff @username\n或 /staff <user_id>\n或在群里回复他的消息打 /staff", kind="keep")
    if err:
        return await reply(context, msg, err, kind="keep", parse_mode=ParseMode.HTML)
    STAFF_IDS.add(uid)
    await _save_staff(update.effective_user.id)
    # 本周已经拿的分数：移出排行榜（用取消资格的方式，名单里不会出现）
    await db.disqualify(config.current_event(), uid, uname, fname, "staff", "staff", "")
    who = html.escape(f"@{uname}" if uname else (fname or str(uid)))
    await reply(context, msg, f"✅ {who} (<code>{uid}</code>) 已加进工作人员名单：不计分、不上榜、发链接不警告。\n"
                f"本周已有的分数已移出排行榜。", kind="keep", parse_mode=ParseMode.HTML)


async def cmd_unstaff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_admin(update, context):
        return
    msg = update.effective_message
    uid, uname, fname, _, err = await resolve_target(update, list(context.args))
    if err == "missing":
        return await reply(context, msg, "用法：/unstaff @username 或 /unstaff <user_id>", kind="keep")
    if err:
        return await reply(context, msg, err, kind="keep", parse_mode=ParseMode.HTML)
    STAFF_IDS.discard(uid)
    await _save_staff(update.effective_user.id)
    await db.undq(config.current_event(), uid)
    who = html.escape(f"@{uname}" if uname else (fname or str(uid)))
    await reply(context, msg, f"✅ {who} (<code>{uid}</code>) 已移出工作人员名单，从现在起会正常计分。",
                kind="keep", parse_mode=ParseMode.HTML)


async def cmd_stafflist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_admin(update, context):
        return
    if not STAFF_IDS:
        return await reply(context, update.effective_message,
                           "工作人员名单是空的。\n用 /staff @username 加人（群管理员和审核人员本来就不计分，不用加）。", kind="keep")
    lines = [f"👔 <b>工作人员名单（{len(STAFF_IDS)}）</b>— 不计分、不上榜、发链接不警告", ""]
    for uid in sorted(STAFF_IDS):
        try:
            c = await context.bot.get_chat(uid)
            name = html.escape(("@" + c.username) if c.username else (c.full_name or ""))
        except Exception:
            name = ""
        lines.append(f"• {name} <code>{uid}</code>")
    lines.append("\n移除：/unstaff @username")
    await reply(context, update.effective_message, "\n".join(lines), kind="keep", parse_mode=ParseMode.HTML)


async def cmd_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/unmute @username：解除禁言（在群里打 = 这个群；私讯 Bot 打 = 所有活动群）。不会清警告次数。"""
    if not await _require_admin(update, context):
        return
    msg, chat = update.effective_message, update.effective_chat
    uid, uname, fname, _, err = await resolve_target(update, list(context.args))
    if err == "missing":
        return await reply(context, msg, "用法：/unmute @username 或 /unmute <user_id>，或在群里回复他的消息打 /unmute", kind="keep")
    if err:
        return await reply(context, msg, err, kind="keep", parse_mode=ParseMode.HTML)
    groups = [chat.id] if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP) else sorted(config.GROUP_IDS)
    lines = []
    for g in groups:
        ok_, e = await unmute_user(context, g, uid)
        lines.append(f"{'✅' if ok_ else '❌'} <code>{g}</code>" + ("" if ok_ else f" {html.escape(e[:80])}"))
    who = html.escape(f"@{uname}" if uname else (fname or str(uid)))
    cnt = await db.warn_count(uid, None)
    await reply(context, msg, f"🔊 {who} (<code>{uid}</code>) 解除禁言：\n" + "\n".join(lines)
                + f"\n\n警告次数还是 {cnt} 次（要清零：/resetwarn {('@' + uname) if uname else uid}）",
                kind="keep", parse_mode=ParseMode.HTML)


async def cmd_resetwarn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/resetwarn @username：警告次数清零（下次再犯又从第 1 次算起）"""
    if not await _require_admin(update, context):
        return
    msg = update.effective_message
    uid, uname, fname, _, err = await resolve_target(update, list(context.args))
    if err == "missing":
        return await reply(context, msg, "用法：/resetwarn @username 或 /resetwarn <user_id>", kind="keep")
    if err:
        return await reply(context, msg, err, kind="keep", parse_mode=ParseMode.HTML)
    n = await db.clear_warns(uid)
    who = html.escape(f"@{uname}" if uname else (fname or str(uid)))
    await reply(context, msg, f"✅ {who} (<code>{uid}</code>) 的警告次数已清零（清掉 {n} 次）。\n"
                f"禁言不会自动解除，需要的话打 /unmute。", kind="keep", parse_mode=ParseMode.HTML)


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
    await reply(context, msg, t(lang_of(update), "dq_done", who=html.escape(who), uid=uid),
                kind="keep", parse_mode=ParseMode.HTML)


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
    await reply(context, msg, t(lang_of(update), "undq_done", who=html.escape(who), uid=uid, p=s.get("points", 0)),
                kind="keep", parse_mode=ParseMode.HTML)


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
/groups — 看现在绑定了哪些活动群（名字、ID、语言、Bot 权限）
/setgroup — 在新群里打，把这个群设为活动群（换群用）
/setgroup add — 加上这个群（多个活动群，分数合并）
/setgroup add ms — 加上这个群，用马来文（zh = 华语）
/eventreset — 本周积分清零（要按按钮确认，会先备份名单）
/eventreset all — 全部资料清零（测试完、正式开始前用）

<u>工作人员（客服等）</u>
/staff @username — 加进名单：不计分、不上榜、发链接不警告（永久）
/unstaff @username — 移出名单
/stafflist — 看名单
<i>群管理员和审核人员本来就不计分，不用加</i>

<u>禁言（发链接自动禁言：第 1 次 1 天、第 2 次 7 天、第 3 次永久，可看群）</u>
/unmute @username — 解除禁言（私讯 Bot 打 = 所有活动群）
/resetwarn @username — 警告次数清零
<i>违规报告按「✅ 忽略」= 解除禁言 + 这次不算次数 + 删警告</i>

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
✅ 忽略 — 解除禁言、这次不算次数、删除群里的警告
（群警告本身 2 小时后自动删除）

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
                 + ("" if in_group else "\n   → 审核人员在这个群打 /setgroup 就行"))
    try:
        bm = await context.bot.get_chat_member(chat.id, me.id)
        can_del = bm.status == "administrator" and bool(getattr(bm, "can_delete_messages", False))
        can_mute = bm.status == "administrator" and bool(getattr(bm, "can_restrict_members", False))
    except Exception:
        can_del = can_mute = False
    lines.append(f"{'✅' if can_del else '⚠️'} Bot 有「删除消息」权限"
                 + ("" if can_del else "（自动删除玩家打的 /points 等指令需要这个权限；Bot 自己的回复不需要）"))
    lines.append(f"{'✅' if can_mute else '❌'} Bot 有「封禁用户」权限"
                 + ("" if can_mute else "（发链接禁言需要这个权限）"))
    lines.append(f"🌐 这个群的语言：{'马来文' if lang_of(update) == 'ms' else '华语'}"
                 "（改：/setgroup add ms 或 /setgroup add zh）")
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
        for gid in config.GROUP_IDS:
            lang = config.GROUP_LANGS.get(gid, "zh")
            body = "\n".join(f"{medals.get(r['rank'], str(r['rank']) + '.')} {mention(r['user_id'], display_name(r))} "
                             f"— {r['points']} {t(lang, 'pts')}" for r in rows)
            text = t(lang, "winners", period=period, body=body, n=len(rows),
                     prize=config.PRIZE_TEXT, turn=config.TURNOVER_REQ)
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
    for tgt in targets:
        try:
            await send_report(context, event, chat_id=tgt, announce=EVENT_ON and not announced)
            announced = True
        except Exception as e:
            log.warning("weekly report to %s failed（审核人员要先私讯 Bot 按 /start）: %s", tgt, e)


# --------------------------------------------------------------------------
def main():
    app = Application.builder().token(config.BOT_TOKEN).post_init(load_event_state).build()

    app.add_handler(CommandHandler(["points", "score"], cmd_points))
    # 中文也能查分：直接打「分数」「积分」「查分」
    app.add_handler(MessageHandler(filters.Regex(re.compile(rf"^\s*({POINTS_WORDS})\s*$", re.IGNORECASE)), cmd_points))
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
    app.add_handler(MessageHandler(filters.Regex(re.compile(rf"^\s*({QUEST_WORDS})\s*$", re.IGNORECASE)), cmd_quest))
    app.add_handler(CommandHandler("debug", cmd_debug))
    app.add_handler(CommandHandler(["list", "help_admin"], cmd_list))
    app.add_handler(CommandHandler("eventstart", cmd_event_start))
    app.add_handler(CommandHandler("eventend", cmd_event_end))
    app.add_handler(CommandHandler("eventstatus", cmd_event_status))
    app.add_handler(CommandHandler("setgroup", cmd_setgroup))
    app.add_handler(CommandHandler("groups", cmd_groups))
    app.add_handler(CommandHandler("staff", cmd_staff))
    app.add_handler(CommandHandler("unmute", cmd_unmute))
    app.add_handler(CommandHandler("resetwarn", cmd_resetwarn))
    app.add_handler(CommandHandler("unstaff", cmd_unstaff))
    app.add_handler(CommandHandler("stafflist", cmd_stafflist))
    app.add_handler(MessageHandler(filters.StatusUpdate.MIGRATE, on_migrate))
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
