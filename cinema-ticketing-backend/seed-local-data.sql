-- ============================================================
-- cinema-ticketing 联调种子数据
--
-- 目的：让下面两条链路能用真实数据跑通
--   1. 锁座 → 下单 → 支付 → 退票
--   2. 下单后不支付 → 等 5 分钟 → 超时自动取消（经 RabbitMQ 延迟队列 + 死信）
--
-- 取值约束（全部来自 OrderService 的实际判断，不是猜的）：
--   * screening.status 必须是 'SCHEDULED' —— screening() 查询带这个条件，否则抛 404
--   * seat.status 必须是 'AVAILABLE'     —— validateSeats() 带这个条件，否则抛 400
--   * 退票要求 screening.start_time > 当前时间 + refund_policy.cutoff_minutes(30)，
--     所以场次时间统一用 CURDATE() 相对偏移，任何一天重跑都还有效
--   * movie.status 在代码里没有任何地方被读取，取值纯属约定
--   * seat.seat_type 同样无人读取
--
-- 幂等：全部 INSERT ... WHERE NOT EXISTS，可重复执行，不会产生重复数据
--
-- 字符集：本文件是 UTF-8。下面的 SET NAMES 让服务端按 UTF-8 解释后续语句，
--         不依赖客户端默认字符集 —— 容器里的 mysql 客户端默认是 latin1，
--         不加这一句会把中文双重编码存坏（星 → æ˜Ÿ，3 字节变 6 字节）。
--
-- 执行：
--   mysql -h192.168.100.133 -ucinema -pcinema cinema_ticketing < seed-local-data.sql
-- ============================================================

SET NAMES utf8mb4;

-- ---------- 影院 ----------
INSERT INTO cinema (id, name, address, phone, status)
SELECT 1, '星轶影城（演示店）', '演示市演示区演示路 1 号', '010-00000001', 'ACTIVE'
WHERE NOT EXISTS (SELECT 1 FROM cinema WHERE id = 1);

-- ---------- 影厅 ----------
-- 1 号厅 8 行 × 10 列 = 80 座；2 号厅 6 行 × 8 列 = 48 座
INSERT INTO hall (id, cinema_id, name, row_count, column_count, hall_type, status)
SELECT 1, 1, '1 号厅 IMAX', 8, 10, 'IMAX', 'ACTIVE'
WHERE NOT EXISTS (SELECT 1 FROM hall WHERE id = 1);

INSERT INTO hall (id, cinema_id, name, row_count, column_count, hall_type, status)
SELECT 2, 1, '2 号厅 标准', 6, 8, 'STANDARD', 'ACTIVE'
WHERE NOT EXISTS (SELECT 1 FROM hall WHERE id = 2);

-- ---------- 座位（按 row_count × column_count 生成）----------
-- 座位号形如 1-01 / 1-02 ... 8-10，与 hall.row_count / column_count 保持一致
INSERT INTO seat (hall_id, row_no, column_no, seat_code, seat_type, status)
WITH RECURSIVE rows_n(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM rows_n WHERE n < 8),
               cols_n(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM cols_n WHERE n < 10)
SELECT 1, rows_n.n, cols_n.n, CONCAT(rows_n.n, '-', LPAD(cols_n.n, 2, '0')), 'STANDARD', 'AVAILABLE'
FROM rows_n CROSS JOIN cols_n
WHERE NOT EXISTS (SELECT 1 FROM seat WHERE hall_id = 1);

INSERT INTO seat (hall_id, row_no, column_no, seat_code, seat_type, status)
WITH RECURSIVE rows_n(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM rows_n WHERE n < 6),
               cols_n(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM cols_n WHERE n < 8)
SELECT 2, rows_n.n, cols_n.n, CONCAT(rows_n.n, '-', LPAD(cols_n.n, 2, '0')), 'STANDARD', 'AVAILABLE'
FROM rows_n CROSS JOIN cols_n
WHERE NOT EXISTS (SELECT 1 FROM seat WHERE hall_id = 2);

