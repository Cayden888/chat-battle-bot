"""所有配置从环境变量读取（Railway → Variables）。"""
import os
from datetime import datetime, timedelta, time, date
from zoneinfo import ZoneInfo


def _ids(name: str) -> set[int]:
    raw = os.getenv(name, "")
    return {int(x) for x in raw.replace(" ", "").split(",") if x.strip().lstrip("-").isdigit()}


def _hhmm(name: str, default: str) -> time:
    h, m = os.getenv(name, default).split(":")
    return time(int(h), int(m))


BOT_TOKEN = os.environ["BOT_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]      # 用 service_role key，不要用 anon key

GROUP_IDS = _ids("GROUP_IDS")          # 参加活动的中文群（可多个，逗号分隔）
CS_CHAT_ID = int(os.getenv("CS_CHAT_ID", "0") or 0)     # 客服群：周一收 Top20 名单
LOG_CHAT_ID = int(os.getenv("LOG_CHAT_ID", "0") or 0)   # 违规日志群（可与客服群相同）
REVIEWER_IDS = _ids("REVIEWER_IDS") or {8875069703}   # 违规审核人员（默认 @nicolenicola），私讯收违规报告
ADMIN_IDS = _ids("ADMIN_IDS")          # 额外管理员（群管理员自动算）

TZ = ZoneInfo(os.getenv("TZ_NAME", "Asia/Kuala_Lumpur"))

# 活动周期：每周一 ROLLOVER_TIME 换期（统计截止 + 新一期开始），REPORT_TIME 发名单
ROLLOVER_TIME = _hhmm("ROLLOVER_TIME", "10:30")
REPORT_TIME = _hhmm("REPORT_TIME", "11:00")

TOP_N = int(os.getenv("TOP_N", "20"))
PRIZE_TEXT = os.getenv("PRIZE_TEXT", "RM8.8")
TURNOVER_REQ = os.getenv("TURNOVER_REQ", "1000")

MIN_INTERVAL_SEC = int(os.getenv("MIN_INTERVAL_SEC", "3"))   # 两条有效发言最少间隔
NEWBIE_THRESHOLD = int(os.getenv("NEWBIE_THRESHOLD", "5"))   # 历史有效发言 < 这个数 + 发Link = 报告里标注「疑似钓鱼」
QR_CHECK = os.getenv("QR_CHECK", "1") == "1"

# ===== 自动删除 Bot 在群里的回复（秒；0 = 不删除）=====
# 以后要改时间：去 Railway → Variables 改这几个值，不用改代码
CONGRATS_DELETE_SEC = int(os.getenv("CONGRATS_DELETE_SEC", "30"))   # 恭喜完成 5条 / 10条任务
REPLY_DELETE_SEC = int(os.getenv("REPLY_DELETE_SEC", "20"))         # /points /quest /top /rules /id /debug 等指令的回复
WARNING_DELETE_SEC = int(os.getenv("WARNING_DELETE_SEC", "0"))      # 违规警告 + /dq /undq 结果（默认 0 = 保留，方便之后回复他 unban）
DELETE_COMMAND_MSG = os.getenv("DELETE_COMMAND_MSG", "0") == "1"    # 1 = 连玩家打的 /points 等指令一起删（Bot 需要管理员「删除消息」权限）
# 不会自动删除：周一赢家公告、客服群名单、私讯给审核人员的报告、私聊 Bot 的回复


def now() -> datetime:
    return datetime.now(TZ)


def event_key_for(dt: datetime) -> date:
    """dt 属于哪一期：以最近一个『周一 ROLLOVER_TIME』为期初，返回那个周一的日期。"""
    dt = dt.astimezone(TZ)
    monday = (dt - timedelta(days=dt.weekday())).date()
    start = datetime.combine(monday, ROLLOVER_TIME, TZ)
    if dt < start:
        monday -= timedelta(days=7)
    return monday


def current_event() -> date:
    return event_key_for(now())


def event_range(key: date) -> tuple[datetime, datetime]:
    start = datetime.combine(key, ROLLOVER_TIME, TZ)
    return start, start + timedelta(days=7)


def today() -> date:
    return now().date()
