# Database Schema Notes

The current database is SQLite at `INTP_Study_Manager/data/study_manager.db`. Schema creation and lightweight migrations currently live in `INTP_Study_Manager/db.py`.

## Migration Rule

Spring Boot must use versioned migration scripts. The first Java migration should be a baseline that matches the effective current Python schema.

Do not use Hibernate `ddl-auto=update` for this project.

Recommended Spring settings:

```properties
spring.jpa.hibernate.ddl-auto=validate
spring.flyway.enabled=true
```

## Tables

### users

Local users. Password hashes use `pbkdf2_sha256`.

Important fields:

- `id`
- `username`
- `display_name`
- `password_hash`
- `role`
- `is_active`
- `upload_quota_bytes`
- `created_at`
- `updated_at`

### invites

Invite-based registration.

Important fields:

- `code`
- `role`
- `created_by`
- `max_uses`
- `used_count`
- `expires_at`
- `upload_quota_bytes`
- `is_active`

### study_sessions

Study records. User-owned.

Important fields:

- `user_id`
- `date`
- `subject`
- `chapter`
- `title`
- `main_question`
- `mastered_content`
- `blockers`
- `wrong_questions`
- `summary`
- `mastery`
- `need_review`
- `is_key`

### mainline_anchors and branch_questions

Mainline anchors and branch questions. User-owned and linked to study sessions.

### knowledge_cards and knowledge_links

Knowledge cards are user-owned. Links are also user-owned and connect two cards.

Java services must verify both linked cards belong to the current user.

### mistakes

Mistake records. User-owned. May reference a knowledge card.

### review_tasks

Review schedule rows. User-owned. Created from knowledge cards using the current review intervals:

```text
1 day
3 days
7 days
14 days
```

### parking_lot

Temporary unresolved questions. User-owned.

### ppt_decks

Uploaded PPT/PDF documents. User-owned.

Important fields:

- `file_path`
- `slide_count`
- `outline`
- `outline_generated_at`
- `status`
- `category`
- `sort_order`

`file_path` currently stores a direct filesystem path. Java should introduce a storage abstraction before changing path semantics.

### ppt_slides

Slide/page rows. User-owned and linked to decks.

Important fields:

- `deck_id`
- `slide_number`
- `title`
- `slide_text`
- `notes`
- `image_path`
- `section_index`
- `page_type`
- `one_sentence_summary`
- `slide_role`
- `key_points`

There is a unique constraint on `(deck_id, slide_number)`.

### ppt_sections

Document structure sections. No `user_id`; isolation is indirect through `deck_id`.

Java services must always check deck ownership before returning or mutating sections.

### slide_explanations

Generated or manually edited explanations. User-owned and linked to `ppt_slides`.

The latest explanation is selected by `created_at DESC, id DESC`.

### slide_questions

Page questions and AI answers. User-owned and linked to `ppt_slides`.

### api_providers

AI provider configuration.

Important fields:

- `provider_key`
- `user_id`
- `name`
- `provider_type`
- `base_url`
- `model`
- `api_key_env`
- `auth_type`
- `extra_headers_json`
- `request_template_json`
- `response_path`
- `balance_query_enabled`
- `balance_query_type`
- `balance_query_config_json`
- `enabled`
- `sort_order`

Current Python service logic treats this mostly as a global table even though `user_id` exists. Before implementation, choose one target rule:

1. Global provider templates plus per-user secrets and defaults.
2. Fully user-owned providers.
3. Global defaults copied into each user account.

Recommended rule for the first Java migration: preserve current global provider behavior, but model it explicitly as a provider catalog. Keep secrets and default active provider user-scoped.

### app_settings

Generic settings.

Current behavior uses `key` as primary key and sometimes embeds user scope in `user:{id}:key`.

Recommended Java model:

- Preserve current keys during compatibility phase.
- New settings should use `user_id + setting_key` uniqueness.
- Introduce a service wrapper so raw key construction is not scattered.

### daily_review_logs

User-owned daily completion logs. Unique by `(user_id, review_date)`.

### daily_ai_review_plans

User-owned AI daily review plans. Unique by `(user_id, review_date)`.

Important JSON fields:

- `plan_json`
- `source_snapshot_json`
- `answers_json`
- `evaluation_json`

## Baseline Flyway Guidance

The first migration should:

1. Recreate the current effective schema.
2. Include indexes from `db.py`.
3. Keep SQLite-compatible column types.
4. Keep JSON fields as `TEXT`.
5. Keep booleans as `INTEGER` during compatibility phase.
6. Keep timestamp fields as `TEXT` during compatibility phase.

Potential follow-up migrations:

- Add a new `generation_jobs` table for PPT/AI background tasks.
- Add structured user settings table.
- Add provider capability fields.
- Add file storage metadata.
- Add prompt version metadata for generated AI records.

## Data Integrity Rules For Java Services

- A user may only access rows whose `user_id` matches the current user.
- A user may only access `ppt_sections` through a deck they own.
- A user may only add explanations/questions to slides in decks they own.
- A user may only link knowledge cards they own.
- Admin APIs must explicitly declare when they are operating across users.

