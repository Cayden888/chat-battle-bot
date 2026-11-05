-- =====================================================================
-- 活动开关（/eventstart /eventend）—— 新增，跑这段即可
-- =====================================================================
create table if not exists cb_settings (
  key         text primary key,
  value       text,
  updated_by  bigint,
  updated_at  timestamptz not null default now()
);
alter table cb_settings enable row level security;
grant select, insert, update, delete on cb_settings to service_role;
