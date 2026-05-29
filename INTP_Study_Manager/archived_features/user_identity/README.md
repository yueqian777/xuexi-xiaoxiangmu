# User Identity Feature Archive

This folder stores a snapshot of the account-management implementation before the mainline app was returned to local single-user mode.

Archived scope:

- Login and logout flow.
- First-admin setup.
- Invite-code registration.
- Admin user management page.
- Browser/device session renewal.
- User deletion and per-user cleanup.
- Upload quota checks backed by user accounts.
- SQLite account tables: `users`, `invites`, `auth_sessions`.
- Business-table user isolation through `user_id`.

Snapshot files:

- `snapshot/app.py`: app startup, login gate, session browser guard, and admin page registration.
- `snapshot/db.py`: account-table creation and user-scope migrations.
- `snapshot/pages/admin_panel.py`: invite and user administration UI.
- `snapshot/services/auth_service.py`: password hashing, account CRUD, sessions, invites, and deletion cleanup.
- `snapshot/tests/test_concurrency_hardening.py`: tests that covered invite/session/delete-user behavior.

Restore guidance:

1. Start from the tag that was created with this archive, or compare these snapshot files against the current mainline.
2. Port the account-specific sections back into the current files; do not blindly overwrite current business code because the mainline may have changed.
3. Re-enable the app login gate and admin page only after the database migrations and `services.auth_service` API are restored.
4. Run the full test suite and a Streamlit startup smoke test before deploying to a server.
