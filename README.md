# 🏆 终极聊天争霸赛 THE ULTIMATE CHAT BATTLE — Bot

GitHub → Supabase → Railway。Bot 自动统计群员有效发言、计分、抓 Link/QR（群警告 + 私讯审核人员）、每周一 11AM 把 Top 20 名单发给客服。Bot 不删任何消息、不 Ban 人。

---

## 一、活动规则（Bot 已实现）

| 项目 | 设定 |
|---|---|
| 周期 | 每周一 **10:30** 换期（截止统计 + 新一期开始），周一 **11:00** 发名单（马来西亚时间） |
| 每条有效发言 | +1 分 |
| 当天第 5 条有效发言 | +5 分（5条任务） |
| 当天第 10 条有效发言 | +5（10条任务）+5（全部任务完成）= +10 分 |
| 上限 | 无 |
| 每天满 10 条 | 10 + 5 + 10 = **25 分**，之后每条 +1 |
| 赢家 | 积分 Top 20，各 RM8.8 |
| 领奖条件 | 需 1000 流水 —— **Bot 查不到流水，名单 CSV 留了一栏给客服核对** |

**不计分：**
- 只发表情 / 符号 / 单个字（"好"、"😂😂"、"!!!"）
- 同一个字重复（"哈哈哈哈"、"111111"）、短句循环（"哈喽哈喽哈喽"）
- 同一期内重复发过的内容（"哈哈好" 和 "哈哈哈好!!" 算同一句）
- 3 秒内连发（防刷屏，可调）
- 转发消息、贴纸、纯图片、指令
- 群管理员不参加排名

**发链接 / 二维码 → 只警告 + 送审核（Bot 不删消息、不 Ban、不自动取消资格）：**
- 发链接（http、www、t.me、xxx.com/.vip 等，包括 "t。me" 这类变形）或 **图片里有二维码**：
  1. Bot 在群里回复警告：请勿发送链接，已提交审核，可能被取消本期资格（会显示本期第几次警告）
  2. Bot 私讯审核人员 **@nicolenicola（ID 8875069703）**：玩家 ID、Username、群、积分排名、违规次数、**为什么可能被取消资格**、原内容、原消息链接
  3. 报告下面有两个按钮：**❌ 取消本期资格** / **✅ 忽略**，由审核人员决定
- 之前几乎没聊过天（有效发言 < 5 条）就发 Link，报告会标注 **🎣 疑似钓鱼号**，由管理员自己手动处理（Bot 不 Ban）
- 那条带链接的消息不计分
- 群管理员发链接不处理

⚠️ **@nicolenicola 必须先私讯 Bot 按一次 /start**，不然 Telegram 不允许 Bot 私讯她，会收不到报告。

同分时，**先达到该分数的人排前面**。

---

## 二、部署步骤

### 1. 创建 Bot
1. BotFather → `/newbot` → 拿到 `BOT_TOKEN`
2. BotFather → `/setprivacy` → 选这个 Bot → **Disable**（不关的话 Bot 看不到群里的普通聊天）
3. BotFather → `/setcommands`：
   ```
   points - 查看我的积分和排名
   top - 实时排行榜 Top 10
   rules - 活动规则
   ```
4. 把 Bot 拉进活动群（不需要删除 / 封禁权限，Bot 不会删消息或 Ban 人）
5. 把 Bot 也拉进客服群
6. **@nicolenicola 私讯 Bot 按 /start**（才能收到违规报告）
7. 在每个群里发 `/id`，记下 chat_id（-100 开头）

### 2. Supabase
1. 新建 Project（Region 选 Singapore）
2. SQL Editor → 粘贴 `supabase/schema.sql` 全部内容 → Run（可以重复跑，不会删数据）
3. Settings → API → 复制 **Project URL** 和 **service_role key**

### 3. GitHub
```bash
git init && git add . && git commit -m "chat battle bot"
git remote add origin git@github.com:你的帐号/chat-battle-bot.git
git push -u origin main
```
`.env` 已在 `.gitignore`，token 不会上传。

### 4. Railway
1. New Project → Deploy from GitHub repo → 选这个 repo
2. Variables → 照 `.env.example` 填（至少填：`BOT_TOKEN`、`SUPABASE_URL`、`SUPABASE_SERVICE_KEY`、`GROUP_IDS`、`CS_CHAT_ID`；审核人员默认就是 8875069703）
3. 部署完看 Logs 有 `Chat Battle bot started` 就是成功了
4. **只能开 1 个 replica**（同一个 token 两个实例同时跑会冲突）

---

## 三、指令

| 指令 | 谁 | 作用 |
|---|---|---|
| `/points` | 所有人 | 本期积分、排名、今天还差几条完成任务 |
| `/top` | 所有人 | 实时 Top 10 |
| `/rules` | 所有人 | 活动规则 |
| `/dq 原因` | 管理员 / 审核人员 | 群里**回复**某人消息，或在任何地方 `/dq <user_id> 原因` → 手动取消资格 |
| `/undq` | 管理员 | 回复某人消息或 `/undq <user_id>` → 恢复资格（误判时用） |
| `/report` | 管理员 | 马上拿本期实时 Top 20 名单 |
| `/report last` | 管理员 | 重新拿上一期名单（客服弄丢时用） |
| `/id` | 所有人 | 查 chat_id / user_id |

---

## 四、周一 11AM 自动做的事
1. 客服群收到：Top 20 名单（名字、@username、User ID、积分）+ **CSV 文件**（Excel 可开，有「流水≥1000（客服核对）」和「已派奖」两栏空白）
2. 活动群收到：赢家公告，提醒「需 1000 流水，自行联系客服领取」

客服流程：打开 CSV → 用 User ID 在后台查流水 → 满 1000 才派 RM8.8 → 在「已派奖」打勾。

---

## 五、把 /points 放进 Daily Popup Bot
两个 Bot 共用同一个 Supabase，Daily Popup Bot 直接读分数就好，见 `integrations/daily_popup_points.py`（里面有 Python 和 Node.js 两种接法）。

⚠️ 如果两个 Bot 都在同一个群，群员打 `/points` 两个 Bot 都会回。二选一：
- 在 BotFather 的 commands 里只给其中一个 Bot 设 `points`，并让群员用 `/points@那个Bot名字`；或
- Daily Popup Bot 只在私聊里回 `/points`

---

## 六、可以调的参数（Railway Variables）
见 `.env.example`。常用：
- `MIN_INTERVAL_SEC` 防刷屏间隔，默认 3 秒
- `REVIEWER_IDS` 违规审核人员，默认 8875069703（@nicolenicola），可加多个
- `LOG_CHAT_ID` 选填，违规报告同时发一份到群
- `NEWBIE_THRESHOLD` 报告里标注「疑似钓鱼」的门槛，默认历史有效发言 < 5
- `TOP_N` / `PRIZE_TEXT` / `TURNOVER_REQ` 赢家人数 / 奖励 / 流水要求
- `ROLLOVER_TIME` / `REPORT_TIME` 换期时间 / 发名单时间

## 七、数据表（Supabase）
| 表 | 内容 |
|---|---|
| `cb_users` | 玩家资料、历史有效发言数 |
| `cb_event_users` | 每期积分、是否取消资格 |
| `cb_daily` | 每天任务进度 |
| `cb_msg_hashes` | 防重复（只存 hash，**不存聊天原文**） |
| `cb_violations` | 违规记录 |
