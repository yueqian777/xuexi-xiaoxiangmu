# Phase 1 Audit And Migration Design

This document records the first migration phase from the current Python + Streamlit application to a Spring Boot + React + Tauri desktop application.

## Current Architecture

The current application is a single Streamlit project under `INTP_Study_Manager/`.

```text
INTP_Study_Manager/
  app.py
  db.py
  models.py
  pages/
  services/
  repositories/
  prompts/
  components/synced_reader/
  data/
```

`app.py` initializes the database and authentication tables, handles first-admin setup or login/register-by-invite, then routes authenticated users through a sidebar radio menu. Admin users receive one extra admin page.

`db.py` owns SQLite connection settings, schema creation, lightweight runtime migrations, and generic SQL helpers. The database file is `INTP_Study_Manager/data/study_manager.db`.

## Functional Modules

- Authentication and account isolation: users, admins, invites, upload quotas, login state.
- Study workflow: study sessions, knowledge cards, knowledge links, mistakes, parking lot, mainline anchors, branch questions, review tasks.
- Daily review: reminders, daily completion logs, AI-generated daily review plans and grading.
- AI provider management: provider templates, ordering, enable/disable, model selection, custom HTTP JSON APIs, balance query, local encrypted API key vault.
- PPT/PDF study: upload, parse, page image rendering, document structure generation, slide explanations, page questions, synced reader, study asset generation.
- Admin: invite management, user management, quota management, user deletion.

## Frontend And UI Findings

The Streamlit UI is page-based and state-heavy. Most pages combine UI and business operations in the same file.

Important pages:

- `pages/dashboard.py`: overview, due reviews, lightweight AI daily review entry points.
- `pages/study_sessions.py`: create and edit study records.
- `pages/knowledge_cards.py`: create/edit cards, relationships, related review/mistake/question context.
- `pages/reviews.py`: due reviews and review result marking.
- `pages/parking_lot.py`: unresolved questions.
- `pages/mainline_branches.py`: mainline anchors and branch questions.
- `pages/mistakes.py`: mistake records and cause statistics.
- `pages/quiz_prompts.py`: closed-book prompt generation.
- `pages/reminders.py`: local reminder configuration.
- `pages/api_settings.py`: provider CRUD, ordering, balance query, vault, provider testing.
- `pages/ppt_tutor.py`: upload, deck selection, reader, structure generation, slide explanation, batch generation, study asset generation.
- `pages/ppt_management.py`: deck/question management.
- `pages/admin_panel.py`: users, invites, quotas.

The synced reader is currently an embedded HTML/JS component. It has a top toolbar and three columns: original page, slide explanation, page questions. It supports directory/page jump, continuous/page mode, keyboard and wheel paging, fullscreen, column resizing, selection toolbar, quote-to-question, Markdown/MathJax rendering, local layout persistence, and current-slide synchronization.

React migration must preserve these interactions, but should replace Streamlit `postMessage` callbacks with REST/SSE/WebSocket APIs.

## Database Summary

The current schema contains 19 tables:

```text
users
invites
study_sessions
mainline_anchors
branch_questions
knowledge_cards
knowledge_links
mistakes
review_tasks
parking_lot
ppt_decks
ppt_slides
ppt_sections
slide_explanations
slide_questions
api_providers
app_settings
daily_review_logs
daily_ai_review_plans
```

Most business tables have `user_id`. Important exceptions and weak points:

- `ppt_sections` has no `user_id`; isolation is indirect through `deck_id`.
- `api_providers` has `user_id`, but current service code mostly treats providers as global.
- `app_settings` uses `key` as the primary key and also encodes user scope in strings like `user:{id}:default_api_config`.
- Parent-child rows do not have composite constraints that enforce matching `user_id`; current correctness relies on service code.

Spring Boot must use Flyway or Liquibase. Do not rely on Hibernate `ddl-auto` to create or update this schema.

## AI Provider Flow

The main entry point is `services.ai_service.generate_text()`.

Input surface:

- `provider_key`
- `prompt`
- optional `api_key`
- optional `model_override`
- `max_output_tokens`
- optional `image_paths`
- optional `reasoning_depth`

Provider types:

- `openai_responses`
- `openai_chat`
- `anthropic_messages`
- `gemini_generate_content`
- `minimax_chat`
- `cohere_chat`
- `custom_http_json`

Credentials can come from a temporary Streamlit session value, the per-user encrypted vault, environment variables, or special provider behavior. The balance query service is a separate but related provider feature and supports multiple provider-specific query strategies.

Spring Boot should split the current large Python service into strategy classes behind one `AiGateway`.

## PPT/PDF Flow

Upload starts at `ppt_service.import_deck()`.

1. Validate user upload quota.
2. Save file to `data/uploads`.
3. Extract text:
   - PPTX: `python-pptx`
   - PDF: `pypdf`, with PyMuPDF fallback
4. Render page images:
   - PDF: PyMuPDF
   - PPTX Windows: PowerPoint COM
   - PPTX Linux: LibreOffice, then a lower-fidelity Pillow fallback
5. Insert `ppt_decks` and `ppt_slides`.
6. Start document structure generation.
7. Generate slide explanations, page questions, reader payloads, and study assets from `pages/ppt_tutor.py`.

Migration must replace Streamlit session background threads with explicit jobs. Reader images should be served as authorized URLs instead of base64 inlined into large payloads.

## Authentication And User Isolation

The current authentication state lives in `st.session_state["current_user"]`. Passwords use PBKDF2-HMAC-SHA256. Admins are initialized at first use or bootstrapped from environment variables. Ordinary users register through invites.

Isolation is application-level: almost every query manually adds `WHERE user_id = ?`. Java must centralize this through a current-user provider and service-level authorization checks. The frontend must not decide ownership by sending `user_id`.

## Migration Risks

1. Inconsistent user isolation around `ppt_sections`, `api_providers`, and `app_settings`.
2. Very large page-level business logic, especially `pages/ppt_tutor.py`.
3. Background generation depends on in-memory Streamlit session state.
4. File paths are stored directly in SQLite.
5. PPTX rendering is platform-dependent and quality-sensitive.
6. AI provider behavior is broad and dynamic.
7. API key vault migration is security-sensitive.
8. Runtime Python schema migration must be converted into versioned migration scripts.
9. JSON text fields need DTO definitions and validation.
10. The synced reader currently depends on embedded HTML and CDN-loaded libraries.

## Target Architecture

```text
frontend/
  React + TypeScript + Vite

backend/
  Spring Boot 3 + Java 21

desktop/
  Tauri
```

Spring Boot should own business logic, persistence, authentication, provider calls, file upload, PPT/PDF parsing, review planning, and background jobs.

React should own UI, routing, state management, reader interactions, and AI conversation UI.

Tauri should remain a desktop shell only: window control, packaging, app-data path, local backend launch/connect, and future auto-update hooks.

## Migration Phases

1. Audit and migration design.
2. Spring Boot read-only backend skeleton with SQLite and Flyway.
3. Core study workflow writes: sessions, knowledge cards, reviews, mistakes, parking lot.
4. AI provider migration: CRUD, vault, unified calls, prompts, balance queries.
5. PPT/PDF migration: upload, parse, render, jobs, structure, explanations, questions.
6. React replacement for Streamlit pages.
7. Tauri desktop shell.
8. Data migration validation and Streamlit retirement.

