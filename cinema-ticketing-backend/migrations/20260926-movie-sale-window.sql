-- Existing databases: run once before deploying the updated backend.
-- Business DATETIME values use Asia/Shanghai. NULL preserves legacy availability.
SET @add_start = IF((SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'movie' AND column_name = 'sale_start_time') = 0,
    'ALTER TABLE movie ADD COLUMN sale_start_time DATETIME NULL AFTER release_date', 'SELECT 1');
PREPARE migration_stmt FROM @add_start;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;
SET @add_end = IF((SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'movie' AND column_name = 'sale_end_time') = 0,
    'ALTER TABLE movie ADD COLUMN sale_end_time DATETIME NULL AFTER sale_start_time', 'SELECT 1');
PREPARE migration_stmt FROM @add_end;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;
