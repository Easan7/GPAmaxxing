-- Minimal schema for study session action outputs.
-- NOTE: This file is intentionally not auto-executed by the app.

-- Study session header table.
create table if not exists study_sessions (
    id uuid primary key,
    student_id text not null,
    created_at timestamp default now(),
    source_run_id text,
    status text default 'active',
    goal text
);

-- Study session line items generated from plan checklist.
create table if not exists session_items (
    id uuid primary key,
    session_id uuid references study_sessions(id),
    topic text,
    expected_minutes int,
    order_index int,
    status text default 'pending',
    created_at timestamp default now()
);
