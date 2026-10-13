-- 这个文件由容器的 /docker-entrypoint-initdb.d 执行。容器里 mysql 客户端没有 LANG，
-- 默认按 latin1 解释文件内容，下面 refund_policy / knowledge_document 里的中文会被
-- 双重编码存坏（购票须知 → è´­ç¥¨é¡»çŸ¥，存进去就再也改不回来）。
-- 显式声明 UTF-8，不依赖客户端默认字符集。
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(64) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    phone VARCHAR(32) UNIQUE,
    role VARCHAR(32) NOT NULL DEFAULT 'USER',
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    session_version BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS movie (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    title VARCHAR(128) NOT NULL,
    description TEXT,
    duration INT NOT NULL,
    release_date DATE,
    sale_start_time DATETIME,
    sale_end_time DATETIME,
    director VARCHAR(128),
    actors VARCHAR(512),
    genre VARCHAR(128),
    status VARCHAR(32) NOT NULL DEFAULT 'UPCOMING',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_movie_status (status),
    INDEX idx_movie_release_date (release_date)
);

CREATE TABLE IF NOT EXISTS cinema (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(128) NOT NULL,
    address VARCHAR(255) NOT NULL,
    phone VARCHAR(32),
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS hall (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    cinema_id BIGINT NOT NULL,
    name VARCHAR(64) NOT NULL,
    row_count INT NOT NULL,
    column_count INT NOT NULL,
    hall_type VARCHAR(32) NOT NULL DEFAULT 'STANDARD',
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_hall_name (cinema_id, name),
    CONSTRAINT fk_hall_cinema FOREIGN KEY (cinema_id) REFERENCES cinema(id)
);

CREATE TABLE IF NOT EXISTS seat (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    hall_id BIGINT NOT NULL,
    row_no INT NOT NULL,
    column_no INT NOT NULL,
    seat_code VARCHAR(32) NOT NULL,
    seat_type VARCHAR(32) NOT NULL DEFAULT 'STANDARD',
    status VARCHAR(32) NOT NULL DEFAULT 'AVAILABLE',
    UNIQUE KEY uk_seat_code (hall_id, seat_code),
    CONSTRAINT fk_seat_hall FOREIGN KEY (hall_id) REFERENCES hall(id)
);

CREATE TABLE IF NOT EXISTS screening (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    movie_id BIGINT NOT NULL,
    hall_id BIGINT NOT NULL,
    start_time DATETIME NOT NULL,
    end_time DATETIME NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'SCHEDULED',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_screening_movie_time (movie_id, start_time),
    INDEX idx_screening_hall_time (hall_id, start_time),
    CONSTRAINT fk_screening_movie FOREIGN KEY (movie_id) REFERENCES movie(id),
    CONSTRAINT fk_screening_hall FOREIGN KEY (hall_id) REFERENCES hall(id)
);

CREATE TABLE IF NOT EXISTS screening_capacity_snapshot (
    screening_id BIGINT PRIMARY KEY,
    sellable_seat_count INT NOT NULL,
    captured_at DATETIME NOT NULL,
    CONSTRAINT fk_capacity_screening FOREIGN KEY (screening_id) REFERENCES screening(id) ON DELETE CASCADE,
    CONSTRAINT ck_capacity_positive CHECK (sellable_seat_count > 0)
);

CREATE TABLE IF NOT EXISTS ticket_order (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    order_no VARCHAR(64) NOT NULL UNIQUE,
    user_id BIGINT NOT NULL,
    screening_id BIGINT NOT NULL,
    total_amount DECIMAL(10, 2) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'UNPAID',
    lock_owner VARCHAR(128) NOT NULL,
    expire_at DATETIME,
    paid_at DATETIME,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_order_user_created (user_id, created_at),
    INDEX idx_order_status_expire (status, expire_at),
    INDEX idx_order_screening_status (screening_id, status),
    CONSTRAINT fk_order_user FOREIGN KEY (user_id) REFERENCES users(id),
    CONSTRAINT fk_order_screening FOREIGN KEY (screening_id) REFERENCES screening(id)
);

CREATE TABLE IF NOT EXISTS order_item (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    order_id BIGINT NOT NULL,
    seat_id BIGINT NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    ticket_status VARCHAR(32) NOT NULL DEFAULT 'VALID',
    checked_in_at DATETIME,
    checked_in_by BIGINT,
    UNIQUE KEY uk_order_seat (order_id, seat_id),
    INDEX idx_order_item_seat (seat_id),
    CONSTRAINT fk_item_order FOREIGN KEY (order_id) REFERENCES ticket_order(id),
    CONSTRAINT fk_item_seat FOREIGN KEY (seat_id) REFERENCES seat(id)
);

CREATE TABLE IF NOT EXISTS payment_transaction (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    payment_no VARCHAR(128) NOT NULL UNIQUE,
    order_id BIGINT NOT NULL,
    amount DECIMAL(10, 2) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'SUCCESS',
    paid_at DATETIME,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_payment_order (order_id),
    INDEX idx_payment_report_time (status, paid_at, order_id),
    CONSTRAINT fk_payment_order FOREIGN KEY (order_id) REFERENCES ticket_order(id)
);

CREATE TABLE IF NOT EXISTS order_idempotency (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT NOT NULL,
    request_id VARCHAR(128) NOT NULL,
    order_no VARCHAR(64) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_order_request (user_id, request_id),
    UNIQUE KEY uk_order_idempotency_order (order_no),
    CONSTRAINT fk_order_idempotency_user FOREIGN KEY (user_id) REFERENCES users(id),
    CONSTRAINT fk_order_idempotency_order FOREIGN KEY (order_no) REFERENCES ticket_order(order_no)
);

CREATE TABLE IF NOT EXISTS refund_record (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    order_id BIGINT NOT NULL,
    amount DECIMAL(10, 2) NOT NULL,
    reason VARCHAR(255),
    status VARCHAR(32) NOT NULL DEFAULT 'REFUNDED',
    refunded_at DATETIME,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_refund_order_created (order_id, created_at),
    INDEX idx_refund_report_time (status, refunded_at, order_id),
    CONSTRAINT fk_refund_order FOREIGN KEY (order_id) REFERENCES ticket_order(id)
);

CREATE TABLE IF NOT EXISTS refund_policy (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    policy_version VARCHAR(32) NOT NULL UNIQUE,
    cutoff_minutes INT NOT NULL DEFAULT 0,
    content VARCHAR(1000) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO refund_policy (policy_version, cutoff_minutes, content, enabled)
SELECT '2026.01', 30, '仅支持开场前 30 分钟完成退票，已出票订单可申请退票。', TRUE
WHERE NOT EXISTS (SELECT 1 FROM refund_policy WHERE policy_version = '2026.01');

CREATE TABLE IF NOT EXISTS message_consume_record (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    message_id VARCHAR(128) NOT NULL,
    message_type VARCHAR(64) NOT NULL,
    processed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_message_consume_id (message_id),
    INDEX idx_message_processed_at (processed_at)
);

CREATE TABLE IF NOT EXISTS knowledge_document (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    document_type VARCHAR(64) NOT NULL DEFAULT 'FAQ',
    version VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PUBLISHED',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_knowledge_status_type (status, document_type),
    FULLTEXT KEY ft_knowledge_content (title, content)
);

INSERT INTO knowledge_document (title, content, document_type, version, status)
SELECT '购票须知', '用户需要先登录，锁座成功后在订单有效期内完成支付；座位锁定、支付和出票状态以订单页面为准。', 'PURCHASE', '2026.01', 'PUBLISHED'
WHERE NOT EXISTS (SELECT 1 FROM knowledge_document WHERE title = '购票须知' AND version = '2026.01');

INSERT INTO knowledge_document (title, content, document_type, version, status)
SELECT '退票规则', '仅支持已出票且距离开场超过 30 分钟的订单退票，影片开始后或进入截止时间后不可退票。', 'REFUND', '2026.01', 'PUBLISHED'
WHERE NOT EXISTS (SELECT 1 FROM knowledge_document WHERE title = '退票规则' AND version = '2026.01');

INSERT INTO knowledge_document (title, content, document_type, version, status)
SELECT '影院 FAQ', '如遇支付成功但订单状态未更新，请保留支付流水号并联系影院客服，系统会按支付流水进行幂等核验。', 'FAQ', '2026.01', 'PUBLISHED'
WHERE NOT EXISTS (SELECT 1 FROM knowledge_document WHERE title = '影院 FAQ' AND version = '2026.01');

CREATE TABLE IF NOT EXISTS movie_review (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    movie_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    rating INT NOT NULL,
    content VARCHAR(1000) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    revision BIGINT NOT NULL DEFAULT 1,
    moderation_note VARCHAR(1000) NOT NULL DEFAULT '',
    moderated_by BIGINT,
    moderated_at DATETIME,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    UNIQUE KEY uk_movie_review_user (movie_id, user_id),
    INDEX idx_movie_review_time (movie_id, updated_at),
    CONSTRAINT fk_review_movie FOREIGN KEY (movie_id) REFERENCES movie(id) ON DELETE CASCADE,
    CONSTRAINT fk_review_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT chk_review_rating CHECK (rating BETWEEN 1 AND 5)
);

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
