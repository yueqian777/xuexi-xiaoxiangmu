# API Boundaries

This document defines the initial backend API boundaries for the Spring Boot migration. All user-scoped endpoints must resolve the current user on the server and must not trust a `user_id` value from the frontend.

## Cross-Cutting Rules

- Every write to user-owned data must set `user_id` from the authenticated server-side principal.
- Every read of user-owned data must filter by the authenticated user unless the endpoint is explicitly admin-only.
- DTOs must not expose API key plaintext by default.
- React must never call external model providers directly.
- Tauri must not contain business logic.
- JSON text stored in SQLite should have typed request/response DTOs at API boundaries.

## Auth API

```text
GET  /api/auth/status
POST /api/auth/setup-admin
POST /api/auth/login
POST /api/auth/logout
POST /api/auth/register-by-invite
GET  /api/auth/me
```

DTOs:

- `SetupAdminRequest`
- `LoginRequest`
- `RegisterByInviteRequest`
- `CurrentUserResponse`

## Admin API

```text
GET    /api/admin/users
PATCH  /api/admin/users/{userId}/active
PATCH  /api/admin/users/{userId}/quota
DELETE /api/admin/users/{userId}
POST   /api/admin/invites
GET    /api/admin/invites
PATCH  /api/admin/invites/{code}/active
```

DTOs:

- `UserAdminDto`
- `CreateInviteRequest`
- `InviteDto`
- `UpdateUserQuotaRequest`

Current Java admin user deletion removes database rows only. Physical uploaded-file and secret-vault cleanup remains deferred until Java file storage and local secret vault migration are implemented.

## Study API

```text
GET    /api/study-sessions
POST   /api/study-sessions
GET    /api/study-sessions/{id}
PUT    /api/study-sessions/{id}
DELETE /api/study-sessions/{id}
```

DTOs:

- `StudySessionDto`
- `SaveStudySessionRequest`

`SaveStudySessionRequest.createKnowledgeCard` preserves the Python "同时创建知识点卡片" workflow. When true, the backend creates the related card and initial review tasks in the same transaction.

## Knowledge API

```text
GET    /api/knowledge-cards
POST   /api/knowledge-cards
GET    /api/knowledge-cards/{id}
PUT    /api/knowledge-cards/{id}
DELETE /api/knowledge-cards/{id}
GET    /api/knowledge-cards/{id}/links
GET    /api/knowledge-links
POST   /api/knowledge-links
DELETE /api/knowledge-links/{id}
```

DTOs:

- `KnowledgeCardDto`
- `SaveKnowledgeCardRequest`
- `KnowledgeLinkDto`
- `SaveKnowledgeLinkRequest`

`POST /api/knowledge-links` follows the Python knowledge-card page behavior: if a link with the same `sourceKnowledgeId`, `targetKnowledgeId`, and `relationType` already exists for the current user, the backend updates `relationNote`, `comparePoints`, and `created_at`; otherwise it inserts a new link.

## Dashboard API

```text
GET /api/dashboard/summary
```

DTOs:

- `DashboardSummaryDto`
- `DashboardCountsDto`
- `LowMasteryCardDto`
- `RecentBlockerDto`
- `OpenParkingQuestionDto`
- `RecentKnowledgeLinkDto`

The dashboard summary mirrors Python `pages.dashboard` and `services.stats_service`: due review tasks, low-mastery cards, recent blockers, open parking-lot questions, recent knowledge links, and daily reminder status. All reads are scoped to the current session user.

## Review API

```text
GET  /api/reviews/due
GET  /api/reviews/tasks
POST /api/reviews/tasks/{taskId}/result
GET  /api/reviews/daily-log
GET  /api/reviews/ai-plan
POST /api/reviews/ai-plan
POST /api/reviews/ai-plan/answers
POST /api/reviews/ai-plan/evaluate
GET  /api/reviews/ai-plan/today
```

DTOs:

- `ReviewTaskDto`
- `MarkReviewResultRequest`
- `DailyReviewLogDto`
- `DailyAiReviewPlanDto`
- `GenerateDailyAiReviewRequest`
- `EvaluateDailyAiReviewRequest`
- `SubmitDailyAiAnswersRequest`
- `DailyAiEvaluationDto`

## Daily Reminder API

```text
GET  /api/reminders/daily-review
PUT  /api/reminders/daily-review
POST /api/reminders/daily-review/done
```

DTOs:

- `DailyReminderStatusDto`
- `DailyReminderConfigDto`
- `SaveDailyReminderConfigRequest`
- `MarkDailyReviewDoneRequest`

The reminder config preserves Python's `user:{user_id}:daily_review_reminder` `app_settings` key with `enabled` and `time`. Marking today done preserves Python's `daily_review_logs` upsert semantics. Windows scheduled-task install/test/uninstall remains deferred to the desktop shell boundary; the backend stores business state only.

## Mistake And Parking APIs

```text
GET    /api/mistakes
POST   /api/mistakes
PUT    /api/mistakes/{id}
DELETE /api/mistakes/{id}

GET    /api/parking-lot
POST   /api/parking-lot
PUT    /api/parking-lot/{id}
DELETE /api/parking-lot/{id}
POST   /api/parking-lot/{id}/resolve
POST   /api/parking-lot/{id}/convert-to-knowledge-card
POST   /api/parking-lot/{id}/convert-to-branch-question
```

DTOs:

- `MistakeDto`
- `SaveMistakeRequest`
- `ParkingLotItemDto`
- `SaveParkingLotItemRequest`
- `ConvertParkingLotToKnowledgeRequest`
- `ConvertParkingLotToBranchQuestionRequest`

