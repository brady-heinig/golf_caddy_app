-- Postgres schema for Supabase (replaces sqlite-specific AUTOINCREMENT/datetime('now')).

CREATE TABLE IF NOT EXISTS users (
  id BIGSERIAL PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  is_admin BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_settings (
  user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  handicap_index DOUBLE PRECISION,
  bag_json TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rounds (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  course_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  current_hole INTEGER NOT NULL DEFAULT 1,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  notes TEXT
);

CREATE TABLE IF NOT EXISTS chat_messages (
  id BIGSERIAL PRIMARY KEY,
  round_id BIGINT NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
  hole INTEGER NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS shots (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  round_id BIGINT REFERENCES rounds(id) ON DELETE SET NULL,
  course_id TEXT NOT NULL,
  hole INTEGER NOT NULL,
  shot_number INTEGER NOT NULL,
  club TEXT NOT NULL,
  distance_to_pin_before INTEGER,
  distance_achieved INTEGER,
  lie TEXT,
  shot_shape TEXT,
  result TEXT,
  notes TEXT,
  proximity_ft INTEGER,
  logged_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

