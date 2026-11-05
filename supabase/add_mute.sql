-- =====================================================================
-- 警告次数 + 禁言阶梯（新增，跑这段即可）
-- =====================================================================
-- 某玩家的有效警告次数（p_event 为空 = 历史全部；有值 = 只算那一周）
create or replace function cb_warn_count(p_user bigint, p_event date default null)
returns int
language sql security definer set search_path = public as $$
  select count(*)::int from cb_violations
   where user_id = p_user and action = 'warned'
     and (p_event is null or event_key = p_event);
$$;

-- 审核人员按「忽略」：最近一次警告不算数
create or replace function cb_unflag(p_user bigint)
returns void
language sql security definer set search_path = public as $$
  update cb_violations set action = 'ignored'
   where id = (select id from cb_violations
                where user_id = p_user and action = 'warned'
                order by id desc limit 1);
$$;

-- /resetwarn：清掉某玩家全部警告次数
create or replace function cb_clear_warns(p_user bigint)
returns int
language plpgsql security definer set search_path = public as $$
declare v int;
begin
  update cb_violations set action = 'cleared' where user_id = p_user and action = 'warned';
  get diagnostics v = row_count;
  return v;
end $$;

revoke all on function cb_warn_count(bigint, date) from public, anon, authenticated;
revoke all on function cb_unflag(bigint)            from public, anon, authenticated;
revoke all on function cb_clear_warns(bigint)       from public, anon, authenticated;
grant execute on function cb_warn_count(bigint, date) to service_role;
grant execute on function cb_unflag(bigint)            to service_role;
grant execute on function cb_clear_warns(bigint)       to service_role;
