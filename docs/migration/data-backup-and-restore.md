# Data Backup And Restore Plan

This project stores important data in both SQLite and the filesystem. Migration must back up both.

## Current Data Locations

```text
INTP_Study_Manager/data/study_manager.db
INTP_Study_Manager/data/study_manager.db-wal
INTP_Study_Manager/data/study_manager.db-shm
INTP_Study_Manager/data/uploads/
INTP_Study_Manager/data/api_keys_user_*.enc.json
INTP_Study_Manager/data/api_keys.enc.json
```

The exact image output directories are derived from uploaded file paths by the PPT service. They must be included when backing up `data/`.

## Backup Before Any Migration

Use a timestamped backup directory outside the app data directory:

```bash
mkdir -p backups
timestamp="$(date +%Y%m%d_%H%M%S)"
cp -a INTP_Study_Manager/data "backups/data_$timestamp"
```

If the Streamlit app is running, stop it first or use the SQLite online backup API. SQLite WAL mode means `study_manager.db`, `study_manager.db-wal`, and `study_manager.db-shm` may all matter.

## Verification Checklist

After backup:

```bash
sqlite3 backups/data_$timestamp/study_manager.db "PRAGMA integrity_check;"
sqlite3 backups/data_$timestamp/study_manager.db ".tables"
```

Check that uploads and vault files exist:

```bash
find backups/data_$timestamp -maxdepth 3 -type f | sort | head
```

## Restore Procedure

1. Stop the application.
2. Move the current `INTP_Study_Manager/data` aside.
3. Copy the backup back:

```bash
mv INTP_Study_Manager/data "INTP_Study_Manager/data_broken_$(date +%Y%m%d_%H%M%S)"
cp -a backups/data_YYYYMMDD_HHMMSS INTP_Study_Manager/data
```

4. Start the app and verify login, PPT list, API provider list, and knowledge cards.

## Java Migration Safety Rules

- The Java backend must not modify the existing Python database until its Flyway baseline has been validated on a copy.
- The first Spring Boot milestone should be read-only against a copied DB.
- Write migrations must be tested on copied data.
- API key vault migration must be opt-in or compatibility-preserving.
- File path migration must keep old files accessible until a verified rewrite is complete.

## Suggested Migration Test Matrix

- Fresh empty database.
- Existing database with one admin and no user data.
- Existing database with multiple users.
- Existing database with PPT/PDF uploads and page images.
- Existing database with encrypted API key vault files.
- Existing database containing legacy `user_id = 0` rows.

