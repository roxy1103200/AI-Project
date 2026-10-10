-- Existing databases normally use SalesReportSchemaInitializer at application startup.
-- This is the equivalent one-time manual migration. Do not replay schema.sql seed data.
SET NAMES utf8mb4;
CREATE TABLE IF NOT EXISTS screening_capacity_snapshot (
    screening_id BIGINT PRIMARY KEY,
    sellable_seat_count INT NOT NULL,
    captured_at DATETIME NOT NULL,
    CONSTRAINT fk_capacity_screening FOREIGN KEY (screening_id) REFERENCES screening(id) ON DELETE CASCADE,
    CONSTRAINT ck_capacity_positive CHECK (sellable_seat_count > 0)
);
ALTER TABLE refund_record ADD COLUMN refunded_at DATETIME NULL;
UPDATE refund_record
SET refunded_at=TIMESTAMPADD(SECOND,UNIX_TIMESTAMP(created_at),'1970-01-01 08:00:00')
WHERE refunded_at IS NULL;
CREATE INDEX idx_payment_report_time ON payment_transaction(status,paid_at,order_id);
CREATE INDEX idx_refund_report_time ON refund_record(status,refunded_at,order_id);
