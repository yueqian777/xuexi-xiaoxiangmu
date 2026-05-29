# User Identity Archive And Single User Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Archive the current user identity feature for future server deployment, then remove account management from the main app while preserving single-user local use.

**Architecture:** Keep `user_id` as a compatibility field in business tables. Replace the account system with a small `services/auth_service.py` shim that returns a local admin-like user and reuses the only existing account ID when a migrated local database has exactly one user. Store the removed multi-user implementation under `archived_features/user_identity/` and tag the commit so it can be restored later.

**Tech Stack:** Python, Streamlit, SQLite, unittest, local Git.

---

### Task 1: Archive Current User Identity Code

**Files:**
- Create: `INTP_Study_Manager/archived_features/user_identity/README.md`
- Create: `INTP_Study_Manager/archived_features/user_identity/snapshot/app.py`
- Create: `INTP_Study_Manager/archived_features/user_identity/snapshot/db.py`
- Create: `INTP_Study_Manager/archived_features/user_identity/snapshot/pages/admin_panel.py`
- Create: `INTP_Study_Manager/archived_features/user_identity/snapshot/services/auth_service.py`
- Create: `INTP_Study_Manager/archived_features/user_identity/snapshot/tests/test_concurrency_hardening.py`

- [ ] **Step 1: Copy current tracked account-related files into the archive snapshot**

Run:
```powershell
New-Item -ItemType Directory -Force -Path 'INTP_Study_Manager\archived_features\user_identity\snapshot\pages','INTP_Study_Manager\archived_features\user_identity\snapshot\services','INTP_Study_Manager\archived_features\user_identity\snapshot\tests'
Copy-Item 'INTP_Study_Manager\app.py' 'INTP_Study_Manager\archived_features\user_identity\snapshot\app.py'
Copy-Item 'INTP_Study_Manager\db.py' 'INTP_Study_Manager\archived_features\user_identity\snapshot\db.py'
Copy-Item 'INTP_Study_Manager\pages\admin_panel.py' 'INTP_Study_Manager\archived_features\user_identity\snapshot\pages\admin_panel.py'
Copy-Item 'INTP_Study_Manager\services\auth_service.py' 'INTP_Study_Manager\archived_features\user_identity\snapshot\services\auth_service.py'
Copy-Item 'INTP_Study_Manager\tests\test_concurrency_hardening.py' 'INTP_Study_Manager\archived_features\user_identity\snapshot\tests\test_concurrency_hardening.py'
```
Expected: files are copied without changing runtime behavior.

- [ ] **Step 2: Add archive README**

Write `README.md` explaining that this folder is a snapshot of the removed login, invite, admin, session, user deletion, quota, and user isolation code. Include restore guidance: compare snapshot files against the current mainline, then port the account-specific sections back instead of copying blindly.

- [ ] **Step 3: Verify archive-only diff**

Run:
```powershell
git diff --stat
python -B -m unittest discover INTP_Study_Manager/tests
```
Expected: only archive files and the plan are added; existing tests still pass.

- [ ] **Step 4: Commit and tag the archive**

Run:
```powershell
git add INTP_Study_Manager/archived_features INTP_Study_Manager/docs/superpowers/plans/2026-05-29-user-identity-archive-single-user.md
git commit -m "archive user identity feature"
git tag archive-user-identity-2026-05-29
```

### Task 2: Write Single User Mode Tests

**Files:**
- Create: `INTP_Study_Manager/tests/test_single_user_mode.py`
- Modify: `INTP_Study_Manager/tests/test_concurrency_hardening.py`
- Modify: `INTP_Study_Manager/tests/test_api_settings_permissions.py`

- [ ] **Step 1: Add failing tests for the target behavior**

Create tests that assert:
- `auth_service.require_login()` returns a local admin user without any login session.
- A migrated database with exactly one `users` row returns that user's ID.
- A new initialized database does not create `users`, `invites`, or `auth_sessions`.
- `app.py` no longer imports `admin_panel` or contains first-admin/login/invite gates.

- [ ] **Step 2: Run tests and confirm RED**

Run:
```powershell
cd INTP_Study_Manager
python -B -m unittest tests.test_single_user_mode
```
Expected: failures from current login-gated implementation, especially `PermissionError` from `require_login()`.

### Task 3: Remove Mainline Account Management

**Files:**
- Modify: `INTP_Study_Manager/app.py`
- Modify: `INTP_Study_Manager/db.py`
- Modify: `INTP_Study_Manager/services/auth_service.py`
- Modify: `INTP_Study_Manager/services/ppt_service.py`
- Delete: `INTP_Study_Manager/pages/admin_panel.py`

- [ ] **Step 1: Replace `auth_service.py` with a single-user shim**

Keep `CurrentUser`, `get_current_user()`, `require_login()`, `require_admin()`, `logout()`, `format_bytes()`, and compatibility no-ops for old import names only if needed. Resolve the local user ID from the only existing `users` row when available; otherwise return ID `0` with role `admin`.

- [ ] **Step 2: Simplify `app.py` startup**

Remove first-admin setup, login/register tabs, device session browser guard, user bar, admin page registration, and account environment bootstrap. Keep the existing business page navigation and call `ensure_default_api_providers()` after `init_db()`.

- [ ] **Step 3: Stop creating account tables in `db.py`**

Remove `_ensure_auth_tables(conn)`, the `users`, `invites`, and `auth_sessions` schema setup, invite index creation, and `_migrate_default_users(conn)`. Update `ppt_sections` migration so it does not query `users` when the table is absent.

- [ ] **Step 4: Remove account-quota dependence from uploads**

Change `ppt_service._has_upload_capacity()` so missing `users` table or missing user row means unlimited local storage.

- [ ] **Step 5: Update tests that used multi-user behavior**

Keep concurrency and local path safety tests that still apply. Move obsolete invite, session-expiry, delete-user, and multi-user permission expectations out of the active test suite because they are archived with the feature.

### Task 4: Verify And Commit Single User Mainline

**Files:**
- All modified runtime and test files.

- [ ] **Step 1: Run targeted tests**

Run:
```powershell
cd INTP_Study_Manager
python -B -m unittest tests.test_single_user_mode tests.test_concurrency_hardening tests.test_api_settings_permissions
```
Expected: all targeted tests pass.

- [ ] **Step 2: Run full regression tests**

Run:
```powershell
cd INTP_Study_Manager
python -B -m unittest discover
```
Expected: full test suite passes.

- [ ] **Step 3: Run syntax and whitespace checks**

Run:
```powershell
python -B - <<'PY'
import ast
from pathlib import Path
for path in Path('INTP_Study_Manager').rglob('*.py'):
    if '__pycache__' in path.parts or 'archived_features' in path.parts:
        continue
    ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
PY
git diff --check
```
Expected: no syntax or whitespace errors.

- [ ] **Step 4: Commit**

Run:
```powershell
git add INTP_Study_Manager
git commit -m "remove account management from mainline"
```

### Self-Review

- The archive task preserves the current implementation before behavior is removed.
- The mainline keeps `require_login()` and `user_id` compatibility so business pages do not require a risky SQL rewrite.
- New tests prove the single-user default, migrated single-account compatibility, removed account tables, and removed app login gate.
- Obsolete account-management tests are archived with the feature instead of silently deleted.
