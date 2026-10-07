-- Existing accounts keep their data. Legacy tokens without sessionVersion fail closed.
ALTER TABLE users ADD COLUMN session_version BIGINT NOT NULL DEFAULT 0;
