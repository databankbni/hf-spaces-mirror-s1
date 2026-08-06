create table if not exists chat_sessions (
  session_id text primary key,
  model text not null,
  updated_at timestamptz not null
);

create table if not exists chat_messages (
  id bigserial primary key,
  session_id text not null references chat_sessions(session_id) on delete cascade,
  role text not null,
  model text not null,
  text text not null,
  created_at timestamptz not null
);

create index if not exists chat_messages_session_id_id_idx
on chat_messages(session_id, id);

create table if not exists training_examples (
  id bigserial primary key,
  session_id text not null references chat_sessions(session_id) on delete cascade,
  model text not null,
  user_text text not null,
  assistant_text text not null,
  prompt text not null,
  context_json jsonb not null,
  created_at timestamptz not null
);

create index if not exists training_examples_session_id_id_idx
on training_examples(session_id, id);
