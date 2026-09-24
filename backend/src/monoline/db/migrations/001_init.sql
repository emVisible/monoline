-- Monoline schema v1 (M1). SQLite, WAL. Durability + resumability live here,
-- NOT in the stateless Node sidecar.
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  slug TEXT,
  title TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  script_text TEXT NOT NULL,
  config_json TEXT NOT NULL,
  canvas_json TEXT NOT NULL,
  total_duration REAL,
  hf_version TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS job_stages (
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  key TEXT NOT NULL,
  seq INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  input_hash TEXT,
  output_json TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  started_at TEXT,
  finished_at TEXT,
  duration_ms INTEGER,
  error TEXT,
  PRIMARY KEY (job_id, key)
);

CREATE TABLE IF NOT EXISTS segments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  i INTEGER NOT NULL,
  text TEXT NOT NULL,
  line_no INTEGER,
  wav_path TEXT,
  wav_bytes INTEGER,
  tts_duration REAL,
  start REAL,
  end REAL,
  norm_duration REAL GENERATED ALWAYS AS (round(end - start, 3)) STORED,
  audio_source TEXT NOT NULL DEFAULT 'tts',
  voice TEXT,
  lang TEXT,
  speed REAL,
  UNIQUE (job_id, i)
);

CREATE TABLE IF NOT EXISTS scene_plans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  schema TEXT NOT NULL DEFAULT 'sceneplan/v1',
  version INTEGER NOT NULL,
  plan_json TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'rules',
  warnings_json TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  stage_key TEXT,
  kind TEXT NOT NULL,
  rel_path TEXT,
  abs_path TEXT,
  mime TEXT,
  size_bytes INTEGER,
  sha256 TEXT,
  duration_seconds REAL,
  fps INTEGER,
  width INTEGER,
  height INTEGER,
  remote_token TEXT,
  remote_expires_at TEXT,
  state TEXT NOT NULL DEFAULT 'local',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  ts TEXT NOT NULL,
  kind TEXT NOT NULL,
  stage_key TEXT,
  level TEXT NOT NULL DEFAULT 'info',
  message TEXT,
  data_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_job ON events(job_id, id);

CREATE TABLE IF NOT EXISTS presets (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  config_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);
