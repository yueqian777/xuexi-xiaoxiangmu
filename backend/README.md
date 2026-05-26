# INTP Study Backend

This is the Spring Boot backend skeleton for the Python to Java migration.

The default datasource points to `backend/study_manager_dev.db`, not the existing Python database. This keeps the first Java milestone safe while Flyway baseline work is validated.

Run locally:

```bash
mvn spring-boot:run
```

Override the database path only after making a backup:

```bash
INTP_DB_PATH=/absolute/path/to/study_manager_copy.db mvn spring-boot:run
```

Health endpoint:

```text
GET /api/health
GET /actuator/health
```
