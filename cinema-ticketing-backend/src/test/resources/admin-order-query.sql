CREATE TABLE users(id BIGINT PRIMARY KEY, username VARCHAR(64), password_hash VARCHAR(64), phone VARCHAR(32));
CREATE TABLE cinema(id BIGINT PRIMARY KEY, name VARCHAR(64));
CREATE TABLE hall(id BIGINT PRIMARY KEY, cinema_id BIGINT, name VARCHAR(64));
CREATE TABLE movie(id BIGINT PRIMARY KEY, title VARCHAR(64), duration INT, status VARCHAR(32));
CREATE TABLE screening(id BIGINT PRIMARY KEY, movie_id BIGINT, hall_id BIGINT, start_time TIMESTAMP, status VARCHAR(32));
CREATE TABLE seat(id BIGINT PRIMARY KEY, seat_code VARCHAR(32));
CREATE TABLE ticket_order(id BIGINT PRIMARY KEY, order_no VARCHAR(64) UNIQUE, user_id BIGINT, screening_id BIGINT,
 status VARCHAR(32), total_amount DECIMAL(10,2), created_at TIMESTAMP, expire_at TIMESTAMP, paid_at TIMESTAMP);
CREATE TABLE order_item(id BIGINT PRIMARY KEY, order_id BIGINT, seat_id BIGINT, price DECIMAL(10,2),
 ticket_status VARCHAR(32), checked_in_at TIMESTAMP, checked_in_by BIGINT);
CREATE TABLE payment_order(id BIGINT PRIMARY KEY, order_id BIGINT UNIQUE, out_trade_no VARCHAR(64), status VARCHAR(32),
 channel VARCHAR(32), environment VARCHAR(32), app_id VARCHAR(64), seller_id VARCHAR(64), amount DECIMAL(10,2),
 channel_trade_no VARCHAR(64), expire_at TIMESTAMP, checkout_issued_at TIMESTAMP, close_requested_at TIMESTAMP,
 close_reason VARCHAR(32), paid_at TIMESTAMP, confirmed_at TIMESTAMP, last_query_at TIMESTAMP, next_check_at TIMESTAMP,
 last_error_code VARCHAR(64), checkout_token_hash VARCHAR(64), lease_owner VARCHAR(64));
CREATE TABLE payment_transaction(id BIGINT PRIMARY KEY, order_id BIGINT, payment_no VARCHAR(64), channel_trade_no VARCHAR(64),
 amount DECIMAL(10,2), status VARCHAR(32), channel VARCHAR(32), environment VARCHAR(32), paid_at TIMESTAMP);
CREATE TABLE refund_record(id BIGINT PRIMARY KEY, order_id BIGINT, refund_no VARCHAR(64), amount DECIMAL(10,2), reason VARCHAR(255),
 status VARCHAR(32), channel VARCHAR(32), environment VARCHAR(32), reason_type VARCHAR(32), policy_version VARCHAR(32),
 attempts INT DEFAULT 0, requested_at TIMESTAMP, refunded_at TIMESTAMP, next_check_at TIMESTAMP, last_error_code VARCHAR(64));
CREATE TABLE refund_policy(id BIGINT PRIMARY KEY, cutoff_minutes INT, enabled BOOLEAN);
INSERT INTO users VALUES(1,'customer','PASSWORD_SECRET','PHONE_SECRET'),(2,'checker','SECRET','SECRET');
INSERT INTO cinema VALUES(1,'测试影院');
INSERT INTO hall VALUES(1,1,'一号厅');
INSERT INTO movie VALUES(1,'测试影片',120,'ARCHIVED');
INSERT INTO screening VALUES(1,1,1,'2026-10-19 15:00:00','SCHEDULED');
INSERT INTO seat VALUES(1,'A1'),(2,'A2');
INSERT INTO ticket_order VALUES(1,'ORDER-A9EC9EE9',1,1,'UNPAID',79.90,'2026-10-19 02:00:00','2026-10-19 10:15:00',NULL);
INSERT INTO order_item VALUES(1,1,1,39.95,'VALID',NULL,NULL),(2,1,2,39.95,'VALID',NULL,NULL);
INSERT INTO refund_policy VALUES(1,30,TRUE);
