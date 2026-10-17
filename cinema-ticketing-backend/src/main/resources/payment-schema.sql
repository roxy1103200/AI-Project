CREATE TABLE IF NOT EXISTS payment_order (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    order_id BIGINT NOT NULL UNIQUE,
    out_trade_no VARCHAR(64) NOT NULL UNIQUE,
    channel VARCHAR(16) NOT NULL DEFAULT 'ALIPAY',
    environment VARCHAR(16) NOT NULL,
    app_id VARCHAR(64) NOT NULL,
    seller_id VARCHAR(64) NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'INIT',
    channel_trade_no VARCHAR(64),
    channel_trade_status VARCHAR(32),
    expire_at DATETIME NOT NULL,
    paid_at DATETIME,
    confirmed_at DATETIME,
    checkout_token_hash VARCHAR(64) UNIQUE,
    checkout_expires_at DATETIME,
    checkout_issued_at DATETIME,
    close_requested_at DATETIME,
    close_reason VARCHAR(32),
    next_check_at DATETIME,
    last_query_at DATETIME,
    lease_owner VARCHAR(64),
    lease_until DATETIME,
    last_error_code VARCHAR(64),
    created_at DATETIME NOT NULL,
    CONSTRAINT fk_channel_payment_order FOREIGN KEY (order_id) REFERENCES ticket_order(id),
    UNIQUE KEY uk_channel_trade (channel,environment,app_id,channel_trade_no),
    INDEX idx_payment_check (next_check_at,lease_until)
);

CREATE TABLE IF NOT EXISTS payment_notify_event (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    app_id VARCHAR(64) NOT NULL,
    notify_id VARCHAR(128) NOT NULL,
    payment_order_id BIGINT NOT NULL,
    trade_status VARCHAR(32) NOT NULL,
    processed_at DATETIME NOT NULL,
    UNIQUE KEY uk_alipay_notice (app_id,notify_id),
    CONSTRAINT fk_payment_notice FOREIGN KEY (payment_order_id) REFERENCES payment_order(id)
);

CREATE TABLE IF NOT EXISTS payment_operation_log (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    action VARCHAR(32) NOT NULL,
    actor_user_id BIGINT NOT NULL,
    refund_id BIGINT NOT NULL,
    created_at DATETIME NOT NULL
);
