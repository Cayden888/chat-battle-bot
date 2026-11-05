-- =====================================================================
-- 一键清零（/eventreset）—— 新增，跑这段即可
--   p_all = false：只清本周（积分、每日任务、重复记录、违规记录、取消资格）
--   p_all = true ：清掉所有周 + 所有玩家资料（测试用，全部归零）
-- =====================================================================
create or replace function cb_reset(p_event date, p_all boolean default false)
returns jsonb
language plpgsql security definer set search_path = public as $$
declare v_players int;
begin
  if p_all then
    select count(*) into v_players from cb_users;
    -- 每个 delete 都带 where（Supabase 的 safeupdate 不允许没有 where 的 delete）
    delete from cb_msg_hashes  where true;
    delete from cb_daily       where true;
    delete from cb_violations  where true;
    delete from cb_event_users where true;
    delete from cb_users       where true;
  else
    select count(*) into v_players from cb_event_users where event_key = p_event;
    delete from cb_msg_hashes where event_key = p_event;
    delete from cb_daily      where event_key = p_event;
    delete from cb_violations where event_key = p_event;
    delete from cb_event_users where event_key = p_event;
  end if;
  return jsonb_build_object('players', v_players);
end $$;

revoke all on function cb_reset(date, boolean) from public, anon, authenticated;
grant execute on function cb_reset(date, boolean) to service_role;
