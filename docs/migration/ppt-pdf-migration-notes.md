# PPT/PDF Migration Notes

The PPT/PDF workflow is the highest-risk feature set in this migration.

## Current Responsibilities

Current Python responsibilities are split across:

- `services/ppt_service.py`
- `services/ppt_context_service.py`
- `services/ppt_generation_state.py`
- `services/ppt_reader_state.py`
- `services/study_asset_service.py`
- `repositories/ppt_repository.py`
- `pages/ppt_tutor.py`
- `pages/ppt_management.py`
- `components/synced_reader/index.html`

`pages/ppt_tutor.py` currently contains UI, prompt building, AI invocation, background execution, reader payload construction, image encoding, and user actions. Java migration should split these concerns.

## Target Services

Recommended Spring services:

- `PptImportService`: upload save, quota check, text extraction, page image rendering, deck/slide creation.
- `PptStructureService`: structure prompt, AI call, response parsing, section and slide metadata updates.
- `PptExplanationService`: single-slide explanation, manual edit, latest explanation lookup.
- `PptExplanationJobService`: batch generation, provider pool, retry, progress, stop.
- `PptQuestionService`: page questions, quote handling, AI answers.
- `ReaderStateService`: current deck/slide and persisted last position.
- `ReaderPayloadService`: reader DTO creation and authorized image URLs.
- `StudyAssetFromPptService`: batching reading content, AI JSON parsing, merging, saving study sessions/cards/reviews.
- `DocumentRenderService`: PDF/PPTX render abstraction.
- `FileStorageService`: upload files, page images, access-control-aware URLs.

## Recommended Libraries

- PPTX text extraction: Apache POI `poi-ooxml`.
- PDF text and rendering: Apache PDFBox.
- PPTX high-quality rendering: LibreOffice headless through JODConverter, or a commercial renderer such as Aspose.Slides if needed.
- JSON parsing and validation: Jackson plus Bean Validation or JSON Schema.
- Background jobs: Spring `TaskExecutor` for first milestone; later JobRunr, Quartz, Spring Batch, or a queue.

## Reader Migration

Keep the UX:

- Three columns: page image, explanation, page questions.
- Directory and page jump.
- Continuous and paged reading modes.
- Current slide synchronization.
- Keyboard and wheel paging.
- Fullscreen.
- Resizable columns.
- Selection toolbar for quote/copy/highlight.
- Collapsible question panel.
- Markdown and MathJax rendering.
- Persisted current deck, slide, mode, and layout.

Change the transport:

- Replace Streamlit `postMessage` with REST/SSE/WebSocket.
- Replace base64 image data in payloads with authorized image URLs.
- Keep reader layout state in frontend local state/localStorage, but persist the last deck/slide on the backend.

## Job Model

Add a Java-side job concept before migrating batch generation.

Suggested fields:

- `id`
- `user_id`
- `job_type`
- `deck_id`
- `status`
- `progress`
- `status_text`
- `total_count`
- `generated_count`
- `skipped_count`
- `failed_count`
- `retry_count`
- `target_slide_numbers_json`
- `completed_slide_numbers_json`
- `failed_slide_numbers_json`
- `provider_snapshot_json`
- `error_message`
- `stop_requested`
- `created_at`
- `updated_at`
- `finished_at`

## Known Risks

- PPTX rendering differs significantly by platform.
- PDF text extraction may be empty for scanned pages; OCR should be a future extension.
- SQLite plus concurrent generation needs careful transaction and connection-pool configuration.
- Current provider image capability detection is heuristic; Java should make provider/model capabilities explicit.
- Existing local files should not be moved until a file-storage migration is tested.

## 2026-05-26 Backend Read API Progress

Added another low-risk backend slice before migrating writes and AI calls:

- `GET /api/knowledge-cards`
- `GET /api/reviews/tasks`
- `GET /api/reviews/due`
- `GET /api/ai/providers`
- `GET /api/mistakes`
- `GET /api/parking-lot`
- `GET /api/knowledge-links`
- `GET /api/knowledge-cards/{cardId}/links`
- `GET /api/ppt/decks/{deckId}`
- `GET /api/ppt/decks/{deckId}/slides`
- `GET /api/ppt/decks/{deckId}/sections`
- `GET /api/reviews/daily-log`
- `GET /api/reviews/ai-plan`

Rules preserved:

