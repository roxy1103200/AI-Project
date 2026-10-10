CREATE TABLE IF NOT EXISTS screening_capacity_snapshot (
    screening_id BIGINT PRIMARY KEY,
    sellable_seat_count INT NOT NULL,
    captured_at DATETIME NOT NULL,
    CONSTRAINT fk_capacity_screening FOREIGN KEY (screening_id) REFERENCES screening(id) ON DELETE CASCADE,
    CONSTRAINT ck_capacity_positive CHECK (sellable_seat_count > 0)
);
