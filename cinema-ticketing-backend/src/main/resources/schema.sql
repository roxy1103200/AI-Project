CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(64) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    phone VARCHAR(32) UNIQUE,
    role VARCHAR(32) NOT NULL DEFAULT 'USER',
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS movie (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    title VARCHAR(128) NOT NULL,
    description TEXT,
    duration INT NOT NULL,
    release_date DATE,
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
    UNIQUE KEY uk_order_seat (order_id, seat_id),
    INDEX idx_order_item_seat (seat_id),
    CONSTRAINT fk_item_order FOREIGN KEY (order_id) REFERENCES ticket_order(id),
    CONSTRAINT fk_item_seat FOREIGN KEY (seat_id) REFERENCES seat(id)
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
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_refund_order_created (order_id, created_at),
    CONSTRAINT fk_refund_order FOREIGN KEY (order_id) REFERENCES ticket_order(id)
);

CREATE TABLE IF NOT EXISTS message_consume_record (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    message_id VARCHAR(128) NOT NULL,
    message_type VARCHAR(64) NOT NULL,
    processed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_message_consume_id (message_id),
    INDEX idx_message_processed_at (processed_at)
);