## Mainline API

```text
GET /api/mainline/anchors
GET /api/mainline/anchors/by-session/{sessionId}
POST /api/mainline/anchors
GET /api/mainline/anchors/branches/by-session/{sessionId}
POST /api/mainline/anchors/branches
```

DTOs:

- `MainlineAnchorDto`
- `SaveMainlineAnchorRequest`
- `BranchQuestionDto`
- `SaveBranchQuestionRequest`

## AI Provider API

```text
GET    /api/ai/providers
POST   /api/ai/providers
GET    /api/ai/providers/{providerKey}
PUT    /api/ai/providers/{providerKey}
DELETE /api/ai/providers/{providerKey}
POST   /api/ai/providers/reorder
POST   /api/ai/providers/{providerKey}/test
GET    /api/ai/default-config
PUT    /api/ai/default-config
POST   /api/ai/generate
```

DTOs:

- `ApiProviderDto`
- `SaveApiProviderRequest`
- `ReorderApiProvidersRequest`
- `ProviderTestRequest`
- `DefaultApiConfigDto`
- `GenerateTextRequest`
- `GenerateTextResponse`

Current Java generation supports `openai_chat` and `minimax_chat` first. Other provider types remain listed for compatibility but should return an explicit unsupported-provider error until their clients are migrated.

Current Provider CRUD is user-scoped: all reads/writes filter by the current session user and new provider rows set `api_providers.user_id` from the backend session.

Provider strategy interface:

```java
interface AiProviderClient {
    boolean supports(String providerType);
    AiResponse generate(AiProviderConfig provider, AiRequest request, ResolvedCredential credential);
}
```

## Secret Vault API

```text
GET    /api/secrets/status
GET    /api/secrets/providers
POST   /api/secrets/unlock
POST   /api/secrets/lock
PUT    /api/secrets/providers/{providerKey}
DELETE /api/secrets/providers/{providerKey}
```

DTOs:

- `UnlockVaultRequest`
- `VaultStatusDto`
- `ProviderSecretPublicDto`
- `UpsertProviderSecretRequest`

Rules:

- Do not return plaintext API keys in list endpoints.
- Keep master password in memory only.
- Maintain compatibility with current per-user vault files unless a migration explicitly replaces them.
- Current Java vault uses AES-GCM plus PBKDF2-HMAC-SHA256 with the Python-compatible iteration count.
- Unlock state is currently process memory by user id; add TTL/session binding before exposing widely.

## Balance API

```text
POST /api/ai/providers/{providerKey}/balance-query
```

DTOs:

- `BalanceQueryConfigDto`
- `BalanceQueryRequest`
- `BalanceResultDto`

Sensitive credentials such as API keys and access tokens must not be persisted in normal provider config.

Current Java balance query supports `deepseek_wallet`, `openrouter_wallet`, `generic_wallet`/`auto_wallet` as generic `/user/balance`, and `custom_http_json`. More Python query types remain pending.

## PPT/PDF API

```text
GET    /api/ppt/decks
POST   /api/ppt/decks
GET    /api/ppt/decks/{deckId}
PUT    /api/ppt/decks/{deckId}
DELETE /api/ppt/decks/{deckId}
GET    /api/ppt/decks/{deckId}/slides
GET    /api/ppt/slides/{slideId}/image
GET    /api/ppt/decks/{deckId}/sections
POST   /api/ppt/decks/{deckId}/structure-jobs
POST   /api/ppt/decks/{deckId}/jobs
GET    /api/ppt/jobs
GET    /api/ppt/jobs/{jobId}
POST   /api/ppt/jobs/{jobId}/stop
```

DTOs:

- `DeckDto`
- `SlideDto`
- `SectionDto`
- `UploadDeckResponse`
- `UpdateDeckRequest`
- `StartStructureJobRequest`
- `ImportDeckResponse`
- `PptJobDto`
- `StartPptJobRequest`

Current Java import stores PDF/PPTX under `intp.storage.root/users/{userId}/decks/{deckUuid}`. PDF import extracts per-page text and renders page PNGs with PDFBox; PPTX import extracts per-slide text with Apache POI. PPTX page image rendering and OCR remain pending.

## PPT Reader API

```text
GET  /api/ppt/reader/default
GET  /api/ppt/decks/{deckId}/reader
PUT  /api/ppt/reader/position
POST /api/ppt/slides/{slideId}/explanations
POST /api/ppt/slides/{slideId}/questions
```

DTOs:

- `ReaderDeckPayload`
- `ReaderSlidePayload`
- `SaveReaderPositionRequest`
- `SaveExplanationEditRequest`
- `AskSlideQuestionRequest`
- `SlideQuestionDto`
- `SlideExplanationDto`

## Job API

```text
POST /api/ppt/decks/{deckId}/explanation-jobs
GET  /api/jobs/{jobId}
POST /api/jobs/{jobId}/stop
GET  /api/jobs
```

DTOs:

- `GenerationJobDto`
- `StartSlideExplanationJobRequest`
- `JobProgressDto`
- `StopJobRequest`

Jobs should persist status, progress, target slides, generated/skipped/failed counts, retry count, active provider, and failure reason.

## Study Asset From PPT API

```text
POST /api/ppt/decks/{deckId}/study-assets/draft
POST /api/ppt/decks/{deckId}/study-assets
```

DTOs:

- `GenerateStudyAssetsRequest`
- `StudyAssetsDraftDto`
- `SaveStudyAssetsRequest`
- `SaveStudyAssetsResponse`
