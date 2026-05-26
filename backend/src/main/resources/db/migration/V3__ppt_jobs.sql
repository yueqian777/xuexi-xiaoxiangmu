CREATE TABLE IF NOT EXISTS ppt_jobs (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    deck_id INTEGER NOT NULL,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0,
    status_text TEXT DEFAULT '',
    error_message TEXT DEFAULT '',
    stop_requested INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    finished_at TEXT DEFAULT '',
    FOREIGN KEY (deck_id) REFERENCES ppt_decks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_ppt_jobs_user_created
    ON ppt_jobs(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ppt_jobs_user_deck
    ON ppt_jobs(user_id, deck_id);