-- ---------- 影片 ----------
INSERT INTO movie (id, title, description, duration, release_date, director, actors, genre, status)
SELECT 1, '流浪地球 3', '太阳危机之后，人类带着地球寻找新家园的第三段旅程。', 128,
       '2026-02-10', '郭帆', '吴京,刘德华,李雪健', '科幻/冒险', 'ON_SHELF'
WHERE NOT EXISTS (SELECT 1 FROM movie WHERE id = 1);

INSERT INTO movie (id, title, description, duration, release_date, director, actors, genre, status)
SELECT 2, '深海回响', '一名声呐工程师在深海听到不该存在的声音。', 106,
       '2026-03-05', '田晓鹏', '张译,周冬雨', '悬疑/剧情', 'ON_SHELF'
WHERE NOT EXISTS (SELECT 1 FROM movie WHERE id = 2);

INSERT INTO movie (id, title, description, duration, release_date, director, actors, genre, status)
SELECT 3, '长安夜行', '长安城一夜之间发生的十二件事。', 95,
       '2026-04-18', '陈凯歌', '易烊千玺,张子枫', '古装/剧情', 'ON_SHELF'
WHERE NOT EXISTS (SELECT 1 FROM movie WHERE id = 3);

-- ---------- 场次 ----------
-- end_time = start_time + 影片时长；改影片时长时记得同步这里
-- 全部安排在 2~3 天后，远离 30 分钟退票截止线
INSERT INTO screening (id, movie_id, hall_id, start_time, end_time, price, status)
SELECT 1, 1, 1,
       TIMESTAMP(DATE_ADD(CURDATE(), INTERVAL 2 DAY), '19:30:00'),
       TIMESTAMP(DATE_ADD(CURDATE(), INTERVAL 2 DAY), '21:38:00'),
       59.00, 'SCHEDULED'
WHERE NOT EXISTS (SELECT 1 FROM screening WHERE id = 1);

INSERT INTO screening (id, movie_id, hall_id, start_time, end_time, price, status)
SELECT 2, 2, 1,
       TIMESTAMP(DATE_ADD(CURDATE(), INTERVAL 2 DAY), '22:00:00'),
       TIMESTAMP(DATE_ADD(CURDATE(), INTERVAL 2 DAY), '23:46:00'),
       45.00, 'SCHEDULED'
WHERE NOT EXISTS (SELECT 1 FROM screening WHERE id = 2);

INSERT INTO screening (id, movie_id, hall_id, start_time, end_time, price, status)
SELECT 3, 3, 2,
       TIMESTAMP(DATE_ADD(CURDATE(), INTERVAL 3 DAY), '14:00:00'),
       TIMESTAMP(DATE_ADD(CURDATE(), INTERVAL 3 DAY), '15:35:00'),
       39.00, 'SCHEDULED'
WHERE NOT EXISTS (SELECT 1 FROM screening WHERE id = 3);

INSERT INTO screening (id, movie_id, hall_id, start_time, end_time, price, status)
SELECT 4, 1, 2,
       TIMESTAMP(DATE_ADD(CURDATE(), INTERVAL 3 DAY), '20:00:00'),
       TIMESTAMP(DATE_ADD(CURDATE(), INTERVAL 3 DAY), '22:08:00'),
       39.00, 'SCHEDULED'
WHERE NOT EXISTS (SELECT 1 FROM screening WHERE id = 4);

-- ---------- 自检 ----------
-- 别名用 ASCII：某些客户端（如容器里默认 latin1 的 mysql）遇到非 ASCII 标识符会解析失败
SELECT 'cinema' AS table_name, COUNT(*) AS rows_count FROM cinema
UNION ALL SELECT 'hall', COUNT(*) FROM hall
UNION ALL SELECT 'seat', COUNT(*) FROM seat
UNION ALL SELECT 'movie', COUNT(*) FROM movie
UNION ALL SELECT 'screening', COUNT(*) FROM screening
UNION ALL SELECT 'refund_policy', COUNT(*) FROM refund_policy;
