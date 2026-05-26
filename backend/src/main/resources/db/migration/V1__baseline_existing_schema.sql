CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    is_active INTEGER NOT NULL DEFAULT 1,
    upload_quota_bytes INTEGER NOT NULL DEFAULT 536870912,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE invites (
    code TEXT PRIMARY KEY,
    role TEXT NOT NULL DEFAULT 'user',
    created_by INTEGER,
    max_uses INTEGER NOT NULL DEFAULT 1,
    used_count INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT,
    upload_quota_bytes INTEGER NOT NULL DEFAULT 536870912,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE study_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 0,
    date TEXT NOT NULL,
    subject TEXT NOT NULL,
    chapter TEXT DEFAULT '',
    title TEXT NOT NULL,
    main_question TEXT NOT NULL,
    mastered_content TEXT DEFAULT '',
    blockers TEXT DEFAULT '',
    wrong_questions TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    mastery INTEGER NOT NULL DEFAULT 0,
    need_review INTEGER NOT NULL DEFAULT 1,
    is_key INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE mainline_anchors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 0,
    session_id INTEGER NOT NULL,
    anchor_code TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT DEFAULT '',
    order_index INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (session_id) REFERENCES study_sessions(id) ON DELETE CASCADE
);

CREATE TABLE branch_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 0,
    session_id INTEGER NOT NULL,
    anchor_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    answer_summary TEXT DEFAULT '',
    understood INTEGER NOT NULL DEFAULT 0,
    need_review INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (session_id) REFERENCES study_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (anchor_id) REFERENCES mainline_anchors(id) ON DELETE CASCADE
);

CREATE TABLE knowledge_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 0,
    subject TEXT NOT NULL,
    topic TEXT NOT NULL,
    core_question TEXT DEFAULT '',
    one_sentence TEXT NOT NULL,
    logic_or_formula TEXT DEFAULT '',
    application TEXT DEFAULT '',
    mastery INTEGER NOT NULL DEFAULT 0,
    need_review INTEGER NOT NULL DEFAULT 1,
    source_session_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (source_session_id) REFERENCES study_sessions(id) ON DELETE SET NULL
);

CREATE TABLE knowledge_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 0,
    source_knowledge_id INTEGER NOT NULL,
    target_knowledge_id INTEGER NOT NULL,
    relation_type TEXT NOT NULL DEFAULT '关联',
    relation_note TEXT DEFAULT '',
    compare_points TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (source_knowledge_id) REFERENCES knowledge_cards(id) ON DELETE CASCADE,
    FOREIGN KEY (target_knowledge_id) REFERENCES knowledge_cards(id) ON DELETE CASCADE,
    CHECK (source_knowledge_id != target_knowledge_id)
);

CREATE TABLE mistakes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 0,
    subject TEXT NOT NULL,
    topic TEXT NOT NULL,
    knowledge_id INTEGER,
    original_question TEXT NOT NULL,
    my_wrong_answer TEXT DEFAULT '',
    correct_idea TEXT NOT NULL,
    cause_category TEXT NOT NULL,
    warning_signal TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    add_to_review INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (knowledge_id) REFERENCES knowledge_cards(id) ON DELETE SET NULL
);

CREATE TABLE review_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 0,
    knowledge_id INTEGER NOT NULL,
    review_date TEXT NOT NULL,
    review_stage TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT '待复习',
    result TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (knowledge_id) REFERENCES knowledge_cards(id) ON DELETE CASCADE
);

CREATE TABLE parking_lot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 0,
    subject TEXT DEFAULT '',
    question TEXT NOT NULL,
    source TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT '未解决',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE ppt_decks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 0,
    filename TEXT NOT NULL,
    title TEXT NOT NULL,
    subject TEXT DEFAULT '',
    category TEXT DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT '使用中',
    file_path TEXT NOT NULL,
    slide_count INTEGER NOT NULL DEFAULT 0,
    outline TEXT DEFAULT '',
    outline_generated_at TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE ppt_slides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 0,
    deck_id INTEGER NOT NULL,
    slide_number INTEGER NOT NULL,
    title TEXT DEFAULT '',
    slide_text TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    image_path TEXT DEFAULT '',
    section_index INTEGER NOT NULL DEFAULT 0,
    page_type TEXT DEFAULT '',
    one_sentence_summary TEXT DEFAULT '',
    slide_role TEXT DEFAULT '',
    key_points TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (deck_id) REFERENCES ppt_decks(id) ON DELETE CASCADE,
    UNIQUE(deck_id, slide_number)
);

CREATE TABLE ppt_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deck_id INTEGER NOT NULL,
    section_index INTEGER NOT NULL,
    title TEXT NOT NULL,
    topic TEXT DEFAULT '',
    core_question TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    key_terms_json TEXT NOT NULL DEFAULT '[]',
    prerequisite_concepts_json TEXT NOT NULL DEFAULT '[]',
    start_slide INTEGER NOT NULL,
    end_slide INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (deck_id) REFERENCES ppt_decks(id) ON DELETE CASCADE,
    UNIQUE(deck_id, section_index)
);

