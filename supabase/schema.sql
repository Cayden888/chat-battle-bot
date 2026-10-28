-- =====================================================================
-- 终极聊天争霸赛 THE ULTIMATE CHAT BATTLE — Supabase schema
-- 在 Supabase → SQL Editor 里整段运行一次即可（可重复运行）
-- =====================================================================

-- 玩家基本资料（跨期累计）
create table if not exists cb_users (
  user_id         bigint primary key,
  username        text,
  full_name       text,
  lifetime_valid  int not null default 0,      -- 历史有效发言数（用来判断是不是新号来钓鱼）
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

-- 每一期（每周）玩家成绩
create table if not exists cb_event_users (
  event_key      date   not null,              -- 本期开始的那个周一
  user_id        bigint not null references cb_users(user_id),
  points         int    not null default 0,
  valid_msgs     int    not null default 0,
  disqualified   boolean not null default false,
  dq_reason      text,
  last_valid_at  timestamptz,
  primary key (event_key, user_id)
);

-- 每天的任务进度（5条 / 10条）
create table if not exists cb_daily (
  event_key   date   not null,
  user_id     bigint not null,
  day         date   not null,
  valid_msgs  int    not null default 0,
  points      int    not null default 0,
  primary key (event_key, user_id, day)
);

-- 防重复内容：只存内容的 hash，不存聊天原文
create table if not exists cb_msg_hashes (
  event_key     date   not null,
  user_id       bigint not null,
  content_hash  text   not null,
  created_at    timestamptz not null default now(),
  primary key (event_key, user_id, content_hash)
);

-- 违规记录（发 Link / QR）
create table if not exists cb_violations (
  id          bigserial primary key,
  event_key   date,
  user_id     bigint,
  kind        text,      -- link / qr / manual
  action      text,      -- warned（自动警告）/ dq_by_<审核人ID> / 手动原因
  snippet     text,
  created_at  timestamptz not null default now()
);

create index if not exists cb_event_users_rank_idx
  on cb_event_users (event_key, disqualified, points desc, last_valid_at asc);

-- 只允许 service_role（Bot）访问
alter table cb_users        enable row level security;
alter table cb_event_users  enable row level security;
alter table cb_daily        enable row level security;
alter table cb_msg_hashes   enable row level security;
alter table cb_violations   enable row level security;


-- ---------------------------------------------------------------------
-- 记录一条“已通过文字过滤”的发言，并计分（原子操作）
-- 计分规则（每天按马来西亚时间重置）：
--   每条有效发言 +1
--   当天第 5 条   额外 +5
--   当天第 10 条  额外 +5（10条任务） +5（完成全部任务） = +10
--   无上限
-- ---------------------------------------------------------------------
create or replace function cb_record_message(
  p_event        date,
  p_day          date,
  p_user         bigint,
  p_username     text,
  p_name         text,
  p_hash         text,
  p_min_interval int default 3
) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  v_eu      cb_event_users%rowtype;
  v_rows    int;
  v_daily   int;
  v_bonus   int := 0;
  v_award   int;
  v_points  int;
begin
  insert into cb_users (user_id, username, full_name)
  values (p_user, p_username, p_name)
  on conflict (user_id) do update
    set username = excluded.username, full_name = excluded.full_name, updated_at = now();

  insert into cb_event_users (event_key, user_id) values (p_event, p_user)
  on conflict do nothing;

  select * into v_eu from cb_event_users
   where event_key = p_event and user_id = p_user
   for update;

  if v_eu.disqualified then
    return jsonb_build_object('status', 'disqualified', 'points', v_eu.points);
  end if;

  -- 刷屏：距离上一条有效发言太近
  if v_eu.last_valid_at is not null
     and now() - v_eu.last_valid_at < make_interval(secs => p_min_interval) then
    return jsonb_build_object('status', 'too_fast', 'points', v_eu.points);
  end if;

  -- 重复内容（本期内同一个人发过一样的内容）
  insert into cb_msg_hashes (event_key, user_id, content_hash)
  values (p_event, p_user, p_hash)
  on conflict do nothing;
  get diagnostics v_rows = row_count;
  if v_rows = 0 then
    return jsonb_build_object('status', 'duplicate', 'points', v_eu.points);
  end if;

  insert into cb_daily (event_key, user_id, day) values (p_event, p_user, p_day)
  on conflict do nothing;

  update cb_daily set valid_msgs = valid_msgs + 1
   where event_key = p_event and user_id = p_user and day = p_day
   returning valid_msgs into v_daily;

  if v_daily = 5 then
    v_bonus := 5;
  elsif v_daily = 10 then
    v_bonus := 10;
  end if;
  v_award := 1 + v_bonus;

  update cb_daily set points = points + v_award
   where event_key = p_event and user_id = p_user and day = p_day;

  update cb_event_users
     set points = points + v_award,
         valid_msgs = valid_msgs + 1,
         last_valid_at = now()
   where event_key = p_event and user_id = p_user
   returning points into v_points;

  update cb_users set lifetime_valid = lifetime_valid + 1 where user_id = p_user;

  return jsonb_build_object(
    'status', 'ok', 'award', v_award, 'bonus', v_bonus,
    'daily', v_daily, 'points', v_points
  );
end $$;


-- 取消资格（审核人员按按钮 或 管理员 /dq），同时写记录
create or replace function cb_disqualify(
  p_event    date,
  p_user     bigint,
  p_username text,
  p_name     text,
  p_kind     text,
  p_action   text,
  p_snippet  text
) returns void
language plpgsql security definer set search_path = public as $$
begin
  insert into cb_users (user_id, username, full_name)
  values (p_user, p_username, p_name)
  on conflict (user_id) do update
    set username = coalesce(excluded.username, cb_users.username),
        full_name = coalesce(excluded.full_name, cb_users.full_name),
        updated_at = now();

  insert into cb_event_users (event_key, user_id, disqualified, dq_reason)
  values (p_event, p_user, true, p_kind)
  on conflict (event_key, user_id) do update
    set disqualified = true, dq_reason = excluded.dq_reason;

  insert into cb_violations (event_key, user_id, kind, action, snippet)
  values (p_event, p_user, p_kind, p_action, left(p_snippet, 300));
end $$;


-- 记录违规（只警告，不取消资格），返回本期违规次数
create or replace function cb_flag(
  p_event    date,
  p_user     bigint,
  p_username text,
  p_name     text,
  p_kind     text,
  p_snippet  text
) returns int
language plpgsql security definer set search_path = public as $$
declare v_count int;
begin
  insert into cb_users (user_id, username, full_name)
  values (p_user, p_username, p_name)
  on conflict (user_id) do update
    set username = excluded.username, full_name = excluded.full_name, updated_at = now();

  insert into cb_violations (event_key, user_id, kind, action, snippet)
  values (p_event, p_user, p_kind, 'warned', left(p_snippet, 300));

  select count(*) into v_count from cb_violations
   where event_key = p_event and user_id = p_user and action = 'warned';
  return v_count;
end $$;


-- 恢复资格
create or replace function cb_undq(p_event date, p_user bigint)
returns void
language sql security definer set search_path = public as $$
  update cb_event_users set disqualified = false, dq_reason = null
   where event_key = p_event and user_id = p_user;
$$;


-- 排行榜（同分时，先达到该分数的人排前面）
create or replace function cb_leaderboard(p_event date, p_limit int default 20)
returns table (
  rank        int,
  user_id     bigint,
  username    text,
  full_name   text,
  points      int,
  valid_msgs  int
)
language sql security definer set search_path = public as $$
  select (row_number() over (order by e.points desc, e.last_valid_at asc))::int,
         e.user_id, u.username, u.full_name, e.points, e.valid_msgs
    from cb_event_users e
    join cb_users u using (user_id)
   where e.event_key = p_event and not e.disqualified and e.points > 0
   order by e.points desc, e.last_valid_at asc
   limit p_limit;
$$;


-- 玩家查自己的分数（/points 用；Daily Popup Bot 也可以直接调用这个）
create or replace function cb_my_stats(p_event date, p_day date, p_user bigint)
returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  v_eu    cb_event_users%rowtype;
  v_today int := 0;
  v_rank  int;
begin
  select * into v_eu from cb_event_users where event_key = p_event and user_id = p_user;
  if not found then
    return jsonb_build_object('points', 0, 'rank', null, 'today', 0, 'disqualified', false);
  end if;

  select coalesce(valid_msgs, 0) into v_today
    from cb_daily where event_key = p_event and user_id = p_user and day = p_day;

  if not v_eu.disqualified and v_eu.points > 0 then
    select count(*) + 1 into v_rank
      from cb_event_users
     where event_key = p_event and not disqualified
       and (points > v_eu.points
            or (points = v_eu.points and last_valid_at < v_eu.last_valid_at));
  end if;

  return jsonb_build_object(
    'points', v_eu.points, 'rank', v_rank, 'today', coalesce(v_today, 0),
    'disqualified', v_eu.disqualified, 'dq_reason', v_eu.dq_reason
  );
end $$;


revoke all on function cb_record_message(date, date, bigint, text, text, text, int) from public, anon, authenticated;
revoke all on function cb_disqualify(date, bigint, text, text, text, text, text)     from public, anon, authenticated;
revoke all on function cb_flag(date, bigint, text, text, text, text)               from public, anon, authenticated;
revoke all on function cb_undq(date, bigint)                                          from public, anon, authenticated;
revoke all on function cb_leaderboard(date, int)                                      from public, anon, authenticated;
revoke all on function cb_my_stats(date, date, bigint)                                from public, anon, authenticated;
grant execute on function cb_record_message(date, date, bigint, text, text, text, int) to service_role;
grant execute on function cb_disqualify(date, bigint, text, text, text, text, text)     to service_role;
grant execute on function cb_flag(date, bigint, text, text, text, text)               to service_role;
grant execute on function cb_undq(date, bigint)                                          to service_role;
grant execute on function cb_leaderboard(date, int)                                      to service_role;
grant execute on function cb_my_stats(date, date, bigint)                                to service_role;
