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

- Parking-lot conversion actions are not migrated yet: mark resolved, convert to knowledge card, convert to branch question.
- Java DELETE endpoints are currently an intentional API expansion; confirm final product permissions before exposing them in React.

Verification:

- `mvn test` passes.
- Spring Boot starts successfully with Flyway schema version 1.
- Direct HTTP probing was blocked by the tool network namespace after the server was started with elevated local-port access, so endpoint curl checks still need to be repeated from a normal terminal or future unified test harness.

Optimization candidates:

- Add integration tests with `@SpringBootTest(webEnvironment = RANDOM_PORT)` so endpoint auth and SQL behavior can be checked without manual curl.
- Introduce optional pagination/filter DTOs before the frontend consumes large study history/card/review lists.
- Decide whether `api_providers.user_id` should remain global-compatible or become per-user before write endpoints are added.