- Knowledge cards and review tasks resolve the current user from the server-side HTTP session only.
- Review task queries join `knowledge_cards` and require both `review_tasks.user_id` and `knowledge_cards.user_id` to match the current user.
- API Provider listing keeps the Python-era global configuration behavior for now, but still requires login.
- Provider responses intentionally do not expose `api_key_env` or any local secret value.
- Mistake listing joins knowledge cards with both `knowledge_id` and matching `user_id`, preventing cross-user card metadata leakage when numeric ids overlap.
- Parking-lot listing is filtered by current session user only.
- Knowledge link listing joins both source and target cards with matching `user_id`, preventing cross-user relationship leakage.
- PPT section rows do not have their own `user_id`; Java authorizes them through the owning `ppt_decks.user_id`.
- PPT slide listing checks both `ppt_slides.user_id` and the owning deck's `user_id`.
- Daily review logs and daily AI review plans remain user-scoped and return stored JSON text unchanged until typed plan/evaluation DTOs are introduced.
- Study sessions now support full CRUD; create sets `user_id` from the HTTP session and update/delete require both `id` and current `user_id`.
- Knowledge cards now support full CRUD; `source_session_id` is accepted only when the referenced study session belongs to the current user.
- Parking-lot items now support full CRUD; all writes are scoped to the current session user.
- Missing single resources now return a shared 404 `ResourceNotFoundException` response instead of being treated as bad requests.
- A Python-comparison review found that mastery must stay in the Python 0-100 range; Java validation was corrected from 0-5 to 0-100.
- A shared Java `ReviewScheduleService` now mirrors Python `REVIEW_INTERVALS`: 1, 3, 7, and 14 day review tasks.
- Creating a knowledge card with `needReview=true` now ensures initial review tasks, matching Python `ensure_initial_review_tasks`.
- Creating a mistake with `addToReview=true` and a linked `knowledgeId` now ensures initial review tasks, matching Python behavior.
- Creating a study session with `createKnowledgeCard=true` now mirrors Python's "同时创建知识点卡片" flow in one transaction.
- Parking-lot create now defaults blank status to `未解决`, matching Python's database-default behavior.
- Mistake create/update can inherit `subject` and `topic` from the linked knowledge card when those fields are blank, matching Python's form behavior.

Remaining Python-parity gaps:

- Java DELETE endpoints are currently an intentional API expansion; confirm final product permissions before exposing them in React.

## 2026-05-26 Parking-Lot Python Parity

Python parking-lot actions have been migrated as backend transaction APIs:

- `POST /api/parking-lot/{id}/resolve` mirrors `UPDATE parking_lot SET status = '已解决'`.
- `POST /api/parking-lot/{id}/convert-to-knowledge-card` creates a knowledge card, optionally creates initial review tasks, then marks the parking item `已转知识点`.
- `POST /api/parking-lot/{id}/convert-to-branch-question` validates the selected mainline anchor belongs to the current user, creates a branch question, then marks the parking item `已转插问`.
- `GET /api/mainline/anchors` mirrors the Python anchor selection query used before converting a parking item to a branch question.

Rules preserved:

- All parking-lot actions read the current user from the session.
- The branch-question conversion joins `mainline_anchors` to `study_sessions` with matching `user_id`, preserving Python's cross-table user isolation.
- Multi-step conversions run inside Java transactions so React will not need to coordinate partial writes.

## 2026-05-26 Review Result Parity

Migrated Python `services.review_service.mark_review_result` into Java:

- `POST /api/reviews/tasks/{taskId}/result`
- Marks the review task `已完成` and stores the selected result.
- Updates the linked knowledge card mastery using Python-compatible deltas:
  - `完全掌握`: +15
  - `基本掌握`: +5
  - `仍然模糊`: -5
  - `完全不会`: -15
- Clamps mastery to the Python range `0..100`.
- Adds extra review tasks for weak results:
  - `仍然模糊`: `追加复习：2 天后`
  - `完全不会`: `重点突破：1 天后`
- Looks up the review task through `review_tasks.user_id` and `knowledge_cards.user_id`, preserving user isolation.

## 2026-05-26 Mainline And Branch Parity

Migrated the Python `pages.mainline_branches` core data operations:

- `GET /api/mainline/anchors`
- `GET /api/mainline/anchors/by-session/{sessionId}`
- `POST /api/mainline/anchors`
- `GET /api/mainline/anchors/branches/by-session/{sessionId}`
- `POST /api/mainline/anchors/branches`

Rules preserved:

