"""
终极聊天争霸赛 THE ULTIMATE CHAT BATTLE — Telegram Bot
Python 3.11 + python-telegram-bot 21 + Supabase，部署在 Railway（worker，长轮询）
"""
import csv
import html
import io
import logging
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

    # 1) 群警告
    try:
        await msg.reply_text(
            f"⚠️ {name} 请勿在群内{label}。\n"
            f"这违反了【终极聊天争霸赛】规则，已提交管理员审核，"
            f"可能会被取消本期活动资格。（本期第 {warn_count} 次警告）",
            parse_mode=ParseMode.HTML)
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
        InlineKeyboardButton("❌ 取消本期资格", callback_data=f"dq:{event:%Y%m%d}:{user.id}"),
        InlineKeyboardButton("✅ 忽略", callback_data=f"ok:{event:%Y%m%d}:{user.id}"),
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
        action, ev, uid = q.data.split(":")
        event = datetime.strptime(ev, "%Y%m%d").date()
        uid = int(uid)
    except Exception:
        return await q.answer("按钮数据错误", show_alert=True)

    who = f"@{reviewer.username}" if reviewer.username else reviewer.full_name
    if action == "dq":
        await db.disqualify(event, uid, None, None, "reviewed", f"dq_by_{reviewer.id}", "")
        result = f"\n\n❌ <b>已取消本期资格</b> — {html.escape(who)}"
        await q.answer("已取消资格")
    else:
        result = f"\n\n✅ <b>已忽略</b> — {html.escape(who)}"
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
            await msg.reply_text(t, parse_mode=ParseMode.HTML, disable_notification=True)
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
    user, msg = update.effective_user, update.effective_message
    s = await db.my_stats(config.current_event(), config.today(), user.id)
    await msg.reply_text(format_stats(user, s), parse_mode=ParseMode.HTML)


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    rows = await db.leaderboard(config.current_event(), 10)
    if not rows:
        text = "🏆 本期还没有人上榜，快来聊天抢第一！"
    else:
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        body = "\n".join(f"{medals.get(r['rank'], str(r['rank']) + '.')} {display_name(r)} — {r['points']} 分"
                         for r in rows)
        text = f"🏆 <b>终极聊天争霸赛 · 实时 Top 10</b>\n\n{body}\n\n输入 /points 查看自己的分数"
    await msg.reply_text(text, parse_mode=ParseMode.HTML)


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
    "❌ 重复内容 / 只发表情 / 单个字 / 刷屏 不计分\n"
    "🚫 发链接、二维码 = 取消资格，钓鱼号直接踢出\n\n"
    "输入 /points 查看分数，/top 查看排行榜"
)


async def cmd_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        RULES.format(roll=config.ROLLOVER_TIME.strftime("%H:%M"), rep=config.REPORT_TIME.strftime("%H:%M"),
                     n=config.TOP_N, prize=config.PRIZE_TEXT, turn=config.TURNOVER_REQ),
        parse_mode=ParseMode.HTML)


async def _require_admin(update: Update, context) -> bool:
    if not await is_admin(context, update.effective_chat.id, update.effective_user.id):
        await update.effective_message.reply_text("只有管理员可以使用这个指令。")
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


async def cmd_dq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消资格：回复玩家消息 /dq 原因，或 /dq <user_id 或 @username> 原因"""
    if not await _require_admin(update, context):
        return
    msg = update.effective_message
    args = list(context.args)
    uid, uname, fname, snippet, err = await resolve_target(update, args)
    if err == "missing":
        return await msg.reply_text("用法：/dq @username 原因\n或 /dq <user_id> 原因\n或在群里回复玩家消息打 /dq 原因")
    if err:
        return await msg.reply_text(err, parse_mode=ParseMode.HTML)
    reason = " ".join(args) or "manual"
    await db.disqualify(config.current_event(), uid, uname, fname, "manual", reason, snippet)
    who = f"@{uname}" if uname else (fname or "")
    await msg.reply_text(f"❌ 已取消 {html.escape(who)} (<code>{uid}</code>) 本期资格。", parse_mode=ParseMode.HTML)


async def cmd_undq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """恢复资格：/undq @username，或 /undq <user_id>，或在群里回复玩家消息 /undq"""
    if not await _require_admin(update, context):
        return
    msg = update.effective_message
    uid, uname, fname, _, err = await resolve_target(update, list(context.args))
    if err == "missing":
        return await msg.reply_text("用法：/undq @username\n或 /undq <user_id>\n或在群里回复玩家消息打 /undq")
    if err:
        return await msg.reply_text(err, parse_mode=ParseMode.HTML)
    s = await db.my_stats(config.current_event(), config.today(), uid)
    await db.undq(config.current_event(), uid)
    who = f"@{uname}" if uname else (fname or "")
    await msg.reply_text(f"✅ 已恢复 {html.escape(who)} (<code>{uid}</code>) 本期资格，积分 {s.get('points', 0)} 分保留。",
                         parse_mode=ParseMode.HTML)


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/report → 本期实时名单；/report last → 上一期名单（重新发给客服）"""
    if not await _require_admin(update, context):
        return
    event = config.current_event()
    if context.args and context.args[0] == "last":
        event -= timedelta(days=7)
    await send_report(context, event, chat_id=update.effective_chat.id, announce=False)


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
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
    lines.append(f"⏰ 本期: {config.current_event()}  今天: {config.today()}")
    await msg.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


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
    # 周一 REPORT_TIME 执行：此时已经换期，上一期 = 本期 - 7 天
    event = config.current_event() - timedelta(days=7)
    log.info("weekly report for %s", event)
    target = config.CS_CHAT_ID or config.LOG_CHAT_ID
    if target:
        await send_report(context, event, chat_id=target, announce=True)


# --------------------------------------------------------------------------
def main():
    app = Application.builder().token(config.BOT_TOKEN).build()

    app.add_handler(CommandHandler(["points", "score"], cmd_points))
    # 中文也能查分：直接打「分数」「积分」「查分」
    app.add_handler(MessageHandler(filters.Regex(r"^\s*(分数|积分|查分|我的分数|我的积分)\s*$"), cmd_points))
    app.add_handler(CommandHandler(["top", "rank"], cmd_top))
    app.add_handler(CommandHandler(["rules", "start", "help"], cmd_rules))
    app.add_handler(CommandHandler("dq", cmd_dq))
    app.add_handler(CallbackQueryHandler(on_review_button, pattern=r"^(dq|ok):"))
    app.add_handler(CommandHandler("undq", cmd_undq))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("debug", cmd_debug))
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
