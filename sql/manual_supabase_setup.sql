-- FocusMate permanent media storage setup
-- Run in Supabase SQL Editor.
-- No media bytes are stored by these SQL statements.

-- 1) Create/ensure one PUBLIC bucket for FocusMate media.
-- Public read is used so stored media URLs do not expire.
insert into storage.buckets (id, name, public)
values ('focusemate-media', 'focusemate-media', true)
on conflict (id) do update set public = true;

-- 2) The app no longer expires chat media automatically.
-- Keep the legacy columns for DB compatibility, but make all existing values NULL.
update public.messages
set media_expires_at = null
where media_expires_at is not null;

update public.direct_messages
set media_expires_at = null
where media_expires_at is not null;

-- 3) Verify the bucket.
select id, name, public
from storage.buckets
where id = 'focusemate-media';

-- 4) Verify chat columns still exist for compatibility.
select table_name, column_name
from information_schema.columns
where table_schema = 'public'
  and table_name in ('messages', 'direct_messages')
  and column_name = 'media_expires_at'
order by table_name;

-- 5) Check existing resources that still point to the old Render filesystem.
-- DO NOT delete these rows automatically.
select id, title, resource_type, link
from public.resources
where link like '%/static/%'
order by id desc;

-- 6) Check existing chat media still pointing to the old Render filesystem.
-- DO NOT delete these rows automatically.
select id, message_type, content, created_at
from public.messages
where message_type in ('image','video','audio','file')
  and content like '%/static/%'
order by id desc;

select id, message_type, content, created_at
from public.direct_messages
where message_type in ('image','video','audio','file')
  and content like '%/static/%'
order by id desc;