- Anchor creation verifies the target study session belongs to the current user.
- Branch-question creation verifies the selected anchor belongs to the current user and derives `session_id` from that anchor, so the frontend cannot spoof session ownership.
- Branch lists join anchors and sessions by matching `user_id`, preserving Python's cross-table isolation pattern.
- Prompt rendering for branch questions remains unmigrated; Java currently migrates the data operations only.

## 2026-05-26 Admin Backend

Migrated core Python `pages.admin_panel` backend operations:

- `GET /api/admin/users`
- `PATCH /api/admin/users/{userId}/active`
- `PATCH /api/admin/users/{userId}/quota`
- `DELETE /api/admin/users/{userId}`
- `GET /api/admin/invites`
- `POST /api/admin/invites`
- `PATCH /api/admin/invites/{code}/active`

Rules preserved:

- Admin endpoints require a session user with `role = admin`.
- The current admin cannot disable or delete itself.
- Admin users cannot be deleted.
- Invite creation uses secure random URL-safe codes and supports role, max uses, expiry days, and upload quota.
- User deletion removes user-owned database rows in the same table family used by Python.

Intentional temporary differences:

- Java user deletion does not remove uploaded files or per-user secret vault files yet, because Java file storage and Java secret vault migration are not implemented.
- Java upload usage is currently a placeholder derived from stored `ppt_decks.file_path` text length, not actual disk file size. Replace it when `FileStorageService` owns uploaded files.

## 2026-05-26 AI Provider Write And Generate

Migrated the first Java backend slice of Python `services.ai_service`:

- `GET /api/ai/providers`
- `POST /api/ai/providers`
- `GET /api/ai/providers/{providerKey}`
- `PUT /api/ai/providers/{providerKey}`
- `DELETE /api/ai/providers/{providerKey}`
- `POST /api/ai/providers/reorder`
- `GET /api/ai/default-config`
- `PUT /api/ai/default-config`
- `POST /api/ai/generate`

Rules preserved:

- Provider list/detail DTOs do not expose `api_key_env` or plaintext API keys.
- Provider save requests may store `apiKeyEnv`, matching Python config semantics, but no plaintext key is stored in `api_providers`.
- Default provider config is stored per user using the Python-compatible `user:{user_id}:default_api_config` key.
- Frontend calls the Spring backend for generation; it does not call model providers directly.

Current implementation scope:

- Java generation currently supports OpenAI-compatible chat providers (`openai_chat`) and MiniMax chat-compatible requests (`minimax_chat`) through `OpenAiChatProviderClient`.
- API keys can be provided per request for testing or resolved from the configured environment variable.
- `openai_responses`, Anthropic, Gemini, Cohere, custom HTTP JSON, image input, balance query, and encrypted local API key vault are still pending.

## 2026-05-26 Daily AI Review Backend

Migrated the main Python `services.daily_ai_review_service` backend flow:

- `GET /api/reviews/ai-plan/today`
- `POST /api/reviews/ai-plan`
- `POST /api/reviews/ai-plan/evaluate`

Rules preserved:

- Candidate collection prioritizes due review tasks, low mastery cards, and `need_review` cards.
- Candidate selection is scoped by current session `user_id`.
- Generated plan JSON is normalized before saving.
- Answers and evaluation JSON are stored on `daily_ai_review_plans`.
- Evaluation updates knowledge-card mastery and uses Python-compatible result thresholds:
  - score >= 85: `完全掌握`
  - score >= 65: `基本掌握`
  - score >= 40: `仍然模糊`
  - otherwise: `完全不会`
- If a question came from an existing review task, Java reuses `ReviewTaskCommandService.markResult`.
- If there is no existing task, Java updates `knowledge_cards.mastery`, updates `need_review`, and creates AI extra review tasks for weak results.

Current limitations:

- Prompt text is embedded in `DailyAiReviewCommandService`; later migrate to a Java `PromptService` with markdown resources.
- The React daily review UI is not implemented yet.
- The evaluation JSON normalization is intentionally minimal compared with Python; add integration tests before relying on it for bulk workflows.

## 2026-05-26 PPT/PDF Reader Backend Parity

Migrated the first usable backend slice of Python `pages.ppt_tutor`, `repositories.ppt_repository`, and `services.ppt_reader_state`:

- `GET /api/ppt/decks/{deckId}/reader`
- `GET /api/ppt/decks/{deckId}/reader-position`
- `PUT /api/ppt/decks/{deckId}/reader-position`
- `GET /api/ppt/decks/{deckId}/slides/{slideId}`
- `GET /api/ppt/decks/{deckId}/slides/{slideId}/image`
- `GET /api/ppt/decks/{deckId}/slides/{slideId}/explanations`
- `GET /api/ppt/decks/{deckId}/slides/{slideId}/explanations/latest`
- `POST /api/ppt/decks/{deckId}/slides/{slideId}/explanations`
- `GET /api/ppt/decks/{deckId}/slides/{slideId}/questions`
- `POST /api/ppt/decks/{deckId}/slides/{slideId}/questions`

