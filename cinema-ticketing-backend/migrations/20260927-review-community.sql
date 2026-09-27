-- One-time upgrade of the legacy review schema. Do not replay after the automatic initializer.
SET NAMES utf8mb4;
ALTER TABLE movie_review
    ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    ADD COLUMN revision BIGINT NOT NULL DEFAULT 1,
    ADD COLUMN moderation_note VARCHAR(1000) NOT NULL DEFAULT '',
    ADD COLUMN moderated_by BIGINT NULL,
    ADD COLUMN moderated_at DATETIME NULL;
ALTER TABLE order_item
    ADD COLUMN checked_in_at DATETIME NULL,
    ADD COLUMN checked_in_by BIGINT NULL;

CREATE TABLE IF NOT EXISTS movie_review_reply (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    review_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    content VARCHAR(1000) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    revision BIGINT NOT NULL DEFAULT 1,
    moderation_note VARCHAR(1000) NOT NULL DEFAULT '',
    moderated_by BIGINT,
    moderated_at DATETIME,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    INDEX idx_review_reply_time (review_id, created_at),
    INDEX idx_review_reply_status (status, updated_at),
    CONSTRAINT fk_reply_review FOREIGN KEY (review_id) REFERENCES movie_review(id) ON DELETE CASCADE,
    CONSTRAINT fk_reply_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS movie_review_like (
    review_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (review_id, user_id),
    CONSTRAINT fk_review_like_review FOREIGN KEY (review_id) REFERENCES movie_review(id) ON DELETE CASCADE,
    CONSTRAINT fk_review_like_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS movie_review_report (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    review_id BIGINT NOT NULL,
    reply_id BIGINT,
    target_key VARCHAR(64) NOT NULL,
    target_revision BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    reason VARCHAR(32) NOT NULL,
    content VARCHAR(1000) NOT NULL DEFAULT '',
    reported_content VARCHAR(1000) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'OPEN',
    resolution_note VARCHAR(1000) NOT NULL DEFAULT '',
    resolved_by BIGINT,
    resolved_at DATETIME,
    created_at DATETIME NOT NULL,
    UNIQUE KEY uk_review_report_user (target_key, user_id),
    INDEX idx_review_report_status (status, created_at),
    CONSTRAINT fk_report_review FOREIGN KEY (review_id) REFERENCES movie_review(id) ON DELETE CASCADE,
    CONSTRAINT fk_report_reply FOREIGN KEY (reply_id) REFERENCES movie_review_reply(id) ON DELETE CASCADE,
    CONSTRAINT fk_report_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS movie_review_moderation (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    target_kind VARCHAR(32) NOT NULL,
    target_id BIGINT NOT NULL,
    target_revision BIGINT NOT NULL,
    from_status VARCHAR(32) NOT NULL,
    to_status VARCHAR(32) NOT NULL,
    content_snapshot VARCHAR(1000) NOT NULL,
    rating_snapshot INT,
    note VARCHAR(1000) NOT NULL,
    admin_id BIGINT NOT NULL,
    created_at DATETIME NOT NULL,
    INDEX idx_review_moderation_target (target_kind, target_id, id)
);
