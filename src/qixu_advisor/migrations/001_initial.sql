-- 001_initial.sql：S2 会话存储初始 schema（customers/conversations/messages/preferences/generations/draft_revisions/draft_actions + meta）。

CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY,
    version INTEGER NOT NULL,
    profile_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    customer_id TEXT REFERENCES customers(id),
    scenario TEXT,
    settings_json TEXT NOT NULL,
    current_need TEXT,
    budget_cny REAL,
    occasion TEXT,
    event_id TEXT,
    product_ids_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL,
    external_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (conversation_id, source, external_id)
);

CREATE TABLE IF NOT EXISTS preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    kind TEXT NOT NULL,
    original_text TEXT NOT NULL,
    source TEXT NOT NULL,
    explicit INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS generations (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    request_key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL,
    run_id TEXT,
    case_id TEXT,
    expected_version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (conversation_id, request_key)
);

CREATE TABLE IF NOT EXISTS draft_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generation_id TEXT NOT NULL REFERENCES generations(id),
    candidate_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS draft_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_revision_id INTEGER NOT NULL REFERENCES draft_revisions(id),
    action TEXT NOT NULL,
    copied_text TEXT NOT NULL DEFAULT '',
    editor TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
