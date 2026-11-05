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
   quest - 今日任务进度
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
| `/quest`（或打「任务」） | 所有人 | 今日任务清单 ✅/⬜。审核人员可以 `/quest @username` 看别人的 |
| `/top` | 所有人 | 实时 Top 10 |
| `/topX` | 审核人员 / 管理员 | 和 /top 一样，但 Bot 的回复不会自动删除 |
| `/rulesX` | 审核人员 / 管理员 | 和 /rules 一样，但 Bot 的回复不会自动删除 |
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

## 八、自动删除 Bot 回复（Railway Variables，单位秒，0 = 不删）
| 变量 | 默认 | 删什么 |
|---|---|---|
| `CONGRATS_DELETE_SEC` | 30 | 恭喜完成 5条 / 10条任务 |
| `REPLY_DELETE_SEC` | 20 | /points、/quest、/top、/rules、/id、/debug 等回复 |
| `WARNING_DELETE_SEC` | 0（保留） | 违规警告、/dq /undq 的结果（保留方便之后回复他 unban） |
| `DELETE_COMMAND_MSG` | 1 | 玩家打的 /points、分数 等指令也在 20 秒后删（Bot 要有删除消息权限）；0 = 不删 |

不会删：/topX、/rulesX 的回复，周一赢家公告、客服群名单、私讯审核人员的报告、私聊 Bot 的回复、玩家的聊天消息。

## 九、开始 / 结束活动（审核人员 / 管理员）
| 指令 | 作用 |
|---|---|
| `/eventend` | 结束活动：停止计分、不抓链接、玩家的 /points /quest /top /rules / 分数 / 任务 都回复「没有进行中」、周一不自动发名单。积分保留 |
| `/eventstart` | 重新开始，全部恢复 |
| `/eventstatus` | 查看现在是开始还是结束 |
| `/eventreset` | 本周积分清零（按按钮确认，清零前先私讯名单备份） |
| `/eventreset all` | 全部资料清零（测试完、正式开始前用） |

状态存在 Supabase 的 `cb_settings` 表，Bot 重启也会记得。第一次用前要在 Supabase 跑 `supabase/add_event_switch.sql`。
开始 / 结束时会在活动群发公告；不想发就在 Railway 加 `ANNOUNCE_EVENT_SWITCH=0`。

## 十、换群 / 设定活动群（审核人员）
| 指令 | 作用 |
|---|---|
| `/setgroup` | 在要做活动的群里打：只用这个群（其他群移除） |
| `/setgroup add` | 在群里打：加上这个群（多个群，分数合并成一个排行榜） |

- 设定存在 Supabase，优先于 Railway 的 `GROUP_IDS`，Bot 重启也记得
- 普通群被 Telegram 升级成超级群（换了 ID）时，Bot 会自动跟上新 ID
- ⚠️ 测试群不要加进活动群，否则测试的分数会上榜。正式开始前：正式群打 `/setgroup` → `/eventreset all`

## 十一、全新安装（从零开始）
1. Supabase SQL Editor 跑 `supabase/schema.sql`（已包含全部表和函数，含活动开关、清零）
2. 代码上传 GitHub → Railway 连 repo → Variables 填 `BOT_TOKEN`、`SUPABASE_URL`、`SUPABASE_SERVICE_KEY`、`REVIEWER_IDS`、`CS_CHAT_ID`
3. BotFather `/setprivacy` → Disable；Bot 拉进活动群设管理员（删除消息权限）
4. 活动群里审核人员打 `/setgroup`，再用普通号打 `/debug` 检查
5. 审核人员打 `/list` 看全部指令

（`add_event_switch.sql`、`add_reset.sql` 只给旧版升级用；全新安装跑 `schema.sql` 就够）

## 十二、华语群 + 马来文群
| 群 | ID | 语言 |
|---|---|---|
| 华语群 | `-1004398257314` | 华语（zh） |
| 马来文群 | `-1003974610649` | 马来文（ms） |

- 设定：华语群打 `/setgroup zh`，马来文群打 `/setgroup add ms`
- 玩家看到的所有文字（/points、/quest、/top、/rules、警告、恭喜、活动开始/结束、周一赢家公告）按群的语言显示
- 审核人员看到的（违规报告、/debug、/list、客服名单）一律华语
- 私聊 Bot：玩家 Telegram 语言是马来文 / 印尼文就用马来文，其他用华语
- 马来文群也可以直接打 `markah`、`skor`（查分）或 `misi`、`tugasan`（任务）
- **两个群分数合并，只有一个排行榜、一份 Top 20**
- 要改任何玩家看到的文字：改 `texts.py`

## 十三、发链接：警告 + 禁言阶梯
| 第几次 | 处罚 |
|---|---|
| 第 1 次 | 禁言 1 天 |
| 第 2 次 | 禁言 7 天 |
| 第 3 次起 | 永久禁言（还在群里、看得到消息，但不能发言） |

- 次数是**历史累计**（`WARN_COUNT_SCOPE=week` 可改成每周一重新算）
- 阶梯可改：Railway 加 `MUTE_STEPS=1d,7d,perm`（h = 小时，d = 天，perm = 永久；空的 = 只警告不禁言）
- 群里的警告 2 小时后自动删除（`WARNING_DELETE_SEC=7200`）
- Bot 要有群管理员的「**封禁用户**」权限才能禁言；`/groups`、`/debug` 可以检查
- 审核人员按「✅ 忽略」= 解除禁言 + 这次不算次数 + 删警告
- `/unmute @username`：解除禁言（私讯 Bot 打 = 所有活动群）
- `/resetwarn @username`：警告次数清零
- 第一次用要在 Supabase 跑 `supabase/add_mute.sql`
