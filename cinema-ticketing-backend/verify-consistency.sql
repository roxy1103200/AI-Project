-- ============================================================================
--  影院项目并发一致性校验
--
--  用法:
--    mysql -h127.0.0.1 -ucinema -pcinema cinema_ticketing < verify-consistency.sql
--
--  这是 OrderConcurrencyConsistencyTest 的独立旁证：Java 那边断言的是"测出来的
--  数"，这里是直接问数据库"现在到底有没有违规数据"。两边数字应当一致。
--
--  全部为只读查询，不修改任何数据。
-- ============================================================================

SELECT '=== 影院项目并发一致性校验 ===' AS `报告`;

-- ---------------------------------------------------------------------------
-- 1. 重复锁定 / 超卖
--    同一个场次的同一个座位，不允许同时出现在两笔"在途"订单里。
--    （CANCELLED / REFUNDED 是已释放的历史订单，不计入。）
-- ---------------------------------------------------------------------------
SELECT '1. 超卖：同场次同座位出现在多笔在途订单' AS `检查项`,
       COUNT(*) AS `违规笔数`,
       IF(COUNT(*) = 0, 'PASS', 'FAIL') AS `判定`
FROM (
    SELECT o.screening_id, oi.seat_id
    FROM order_item oi
    JOIN ticket_order o ON o.id = oi.order_id
    WHERE o.status IN ('UNPAID', 'PAID', 'ISSUED')
    GROUP BY o.screening_id, oi.seat_id
    HAVING COUNT(DISTINCT oi.order_id) > 1
) violations;

-- ---------------------------------------------------------------------------
-- 2. 重复订单
--    同一用户 + 同一 requestId 只允许对应一笔订单（uk_order_request 保证）。
-- ---------------------------------------------------------------------------
SELECT '2. 重复订单：同用户同 requestId 对应多笔订单' AS `检查项`,
       COUNT(*) AS `违规笔数`,
       IF(COUNT(*) = 0, 'PASS', 'FAIL') AS `判定`
FROM (
    SELECT user_id, request_id
    FROM order_idempotency
    GROUP BY user_id, request_id
    HAVING COUNT(DISTINCT order_no) > 1
) violations;

-- 幂等记录指向的订单必须真实存在，且归属同一个用户
SELECT '2b. 幂等记录与实际订单不一致' AS `检查项`,
       COUNT(*) AS `违规笔数`,
       IF(COUNT(*) = 0, 'PASS', 'FAIL') AS `判定`
FROM order_idempotency i
LEFT JOIN ticket_order o ON o.order_no = i.order_no
WHERE o.id IS NULL OR o.user_id <> i.user_id;

-- ---------------------------------------------------------------------------
-- 3. 重复支付
--    一笔订单只允许一条支付流水（uk_payment_order），
--    一个 payment_no 只允许用一次（payment_no UNIQUE）。
-- ---------------------------------------------------------------------------
SELECT '3. 重复支付：一笔订单多条支付流水' AS `检查项`,
       COUNT(*) AS `违规笔数`,
       IF(COUNT(*) = 0, 'PASS', 'FAIL') AS `判定`
FROM (
    SELECT order_id FROM payment_transaction
    GROUP BY order_id HAVING COUNT(*) > 1
) violations;

SELECT '3b. 重复支付：同 payment_no 出现多次' AS `检查项`,
       COUNT(*) AS `违规笔数`,
       IF(COUNT(*) = 0, 'PASS', 'FAIL') AS `判定`
FROM (
    SELECT payment_no FROM payment_transaction
    GROUP BY payment_no HAVING COUNT(*) > 1
) violations;

-- ---------------------------------------------------------------------------
-- 4. 订单明细重复
--    同一笔订单内不允许出现同一个座位两次（uk_order_seat）。
-- ---------------------------------------------------------------------------
SELECT '4. 订单内座位重复' AS `检查项`,
       COUNT(*) AS `违规笔数`,
       IF(COUNT(*) = 0, 'PASS', 'FAIL') AS `判定`
FROM (
    SELECT order_id, seat_id FROM order_item
    GROUP BY order_id, seat_id HAVING COUNT(*) > 1
) violations;

-- ---------------------------------------------------------------------------
-- 5. 状态机违规
--    PAID 必须有支付时间；CANCELLED 只可能来自 UNPAID（不该有支付流水）。
-- ---------------------------------------------------------------------------
SELECT '5. 状态机：PAID/ISSUED 但无支付流水' AS `检查项`,
       COUNT(*) AS `违规笔数`,
       IF(COUNT(*) = 0, 'PASS', 'FAIL') AS `判定`
FROM ticket_order o
WHERE o.status IN ('PAID', 'ISSUED')
  AND NOT EXISTS (SELECT 1 FROM payment_transaction p WHERE p.order_id = o.id);

SELECT '5b. 状态机：CANCELLED 却有支付流水' AS `检查项`,
       COUNT(*) AS `违规笔数`,
       IF(COUNT(*) = 0, 'PASS', 'FAIL') AS `判定`
FROM ticket_order o
WHERE o.status = 'CANCELLED'
  AND EXISTS (SELECT 1 FROM payment_transaction p WHERE p.order_id = o.id);

-- ---------------------------------------------------------------------------
-- 6. 规模快照 —— 用来对照压测报告里的数字
-- ---------------------------------------------------------------------------
SELECT '6. 规模' AS `检查项`, '订单总数' AS `维度`, COUNT(*) AS `数量` FROM ticket_order
UNION ALL SELECT '6. 规模', '订单明细总数', COUNT(*) FROM order_item
UNION ALL SELECT '6. 规模', '幂等记录总数', COUNT(*) FROM order_idempotency
UNION ALL SELECT '6. 规模', '支付流水总数', COUNT(*) FROM payment_transaction
UNION ALL SELECT '6. 规模', '在途座位占用数', COUNT(DISTINCT CONCAT(o.screening_id, ':', oi.seat_id))
    FROM order_item oi JOIN ticket_order o ON o.id = oi.order_id
    WHERE o.status IN ('UNPAID', 'PAID', 'ISSUED');

SELECT '=== 校验结束：以上 判定 全为 PASS 即一致性无损 ===' AS `报告`;
