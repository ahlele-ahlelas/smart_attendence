-- SnapClass migrations: run once in Supabase SQL Editor.
-- All statements are idempotent and additive; existing data is untouched.

-- 1. Multiple face embeddings per student (recognition accuracy)
alter table students
  add column if not exists face_embeddings jsonb not null default '[]'::jsonb;

-- 2. Explicit class sessions (one row per time attendance is taken)
create table if not exists class_sessions (
  session_id  bigint generated always as identity primary key,
  subject_id  bigint not null,
  started_at  timestamptz not null default now(),
  label       text
);

-- 3. Attendance rows link to their session (nullable: old rows keep working)
alter table attendance_logs
  add column if not exists session_id bigint;