Rules preserved:

- Last reader position uses the Python-compatible `user:{user_id}:ppt_reader_last_position` `app_settings` key.
- Reader position payload keeps Python field names: `deck_id` and `slide_number`.
- Saving reader position validates the deck and optional slide belong to the current session user.
- Slide authorization always joins `ppt_slides` and `ppt_decks` with matching `user_id`.
- Latest explanation uses Python ordering: `created_at DESC, id DESC`.
- Reader payload batches latest explanations by slide with SQLite `ROW_NUMBER()`, matching Python `latest_explanations_by_slide_ids`.
- Slide questions use Python ordering: `sort_order ASC, created_at ASC, id ASC`.
- Manual explanation and question writes set `user_id` from the server session only.
- Slide images are served through an authorized backend endpoint instead of exposing local filesystem paths directly.

Current limitations:

- `GET /api/ppt/decks/{deckId}/reader` returns all slide questions; the Python Streamlit reader loaded questions only for the active image window. React can either consume all or switch later to a windowed endpoint if large decks become heavy.
- Image URLs may return 404 when existing `image_path` points to a missing local file; Java file storage/import is not migrated yet.
- AI-generated slide explanations, AI answered canvas questions, document structure generation, upload/import, render missing images, and refresh PDF text are still pending.

## 2026-05-26 Study Business Remaining Backend Slice

Migrated additional Python learning-business operations:

- `POST /api/knowledge-links`
- `DELETE /api/knowledge-links/{id}`
- `GET /api/reminders/daily-review`
- `PUT /api/reminders/daily-review`
- `POST /api/reminders/daily-review/done`
- `GET /api/dashboard/summary`

Rules preserved:

- Knowledge-link writes validate both cards belong to the current session user.
- Knowledge-link upsert mirrors Python: same `source_knowledge_id`, `target_knowledge_id`, and `relation_type` updates note/compare text and refreshes `created_at`; otherwise it inserts.
- Knowledge-link delete scopes by current `user_id`.
- Daily reminder config uses Python's `user:{user_id}:daily_review_reminder` `app_settings` key.
- Reminder time is normalized to `HH:mm`; invalid stored JSON falls back to Python's default `{enabled: true, time: "21:00"}`.
- Marking today done mirrors Python's upsert into `daily_review_logs` for the current local date.
- Dashboard summary mirrors `services.stats_service` and the Python dashboard read model: due tasks, low mastery cards, blockers, open parking questions, recent links, and reminder status.

Current limitations:

- Windows scheduled-task install/test/uninstall is intentionally not migrated into Spring. It should be handled later by Tauri or a desktop integration layer.
- Dashboard AI review controls are already partly covered by Daily AI Review endpoints, but the React dashboard UI is still pending.

## 2026-05-26 Backend Safety And Flow Fixes

Follow-up review fixes from the full Python/Java comparison and Java optimization pass:

- `api_providers` CRUD, reorder, lookup, and generate are now scoped by current session `user_id`.
- New provider rows set `user_id` from the backend session.
- Added `POST /api/ai/providers/{providerKey}/test` for backend-owned provider validation.
- Added Flyway lookup indexes for user-scoped provider access and PPT slide lookup:
  - `idx_api_providers_user_sort`
  - `idx_api_providers_user_provider`
  - `idx_ppt_slides_user_deck_number`
- `GET /api/auth/me` now returns the shared 401 `UnauthorizedException` path when no session user exists.
- PPT slide image serving now restricts resolved image files to `intp.storage.root` and only serves image media types.
- Invite registration now claims invite usage with a conditional update before user creation to avoid exceeding `max_uses` under concurrent registration.
- Daily AI review generation/evaluation no longer keeps a database transaction open while waiting for external AI calls; only the save/apply phase is wrapped in a short `TransactionTemplate` transaction.
- Unexpected backend errors are now logged server-side while still returning a concise API error to the frontend.

Remaining high-priority backend work:

- Local encrypted API key vault.
- Balance query endpoints.
- Additional AI provider clients and custom HTTP JSON.
- PPT/PDF import, rendering, document structure, and generation jobs.
- Real integration tests for multi-user isolation and migrated Python behavior.