CREATE TABLE slide_explanations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 0,
    slide_id INTEGER NOT NULL,
    model TEXT NOT NULL,
    explanation TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (slide_id) REFERENCES ppt_slides(id) ON DELETE CASCADE
);

CREATE TABLE slide_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 0,
    slide_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    model TEXT NOT NULL,
    category TEXT DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT '未整理',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (slide_id) REFERENCES ppt_slides(id) ON DELETE CASCADE
);

CREATE TABLE api_providers (
    provider_key TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL DEFAULT 0,
    name TEXT NOT NULL UNIQUE,
    provider_type TEXT NOT NULL,
    base_url TEXT DEFAULT '',
    model TEXT DEFAULT '',
    api_key_env TEXT DEFAULT '',
    auth_type TEXT NOT NULL DEFAULT 'bearer',
    extra_headers_json TEXT DEFAULT '{}',
    request_template_json TEXT DEFAULT '',
    response_path TEXT DEFAULT '',
    balance_query_enabled INTEGER NOT NULL DEFAULT 0,
    balance_query_type TEXT NOT NULL DEFAULT 'auto_wallet',
    balance_query_config_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE app_settings (
    key TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL DEFAULT 0,
    value TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE daily_review_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 0,
    review_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT '已完成',
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE(user_id, review_date)
);

CREATE TABLE daily_ai_review_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 0,
    review_date TEXT NOT NULL,
    provider_key TEXT,
    model TEXT DEFAULT '',
    plan_json TEXT NOT NULL DEFAULT '{}',
    source_snapshot_json TEXT NOT NULL DEFAULT '{}',
    answers_json TEXT DEFAULT '{}',
    evaluation_json TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT '待回答',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    evaluated_at TEXT DEFAULT '',
    UNIQUE(user_id, review_date),
    FOREIGN KEY (provider_key) REFERENCES api_providers(provider_key) ON DELETE SET NULL
);

CREATE INDEX idx_study_sessions_user_date_id ON study_sessions(user_id, date DESC, id DESC);
CREATE INDEX idx_study_sessions_user_subject_date_id ON study_sessions(user_id, subject, date DESC, id DESC);
CREATE INDEX idx_mainline_anchors_user_session_order ON mainline_anchors(user_id, session_id, order_index ASC, id ASC);
CREATE INDEX idx_branch_questions_user_anchor_created ON branch_questions(user_id, anchor_id, created_at ASC, id ASC);
CREATE INDEX idx_branch_questions_user_session_anchor ON branch_questions(user_id, session_id, anchor_id);
CREATE INDEX idx_knowledge_cards_user_mastery_created ON knowledge_cards(user_id, mastery ASC, created_at DESC, id DESC);
CREATE INDEX idx_knowledge_cards_user_subject_created ON knowledge_cards(user_id, subject, created_at DESC, id DESC);
CREATE INDEX idx_knowledge_cards_user_source_session ON knowledge_cards(user_id, source_session_id);
CREATE INDEX idx_knowledge_links_user_source_created ON knowledge_links(user_id, source_knowledge_id, created_at DESC, id DESC);
CREATE INDEX idx_knowledge_links_user_target_created ON knowledge_links(user_id, target_knowledge_id, created_at DESC, id DESC);
CREATE INDEX idx_mistakes_user_knowledge_created ON mistakes(user_id, knowledge_id, created_at DESC, id DESC);
CREATE INDEX idx_mistakes_user_subject_topic_created ON mistakes(user_id, subject, topic, created_at DESC, id DESC);
CREATE INDEX idx_mistakes_user_subject_cause ON mistakes(user_id, subject, cause_category);
CREATE INDEX idx_review_tasks_user_status_date_id ON review_tasks(user_id, status, review_date ASC, id ASC);
CREATE INDEX idx_review_tasks_user_knowledge_date ON review_tasks(user_id, knowledge_id, review_date ASC, id ASC);
CREATE INDEX idx_parking_lot_user_status_created ON parking_lot(user_id, status, created_at DESC, id DESC);
CREATE INDEX idx_ppt_decks_user_created ON ppt_decks(user_id, created_at DESC, id DESC);
CREATE INDEX idx_ppt_decks_manage ON ppt_decks(user_id, status, category, sort_order ASC, created_at DESC, id DESC);
CREATE INDEX idx_slide_explanations_user_slide_created ON slide_explanations(user_id, slide_id, created_at DESC, id DESC);
CREATE INDEX idx_slide_questions_user_slide_created ON slide_questions(user_id, slide_id, created_at DESC, id DESC);
CREATE INDEX idx_slide_questions_manage ON slide_questions(user_id, status, category, sort_order ASC, created_at DESC, id DESC);
CREATE INDEX idx_daily_ai_review_plans_user_date ON daily_ai_review_plans(user_id, review_date DESC, id DESC);
CREATE INDEX idx_api_providers_enabled_order ON api_providers(user_id, enabled, sort_order ASC, provider_key ASC);
CREATE INDEX idx_api_providers_order ON api_providers(user_id, sort_order ASC, provider_key ASC);
