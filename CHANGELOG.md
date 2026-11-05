# 版本记录

## 2026-11-05（目前版本）
- 发链接自动禁言：第 1 次 1 天、第 2 次 7 天、第 3 次永久禁言（可看群，不踢）
- 群警告 2 小时后自动删除（华语 / 马来文都一样）
- 「✅ 忽略」= 解除禁言 + 不算次数 + 删警告
- 新指令：/unmute、/resetwarn
- /groups、/debug 检查「封禁用户」权限
- /rules 显示禁言阶梯
- /dq /undq 的结果不会自动删除
- 新增 Supabase：add_mute.sql（cb_warn_count / cb_unflag / cb_clear_warns）
- 二维码不再警告（只是不计分）；/staff 工作人员名单；/groups

## 2026-11-03 b
- 华语群 + 马来文群：每个群用自己的语言（新文件 `texts.py` 放所有玩家看到的文字）
- `/setgroup add ms` / `/setgroup zh`：设定群语言（存在 Supabase）
- 马来文关键字：markah、skor、mata saya（查分）；misi、tugasan（任务）
- 活动开始/结束公告、周一赢家公告：每个群各用自己的语言
- 两个群分数合并，一个排行榜

## 2026-11-03 a
- `/setgroup`、`/setgroup add`：在群里设定活动群；群升级换 ID 自动跟上
- `/eventreset`、`/eventreset all`：一键清零（按钮确认 + 先备份名单）
- `/eventstart`、`/eventend`、`/eventstatus`：活动开关（存在 Supabase）
- `/report last`、`/report 2`、`/report 2026-10-26`：任何一周的名单
- 周一名单同时发客服群 + 私讯审核人员
- `/list`：审核人员指令清单（群里打会改成私讯）
- `/quest` / 「任务」：今日任务清单；审核人员可 `/quest @username`
- `/dq`、`/undq` 支持 @username
- `/topX`、`/rulesX`：审核人员专用，不自动删除
- 自动删除：恭喜 30 秒、指令回复 20 秒、玩家指令一起删；违规警告保留
- 审核人员按「忽略」→ 自动删除群里的警告
- 违规（Link / QR）只警告 + 私讯审核人员，不删消息、不 Ban、不自动取消资格
- `/debug`：一次检查所有设定
- 「分数」「积分」「查分」等中文关键字可查分

## 2026-10-28
- 第一版：计分、/points、/top、/rules、周一 Top 20 名单