## 2026-05-26 Backend Optimization Follow-up

Implemented additional optimization items from the Java backend review:

- `SessionCurrentUserProvider` now revalidates `users.is_active` on each request and invalidates stale sessions for disabled/deleted users.
- Admin user listing no longer performs an upload-usage query per user; it batches current placeholder usage by `ppt_decks.user_id`.
- Added `GET /api/ppt/decks/{deckId}/reader-window?activeSlideNumber=&radius=` so React can load only the current slide window instead of the full PPT reader payload.
- `reader-window` caps radius to `0..10` and falls back to the first window when an invalid active slide is requested.

Still worth optimizing later:

- Replace admin upload usage placeholder with real file sizes after Java `FileStorageService` owns uploads.
- Add pagination/cursor DTOs for study sessions, knowledge cards, mistakes, review tasks, and full PPT slide lists.
- Move PPT reader list DTOs away from returning `imagePath` and large text fields once React has dedicated detail/window endpoints wired in.
- Replace Daily AI candidate correlated subqueries with a CTE/window-function query when real data volume grows.
- Add integration tests, not only compile tests.

## 2026-05-26 Secrets, Balance, Provider, PPT Import Slice

Implemented another backend slice for the remaining large modules:

- Local encrypted API key vault:
  - `GET /api/secrets/status`
  - `POST /api/secrets/unlock`
  - `POST /api/secrets/lock`
  - `GET /api/secrets/providers`
  - `PUT /api/secrets/providers/{providerKey}`
  - `DELETE /api/secrets/providers/{providerKey}`
- AI generation now resolves API keys from request key first, then unlocked vault, then environment variable.
- Balance query endpoint:
  - `POST /api/ai/providers/{providerKey}/balance-query`
  - Implemented `deepseek_wallet`, `openrouter_wallet`, `generic_wallet` / `auto_wallet` generic path, and `custom_http_json`.
- More provider clients:
  - `openai_responses`
  - `anthropic_messages`
  - `gemini_generate_content`
  - `cohere_chat`
  - `custom_http_json`
- Provider URL guard:
  - AI and balance URLs now pass a basic SSRF guard.
  - HTTPS is allowed; HTTP is restricted to localhost proxy.
  - Private/link-local addresses are blocked unless localhost proxy.
- Balance query config save strips sensitive keys such as `api_key`, `access_token`, `authorization`, and `token`.
- PPT/PDF import skeleton:
  - `POST /api/ppt/decks`
  - Stores uploaded `.pdf` / `.pptx` under `intp.storage.root/users/{userId}/decks/{deckUuid}`.
  - Checks quota using real files under the user's storage directory.
  - Creates `ppt_decks` and `ppt_slides` rows from extracted PDF/PPTX content.
- PPT job skeleton:
  - `POST /api/ppt/decks/{deckId}/jobs`
  - `GET /api/ppt/jobs`
  - `GET /api/ppt/jobs/{jobId}`
  - `POST /api/ppt/jobs/{jobId}/stop`

Current limitations:

- Vault unlock state is in process memory keyed by user id; add TTL and session binding later.
- Java vault defaults to `${intp.storage.root}`; use `INTP_STORAGE_ROOT` if compatibility with Python's existing `data/api_keys_user_*.enc.json` is needed.
- Balance query still lacks Python's Kimi, Zhipu, MiniMax, SiliconFlow, StepFun, Novita, NewAPI/OneAPI, and OpenAI Plan adapters.
- More provider clients are text-only; image input is still pending.
- Provider URL guard is a first pass; custom HTTP should eventually have admin allowlist controls.
- PPT/PDF import now extracts PDF text, renders PDF page images, and extracts PPTX text. PPTX page image rendering, OCR, document structure generation, and AI generation workers remain pending.
- PPT job state is currently in memory. Real long-running parsing/rendering/generation needs a persistent job table before production use.

Verification:

- `mvn test` passes.
- Spring Boot starts successfully with Flyway schema version 1.
- Direct HTTP probing was blocked by the tool network namespace after the server was started with elevated local-port access, so endpoint curl checks still need to be repeated from a normal terminal or future unified test harness.

Optimization candidates:

- Add integration tests with `@SpringBootTest(webEnvironment = RANDOM_PORT)` so endpoint auth and SQL behavior can be checked without manual curl.
- Introduce optional pagination/filter DTOs before the frontend consumes large study history/card/review lists.
- Decide whether `api_providers.user_id` should remain global-compatible or become per-user before write endpoints are added.
