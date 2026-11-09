-- 002_runtime_settings.sql：运行时可覆盖的模型连接设置（界面自配，优先级高于 .env 与环境变量）。

CREATE TABLE IF NOT EXISTS runtime_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
