"""
玩家会看到的所有文字（华语 zh / 马来文 ms）
==========================================
以后要改字，直接改这里就好。{xxx} 是 Bot 会自动填进去的内容，不要删掉。
哪个群用哪种语言：config.py 的 GROUP_LANGS，或在群里打 /setgroup add ms
审核人员看到的（违规报告、/debug、/list、客服名单）一律是华语。
"""

T = {
    # ---- 活动开关 ----
    "closed": {
        "zh": "⏸ 【终极聊天争霸赛】目前没有进行中，等活动开始后再来哦！",
        "ms": "⏸ THE ULTIMATE CHAT BATTLE tidak berlangsung sekarang. Sila datang semula apabila acara bermula!",
    },
    "event_started": {
        "zh": "🏁 <b>终极聊天争霸赛 开始啦！</b>\n从现在起在群里聊天就能拿积分，输入 /rules 查看规则。",
        "ms": "🏁 <b>THE ULTIMATE CHAT BATTLE sudah bermula!</b>\nMulai sekarang, berbual dalam grup untuk kumpul mata. Taip /rules untuk lihat peraturan.",
    },
    "event_ended": {
        "zh": "⏸ <b>终极聊天争霸赛 已结束</b>\n现在聊天不会再计分，感谢大家参与！",
        "ms": "⏸ <b>THE ULTIMATE CHAT BATTLE telah tamat</b>\nMesej tidak akan dikira mata lagi. Terima kasih atas penyertaan anda!",
    },

    # ---- 违规警告 ----
    "label_link": {"zh": "发送链接", "ms": "hantar pautan"},
    "label_qr": {"zh": "发送二维码", "ms": "hantar kod QR"},
    "warning": {
        "zh": "⚠️ {name} 请勿在群内{label}。\n这违反了【终极聊天争霸赛】规则（{count}）。{penalty}\n"
              "已提交管理员审核，可能会被取消本期活动资格。",
        "ms": "⚠️ {name}, jangan {label} dalam grup.\nIni melanggar peraturan THE ULTIMATE CHAT BATTLE ({count}).{penalty}\n"
              "Perkara ini telah dihantar kepada admin untuk semakan. Kelayakan anda minggu ini mungkin dibatalkan.",
    },
    "warn_count_all": {"zh": "第 {n} 次警告", "ms": "amaran ke-{n}"},
    "warn_count_week": {"zh": "本周第 {n} 次警告", "ms": "amaran ke-{n} minggu ini"},
    "mute_for": {
        "zh": "\n🔇 已禁言 {dur}，时间到会自动恢复。",
        "ms": "\n🔇 Anda disekat daripada menghantar mesej selama {dur}. Sekatan akan ditarik balik secara automatik.",
    },
    "mute_perm": {
        "zh": "\n🔇 已永久禁言：仍然可以看群，但不能发言。",
        "ms": "\n🔇 Anda disekat daripada menghantar mesej secara kekal: masih boleh lihat grup, tetapi tidak boleh berbual.",
    },
    "dur_h": {"zh": "{n} 小时", "ms": "{n} jam"},
    "dur_d": {"zh": "{n} 天", "ms": "{n} hari"},
    "dur_perm": {"zh": "永久禁言（可看群）", "ms": "sekatan kekal (masih boleh lihat grup)"},
    "mute_rule": {
        "zh": "🚫 发链接会被警告并禁言：{steps}\n\n",
        "ms": "🚫 Hantar pautan akan diberi amaran dan disekat: {steps}\n\n",
    },
    "nth": {"zh": "第 {n} 次 {d}", "ms": "kali ke-{n} {d}"},
    "nth_more": {"zh": "之后每次 {d}", "ms": "seterusnya {d}"},

    # ---- 恭喜 ----
    "congrats5": {
        "zh": "🎯 {name} 完成今日 5 条有效发言任务，+5 分！",
        "ms": "🎯 {name} telah siapkan misi 5 mesej hari ini, +5 mata!",
    },
    "congrats10": {
        "zh": "🔥 {name} 完成今日 10 条有效发言任务 +5，全部任务达成再 +5！当前 {points} 分",
        "ms": "🔥 {name} telah siapkan misi 10 mesej hari ini +5, semua misi selesai +5 lagi! Jumlah sekarang {points} mata",
    },

    # ---- /points ----
    "stats_title": {"zh": "🏆 <b>终极聊天争霸赛</b>  {start} – {end}", "ms": "🏆 <b>THE ULTIMATE CHAT BATTLE</b>  {start} – {end}"},
    "dq_status": {
        "zh": "❌ 本期资格已取消（违规发送链接）",
        "ms": "❌ Kelayakan anda minggu ini telah dibatalkan (menghantar pautan)",
    },
    "stats_points": {"zh": "⭐ 本期积分：<b>{p}</b> 分", "ms": "⭐ Mata minggu ini: <b>{p}</b>"},
    "stats_rank": {"zh": "📊 当前排名：<b>#{r}</b>", "ms": "📊 Kedudukan semasa: <b>#{r}</b>"},
    "stats_norank": {"zh": "📊 当前排名：未上榜", "ms": "📊 Kedudukan semasa: belum tersenarai"},
    "stats_today": {"zh": "💬 今日有效发言：{n} 条", "ms": "💬 Mesej sah hari ini: {n}"},
    "stats_need5": {
        "zh": "🎯 再聊 {n} 条完成【5条任务】+5 分",
        "ms": "🎯 {n} mesej lagi untuk siapkan misi 5 mesej (+5 mata)",
    },
    "stats_need10": {
        "zh": "🎯 再聊 {n} 条完成【10条任务】+5，并解锁【全部任务】+5",
        "ms": "🎯 {n} mesej lagi untuk siapkan misi 10 mesej (+5) dan bonus semua misi (+5)",
    },
    "stats_done": {
        "zh": "✅ 今日任务全部完成！继续聊天每条 +1 分（无上限）",
        "ms": "✅ Semua misi hari ini selesai! Setiap mesej seterusnya +1 mata (tiada had)",
    },
    "stats_intop": {"zh": "🔥 你在 Top {n} 内，保持住！", "ms": "🔥 Anda dalam Top {n}, teruskan!"},

    # ---- /top ----
    "top_empty": {
        "zh": "🏆 本期还没有人上榜，快来聊天抢第一！",
        "ms": "🏆 Belum ada sesiapa dalam carta minggu ini. Jom berbual dan rebut tempat pertama!",
    },
    "top_title": {"zh": "🏆 <b>终极聊天争霸赛 · 实时 Top 10</b>", "ms": "🏆 <b>THE ULTIMATE CHAT BATTLE · Top 10 Semasa</b>"},
    "top_footer": {"zh": "输入 /points 查看自己的分数", "ms": "Taip /points untuk lihat mata anda"},
    "pts": {"zh": "分", "ms": "mata"},

    # ---- /rules ----
    "rules": {
        "zh": (
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
            "{mute_rule}"
            "输入 /points 查看分数，/quest 查看今日任务，/top 查看排行榜"
        ),
        "ms": (
            "🏆 <b>THE ULTIMATE CHAT BATTLE</b>\n"
            "⏰ Setiap Isnin {roll} hingga Isnin berikutnya {roll}, keputusan diumumkan Isnin {rep}\n\n"
            "<b>Cara kumpul mata</b>\n"
            "1. Setiap mesej sah +1 mata\n"
            "2. Hantar 5 mesej sah sehari +5 mata\n"
            "3. Hantar 10 mesej sah sehari, tambahan +5 mata\n"
            "4. Siapkan semua misi di atas, tambahan +5 mata\n"
            "Tiada had mata!\n\n"
            "🎁 Top {n} masing-masing dapat {prize} (perlu turnover {turn} untuk menuntut)\n\n"
            "✅ Berbual santai, sertai perbincangan, kongsi pengalaman\n"
            "❌ Tidak dikira: kandungan berulang / emoji atau simbol sahaja / satu huruf / nombor sahaja / "
            "spam / mesej forward / sticker atau gambar\n"
            "{mute_rule}"
            "Taip /points untuk mata, /quest untuk misi hari ini, /top untuk carta"
        ),
    },

    # ---- /quest ----
    "quest_title": {"zh": "📋 <b>今日任务</b>  {date}", "ms": "📋 <b>Misi Hari Ini</b>  {date}"},
    "quest_1": {
        "zh": "{b} 有效发言  每条 +1 分（已发 {n} 条，无上限）",
        "ms": "{b} Mesej sah  +1 mata setiap satu ({n} dihantar, tiada had)",
    },
    "quest_5": {"zh": "{b} 发满 5 条  +5 分（{x}/5）", "ms": "{b} Hantar 5 mesej  +5 mata ({x}/5)"},
    "quest_10": {"zh": "{b} 发满 10 条  +5 分（{x}/10）", "ms": "{b} Hantar 10 mesej  +5 mata ({x}/10)"},
    "quest_all": {"zh": "{b} 完成全部任务  +5 分", "ms": "{b} Siapkan semua misi  +5 mata"},
    "quest_earned": {
        "zh": "⭐ 今日已得 <b>{e}</b> 分  |  本期总分 <b>{p}</b> 分",
        "ms": "⭐ Hari ini: <b>{e}</b> mata  |  Jumlah minggu ini: <b>{p}</b> mata",
    },
    "quest_need5": {"zh": "🎯 再聊 {n} 条拿 +5 分", "ms": "🎯 {n} mesej lagi untuk +5 mata"},
    "quest_need10": {
        "zh": "🎯 再聊 {n} 条拿 +10 分（10条任务 + 全部完成）",
        "ms": "🎯 {n} mesej lagi untuk +10 mata (misi 10 mesej + semua misi)",
    },
    "quest_done": {
        "zh": "🔥 今日任务全部完成！继续聊天每条 +1 分",
        "ms": "🔥 Semua misi hari ini selesai! Setiap mesej seterusnya +1 mata",
    },
    "quest_reset": {
        "zh": "⏰ 任务每天 00:00（马来西亚时间）重置",
        "ms": "⏰ Misi ditetapkan semula setiap hari pada 00:00 (waktu Malaysia)",
    },

    # ---- 权限 / 审核结果（会在群里出现）----
    "admin_only": {
        "zh": "只有审核人员 / 管理员可以使用这个指令。",
        "ms": "Hanya penyemak / admin boleh guna arahan ini.",
    },
    "quest_others_only": {
        "zh": "只有管理员 / 审核人员可以查看别人的任务。",
        "ms": "Hanya admin / penyemak boleh lihat misi orang lain.",
    },
    "dq_done": {
        "zh": "❌ 已取消 {who} (<code>{uid}</code>) 本期资格。",
        "ms": "❌ Kelayakan {who} (<code>{uid}</code>) untuk minggu ini telah dibatalkan.",
    },
    "undq_done": {
        "zh": "✅ 已恢复 {who} (<code>{uid}</code>) 本期资格，积分 {p} 分保留。",
        "ms": "✅ Kelayakan {who} (<code>{uid}</code>) untuk minggu ini telah dipulihkan, {p} mata dikekalkan.",
    },

    # ---- 周一赢家公告 ----
    "winners": {
        "zh": ("🎉 <b>终极聊天争霸赛 本期赢家出炉！</b>\n{period}\n\n{body}\n\n"
               "🎁 以上 Top {n} 各得 {prize}\n"
               "📌 需有 {turn} 流水才能领取，请自行联系客服领取奖励\n\n"
               "新一期已经开始，继续聊天冲榜吧！/points 查分"),
        "ms": ("🎉 <b>Pemenang THE ULTIMATE CHAT BATTLE minggu ini!</b>\n{period}\n\n{body}\n\n"
               "🎁 Top {n} di atas masing-masing dapat {prize}\n"
               "📌 Perlu turnover {turn} untuk menuntut. Sila hubungi khidmat pelanggan untuk menuntut hadiah\n\n"
               "Minggu baharu sudah bermula, teruskan berbual untuk naik carta! Taip /points untuk semak mata"),
    },
}

LANGS = ("zh", "ms")


def t(lang: str, key: str, **kw) -> str:
    entry = T[key]
    text = entry.get(lang) or entry["zh"]
    return text.format(**kw) if kw else text
