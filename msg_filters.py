"""判断一条消息：有没有 Link / 是不是有效发言。纯函数，方便测试。"""
import hashlib
import re
import unicodedata

# ---- Link 检测 -------------------------------------------------------------
_TLDS = (
    "com|net|org|xyz|top|io|me|cc|vip|link|site|online|shop|app|club|live|info|"
    "biz|pro|win|bet|asia|my|sg|cn|hk|tw|ly|gg|to|co|ru|in|ws|fun|icu|buzz|tk"
)
LINK_RE = re.compile(
    r"(https?://|www\.|t\.me/|telegram\.(me|dog)/|wa\.me/|"
    r"\b[a-z0-9][a-z0-9-]{1,62}\s?\.\s?(" + _TLDS + r")\b(/|\s|$))",
    re.IGNORECASE,
)
# 常见变形：t。me / t点me / tme/xxx
OBFUSCATED_RE = re.compile(r"t\s*[\.。点]\s*me\s*/|@\w+bot\b", re.IGNORECASE)


def has_link(text: str, entities=()) -> bool:
    for e in entities or ():
        if getattr(e, "type", None) in ("url", "text_link"):
            return True
    if not text:
        return False
    return bool(LINK_RE.search(text) or OBFUSCATED_RE.search(text))


# ---- 有效发言判定 ----------------------------------------------------------
def _is_meaningful_char(ch: str) -> bool:
    """字母 / 数字 / 汉字算有效字符；表情、符号、标点、空白都不算。"""
    cat = unicodedata.category(ch)
    return cat[0] in ("L", "N")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    return "".join(ch for ch in text if _is_meaningful_char(ch))


def content_hash(norm: str) -> str:
    # 把连续重复的字压成一个：「哈哈哈哈」和「哈哈」视为同一句
    collapsed = re.sub(r"(.)\1+", r"\1", norm)
    return hashlib.sha256(collapsed.encode()).hexdigest()[:32]


def check_valid(text: str) -> tuple[bool, str, str]:
    """返回 (是否有效, 原因, 标准化后的文本)。"""
    norm = normalize(text)
    if not norm:
        return False, "only_emoji_or_symbols", norm
    if len(norm) < 2:
        return False, "single_char", norm
    if len(set(norm)) < 2:
        return False, "same_char_repeated", norm      # 哈哈哈哈 / 111111 / aaaa
    if norm.isdigit():
        return False, "digits_only", norm
    # 同一小段一直重复：哈喽哈喽哈喽 / 666 777 → 去重后太短
    if len(norm) >= 6 and len(set(norm)) <= 2:
        return False, "repeated_pattern", norm
    return True, "ok", norm
