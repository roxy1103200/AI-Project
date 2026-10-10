package com.cinema.ticketing.service;

import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.common.JdbcTimes;
import com.cinema.ticketing.dto.CreateOrderRequest;
import com.cinema.ticketing.dto.OrderView;
import com.cinema.ticketing.dto.SeatLockResult;
import com.cinema.ticketing.mq.OrderMessagePublisher;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.sql.PreparedStatement;
import java.sql.Statement;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@Service
public class OrderService {

    private static final Duration SEAT_LOCK_TTL = Duration.ofMinutes(5);
    private static final Duration ORDER_TTL = Duration.ofMinutes(5);
    private static final int MAX_SEATS_PER_ORDER = 6;
    /** 延迟消息允许比 expire_at 早到多久仍算「已到期」。 */
    private static final Duration CANCEL_GRACE = Duration.ofSeconds(2);
    private static final String LOCK_KEY_PREFIX = "seat:lock:";
    private static final DefaultRedisScript<Long> LOCK_SCRIPT = new DefaultRedisScript<>(
            "for i,key in ipairs(KEYS) do "
                    + "if redis.call('get', key) then return 0 end "
                    + "end "
                    + "for i,key in ipairs(KEYS) do redis.call('set', key, ARGV[1], 'PX', ARGV[2]) end "
                    + "return 1", Long.class);
    private static final DefaultRedisScript<Long> UNLOCK_SCRIPT = new DefaultRedisScript<>(
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
                    + "return redis.call('del', KEYS[1]) "
                    + "end return 0", Long.class);

    private final JdbcTemplate jdbcTemplate;
    private final StringRedisTemplate redisTemplate;
    private final OrderMessagePublisher orderMessagePublisher;

    public OrderService(JdbcTemplate jdbcTemplate, StringRedisTemplate redisTemplate,
                        OrderMessagePublisher orderMessagePublisher) {
        this.jdbcTemplate = jdbcTemplate;
        this.redisTemplate = redisTemplate;
        this.orderMessagePublisher = orderMessagePublisher;
    }

    @Transactional
    public SeatLockResult lockSeats(String owner, long screeningId, List<Long> requestedSeatIds) {
        List<Long> seatIds = distinctSeatIds(requestedSeatIds);
        Screening screening = screening(screeningId);
        lockAvailableSeats(screening.hallId(), seatIds);
        validateSeats(screeningId, screening.hallId(), seatIds);
        ScreeningCapacity.capture(jdbcTemplate, screeningId, screening.hallId());
        List<String> keys = seatIds.stream()
                .map(seatId -> lockKey(screeningId, seatId))
                .toList();
        Long locked = redisTemplate.execute(LOCK_SCRIPT, keys, owner, String.valueOf(SEAT_LOCK_TTL.toMillis()));
        if (!Long.valueOf(1L).equals(locked)) {
            throw new BusinessException(409, "部分座位已被其他用户锁定");
        }
        return new SeatLockResult(screeningId, seatIds, LocalDateTime.now().plus(SEAT_LOCK_TTL));
    }

    @Transactional
    public OrderView createOrder(long userId, String owner, CreateOrderRequest request) {
        lockUser(userId);
        String existingOrderNo = findOrderNoByRequest(userId, request.requestId());
        if (existingOrderNo != null) {
            return findOrder(userId, existingOrderNo);
        }

        List<Long> seatIds = distinctSeatIds(request.seatIds());
        Screening screening = screening(request.screeningId());
        lockAvailableSeats(screening.hallId(), seatIds);
        validateNoActiveOrder(request.screeningId(), seatIds);
        validateLockOwnership(request.screeningId(), seatIds, owner);
        ScreeningCapacity.capture(jdbcTemplate, request.screeningId(), screening.hallId());

        String orderNo = "O" + UUID.randomUUID().toString().replace("-", "").substring(0, 24).toUpperCase();
        BigDecimal totalAmount = screening.price().multiply(BigDecimal.valueOf(seatIds.size()));
        // expire_at 由应用算好显式写库，不用 DATE_ADD(CURRENT_TIMESTAMP, ...)。数据库和应用未必在同一
        // 时区（本机开发就是 JVM=UTC+8、MySQL 容器=UTC），而延迟消息的投递时刻和 cancelIfUnpaid
        // 的到期判断都基于 JVM 时钟 —— 三处必须同源，否则延迟会被算成负数、到期判断恒为假。
        //
        // 延迟直接传 ORDER_TTL，而不是拿 expireAt 减第二个 now()：多读一次时钟会让 TTL 比真实
        // 剩余时间短几毫秒，消息落在 expire_at 之前几毫秒，到期判断把它当「尚未到期」打回，
        // 每次自动取消都白烧一次重试（实测触发过一次）。
        LocalDateTime expireAt = LocalDateTime.now().plus(ORDER_TTL);
        long orderId = insertOrder(orderNo, userId, request.screeningId(), totalAmount, owner, expireAt);
        insertOrderItems(orderId, seatIds, screening.price());
        jdbcTemplate.update("INSERT INTO order_idempotency (user_id, request_id, order_no) VALUES (?, ?, ?)",
                userId, request.requestId(), orderNo);
        orderMessagePublisher.scheduleCancellation(orderNo, ORDER_TTL);
        return findOrder(userId, orderNo);
    }

    @Transactional
    public OrderView pay(long userId, String owner, String orderNo, String paymentNo) {
        OrderSnapshot order = lockOrderSnapshot(userId, orderNo);
        if ("ISSUED".equals(order.status())) {
            String existingPaymentNo = paymentNoForOrder(order.id());
            if (paymentNo.equals(existingPaymentNo)) {
                return findOrder(userId, orderNo);
            }
            throw new BusinessException(409, "订单已通过其他支付流水完成支付");
        }
        if (!"UNPAID".equals(order.status())) {
            throw new BusinessException(409, "当前订单状态不能支付: " + order.status());
        }
        if (order.expireAt() == null || !order.expireAt().isAfter(LocalDateTime.now())) {
            throw new BusinessException(409, "订单已超时，请重新选座下单");
        }
        // paid_at 同理：库生成的 CURRENT_TIMESTAMP 走的是数据库时区，返回给前端会差几个小时
        LocalDateTime paidAt = LocalDateTime.now(java.time.ZoneId.of("Asia/Shanghai"));
        try {
            jdbcTemplate.update("INSERT INTO payment_transaction (payment_no, order_id, amount, status, paid_at) "
                            + "VALUES (?, ?, ?, 'SUCCESS', ?)",
                    paymentNo, order.id(), order.totalAmount(), paidAt);
        } catch (DuplicateKeyException exception) {
            throw new BusinessException(409, "支付流水号已用于其他订单");
        }
        int updated = jdbcTemplate.update(
                "UPDATE ticket_order SET status = 'PAID', paid_at = ? WHERE id = ? AND status = 'UNPAID'",
                paidAt, order.id());
        if (updated != 1) {
            return findOrder(userId, orderNo);
        }
        jdbcTemplate.update("UPDATE order_item SET ticket_status = 'ISSUED' WHERE order_id = ?", order.id());
        jdbcTemplate.update("UPDATE ticket_order SET status = 'ISSUED' WHERE id = ? AND status = 'PAID'", order.id());
        unlockSeats(order.screeningId(), order.seatIds(), order.lockOwner());
        return findOrder(userId, orderNo);
    }

    @Transactional
    public OrderView refund(long userId, String orderNo, String reason) {
        OrderSnapshot order = lockOrderSnapshot(userId, orderNo);
        if ("REFUNDED".equals(order.status())) {
            return findOrder(userId, orderNo);
        }
        if (!"ISSUED".equals(order.status())) {
            throw new BusinessException(409, "只有已出票订单可以退票");
        }
        if (!jdbcTemplate.queryForList("SELECT id FROM order_item WHERE order_id=? AND checked_in_at IS NOT NULL LIMIT 1", order.id()).isEmpty()) {
            throw new BusinessException(409, "订单中已有电影票验票入场，不能退票");
        }
        RefundPolicy policy = refundPolicy();
        if (!order.startTime().isAfter(LocalDateTime.now().plusMinutes(policy.cutoffMinutes()))) {
            throw new BusinessException(400, "已超过退票截止时间: " + policy.content());
        }
        int updated = jdbcTemplate.update(
                "UPDATE ticket_order SET status = 'REFUNDED' WHERE id = ? AND status = 'ISSUED'", order.id());
        if (updated != 1) {
            throw new BusinessException(409, "订单状态已变化，请刷新后重试");
        }
        jdbcTemplate.update("UPDATE order_item SET ticket_status = 'REFUNDED' WHERE order_id = ?", order.id());
        jdbcTemplate.update("INSERT INTO refund_record (order_id, amount, reason, status, refunded_at) VALUES (?, ?, ?, 'REFUNDED', ?)",
                order.id(), order.totalAmount(), reason, LocalDateTime.now(java.time.ZoneId.of("Asia/Shanghai")));
        return findOrder(userId, orderNo);
    }

    private RefundPolicy refundPolicy() {
        try {
            Map<String, Object> row = jdbcTemplate.queryForMap(
                    "SELECT cutoff_minutes, content FROM refund_policy WHERE enabled = TRUE ORDER BY id DESC LIMIT 1");
            Number cutoff = (Number) row.get("cutoff_minutes");
            return new RefundPolicy(cutoff.longValue(),
                    com.cinema.ticketing.common.RefundPolicyText.render(cutoff, String.valueOf(row.get("content"))));
        } catch (org.springframework.dao.EmptyResultDataAccessException exception) {
            throw new BusinessException(503, "退票规则暂不可用，请稍后重试");
        }
    }

    public List<Map<String, Object>> seats(long screeningId) {
        Screening screening = screening(screeningId);
        List<Map<String, Object>> seats = jdbcTemplate.queryForList(
                "SELECT s.id, s.hall_id, s.row_no, s.column_no, s.seat_code, s.seat_type, s.status, "
                        + "CASE WHEN EXISTS (SELECT 1 FROM ticket_order o JOIN order_item oi ON oi.order_id = o.id "
                        + "WHERE o.screening_id = ? AND oi.seat_id = s.id AND o.status IN ('UNPAID', 'PAID', 'ISSUED')) "
                        + "THEN 'SOLD' ELSE s.status END AS booking_status "
                        + "FROM seat s WHERE s.hall_id = ? ORDER BY s.row_no, s.column_no",
                screeningId, screening.hallId());
        List<String> keys = seats.stream()
                .map(seat -> lockKey(screeningId, ((Number) seat.get("id")).longValue()))
                .toList();
        List<String> lockOwners = keys.isEmpty() ? List.of() : redisTemplate.opsForValue().multiGet(keys);
        for (int index = 0; index < seats.size(); index++) {
            Map<String, Object> seat = seats.get(index);
            if ("AVAILABLE".equals(seat.get("booking_status"))
                    && lockOwners != null && lockOwners.get(index) != null) {
                seat.put("booking_status", "LOCKED");
            }
        }
        return seats;
    }

    public OrderView findOrder(long userId, String orderNo) {
        OrderSnapshot order = findOrderSnapshot(userId, orderNo);
        List<Map<String, Object>> items = jdbcTemplate.queryForList(
                "SELECT oi.id, oi.seat_id, s.seat_code, oi.price, oi.ticket_status "
                        + "FROM order_item oi JOIN seat s ON s.id = oi.seat_id WHERE oi.order_id = ? ORDER BY oi.id",
                order.id());
        return new OrderView(order.orderNo(), order.userId(), order.screeningId(), order.totalAmount(), order.status(),
                order.expireAt(), order.paidAt(), order.startTime(), items);
    }

    public Map<String, Object> orderSeatMap(long userId, String orderNo) {
        OrderSnapshot order = findOrderSnapshot(userId, orderNo);
        Map<String, Object> result = jdbcTemplate.queryForMap(
                "SELECT m.title movieTitle,c.name cinemaName,h.name hallName,h.row_count rowCount, "
                        + "h.column_count columnCount,s.start_time startTime,h.id hallId "
                        + "FROM screening s JOIN movie m ON m.id=s.movie_id JOIN hall h ON h.id=s.hall_id "
                        + "JOIN cinema c ON c.id=h.cinema_id WHERE s.id=?", order.screeningId());
        result.put("orderNo", order.orderNo());
        result.put("status", order.status());
        result.put("totalAmount", order.totalAmount());
        // Historical tickets remain readable after the screening has started or stopped selling.
        result.put("seats", jdbcTemplate.queryForList(
                "SELECT s.id,s.row_no,s.column_no,s.seat_code,s.status, "
                        + "CASE WHEN oi.id IS NOT NULL THEN TRUE ELSE FALSE END is_order_seat,oi.ticket_status,oi.checked_in_at "
                        + "FROM seat s LEFT JOIN order_item oi ON oi.seat_id=s.id AND oi.order_id=? "
                        + "WHERE s.hall_id=? ORDER BY s.row_no,s.column_no", order.id(), result.get("hallId")));
        return result;
    }

    /**
     * MQ 消费入口：先落幂等记录，再走 {@link #cancelOverdueOrder}。
     *
     * <p>幂等记录和取消在同一个事务里 —— 取消抛异常时事务回滚，幂等记录一并撤销，
     * 重试才能重新处理（否则失败一次就再也补不上了）。
     */
    @Transactional
    public void cancelIfUnpaid(String messageId, String orderNo) {
        int inserted = jdbcTemplate.update(
                "INSERT IGNORE INTO message_consume_record (message_id, message_type) VALUES (?, 'ORDER_CANCEL')",
                messageId);
        if (inserted == 0) {
            return;
        }
        cancelOverdueOrder(orderNo);
    }

    /**
     * 取消一条到期未支付的订单：改状态、改明细、释放座位锁。
     *
     * <p>MQ 消费和定时对账共用这一条路径，所以这里不碰 message_consume_record（对账没有消息 id）。
     * 订单不存在、或已经不是 UNPAID，都当作无事发生返回 false。
     *
     * @return 真正执行了取消返回 true
     */
    @Transactional
    public boolean cancelOverdueOrder(String orderNo) {
        Map<String, Object> order;
        try {
            order = jdbcTemplate.queryForMap(
                    "SELECT id, screening_id, status, expire_at, lock_owner FROM ticket_order WHERE order_no = ? FOR UPDATE",
                    orderNo);
        } catch (org.springframework.dao.EmptyResultDataAccessException exception) {
            return false;
        }
        if (!"UNPAID".equals(order.get("status"))) {
            return false;
        }
        LocalDateTime expireAt = JdbcTimes.asLocalDateTime(order.get("expire_at"));
        // 留 CANCEL_GRACE 的余量：延迟消息的 TTL 有毫秒级抖动，可能恰好比 expire_at 早一点点落地，
        // 那是正常现象而不是错误。只有确实还差得远（重试路径上提前送达的消息）才拒绝。
        if (expireAt.isAfter(LocalDateTime.now().plus(CANCEL_GRACE))) {
            throw new IllegalStateException("订单尚未到期: " + orderNo);
        }
        int updated = jdbcTemplate.update(
                "UPDATE ticket_order SET status = 'CANCELLED' WHERE id = ? AND status = 'UNPAID'", order.get("id"));
        if (updated != 1) {
            // MQ 消费和定时对账可能同时盯上同一笔订单，被对方抢先取消时这里拿到 0 行。
            return false;
        }
        jdbcTemplate.update("UPDATE order_item SET ticket_status = 'CANCELLED' WHERE order_id = ?", order.get("id"));
        List<Long> seatIds = orderSeatIds(((Number) order.get("id")).longValue());
        unlockSeats(((Number) order.get("screening_id")).longValue(), seatIds, (String) order.get("lock_owner"));
        return true;
    }

    @Transactional
    public OrderView cancel(long userId, String orderNo) {
        OrderSnapshot order = lockOrderSnapshot(userId, orderNo);
        if ("CANCELLED".equals(order.status())) {
            return findOrder(userId, orderNo);
        }
        if (!"UNPAID".equals(order.status())) {
            throw new BusinessException(409, "只有待支付订单可以取消");
        }
        int updated = jdbcTemplate.update(
                "UPDATE ticket_order SET status = 'CANCELLED' WHERE id = ? AND status = 'UNPAID'", order.id());
        if (updated != 1) {
            throw new BusinessException(409, "订单状态已变化，请刷新后重试");
        }
        jdbcTemplate.update("UPDATE order_item SET ticket_status = 'CANCELLED' WHERE order_id = ?", order.id());
        unlockSeats(order.screeningId(), order.seatIds(), order.lockOwner());
        return findOrder(userId, orderNo);
    }

    private Screening screening(long screeningId) {
        try {
            Screening screening = jdbcTemplate.queryForObject(
                    "SELECT hall_id, price, start_time FROM screening WHERE id = ? AND status = 'SCHEDULED' "
                            + "AND movie_id IN (SELECT id FROM movie WHERE status IN ('UPCOMING', 'ON_SHELF', 'ON_SHOW') "
                            + "AND (sale_start_time IS NULL OR sale_start_time<=?) AND (sale_end_time IS NULL OR sale_end_time>?) "
                            + "AND (sale_start_time IS NULL OR screening.start_time>=sale_start_time) "
                            + "AND (sale_end_time IS NULL OR screening.end_time<=sale_end_time)) "
                            + "AND hall_id IN (SELECT h.id FROM hall h JOIN cinema c ON c.id = h.cinema_id "
                            + "WHERE h.status = 'ACTIVE' AND c.status = 'ACTIVE') FOR SHARE",
                    (rs, rowNum) -> new Screening(rs.getLong("hall_id"), rs.getBigDecimal("price"),
                            rs.getObject("start_time", LocalDateTime.class)), screeningId, LocalDateTime.now(), LocalDateTime.now());
            if (screening.startTime() == null || !screening.startTime().isAfter(LocalDateTime.now())) {
                throw new BusinessException(409, "场次已停止售票");
            }
            return screening;
        } catch (EmptyResultDataAccessException exception) {
            throw new BusinessException(404, "场次不存在或不可售");
        }
    }

    private void validateSeats(long screeningId, long hallId, List<Long> seatIds) {
        String placeholders = String.join(",", seatIds.stream().map(id -> "?").toList());
        List<Object> parameters = new ArrayList<>();
        parameters.add(hallId);
        parameters.addAll(seatIds);
        parameters.add(screeningId);
        Integer count = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM seat s WHERE s.hall_id = ? AND s.status = 'AVAILABLE' AND s.id IN (" + placeholders + ") "
                        + "AND NOT EXISTS (SELECT 1 FROM ticket_order o JOIN order_item oi ON oi.order_id = o.id "
                        + "WHERE o.screening_id = ? AND oi.seat_id = s.id AND o.status IN ('UNPAID', 'PAID', 'ISSUED'))",
                Integer.class, parameters.toArray());
        if (count == null || count != seatIds.size()) {
            throw new BusinessException(409, "座位不存在、已被占用或不属于当前场次");
        }
    }

    private void lockUser(long userId) {
        List<Long> ids = jdbcTemplate.queryForList("SELECT id FROM users WHERE id = ? FOR UPDATE", Long.class, userId);
        if (ids.isEmpty()) {
            throw new BusinessException(401, "登录状态无效，请重新登录");
        }
    }

    private void lockAvailableSeats(long hallId, List<Long> seatIds) {
        // Serialize layout changes and the first capacity snapshot using the same hall lock.
        jdbcTemplate.queryForList("SELECT id FROM hall WHERE id=? FOR UPDATE", Long.class, hallId);
        String placeholders = String.join(",", seatIds.stream().map(id -> "?").toList());
        List<Object> parameters = new ArrayList<>();
        parameters.add(hallId);
        parameters.addAll(seatIds);
        List<Long> lockedSeatIds = jdbcTemplate.queryForList(
                "SELECT id FROM seat WHERE hall_id = ? AND status = 'AVAILABLE' AND id IN (" + placeholders + ") "
                        + "ORDER BY id FOR UPDATE", Long.class, parameters.toArray());
        if (lockedSeatIds.size() != seatIds.size()) {
            throw new BusinessException(409, "座位不存在、已停用或不属于当前场次");
        }
    }

    private void validateNoActiveOrder(long screeningId, List<Long> seatIds) {
        String placeholders = String.join(",", seatIds.stream().map(id -> "?").toList());
        List<Object> parameters = new ArrayList<>();
        parameters.add(screeningId);
        parameters.addAll(seatIds);
        List<Long> occupied = jdbcTemplate.queryForList(
                "SELECT oi.seat_id FROM order_item oi JOIN ticket_order o ON o.id = oi.order_id "
                        + "WHERE o.screening_id = ? AND oi.seat_id IN (" + placeholders + ") "
                        + "AND o.status IN ('UNPAID', 'PAID', 'ISSUED') FOR UPDATE",
                Long.class, parameters.toArray());
        if (!occupied.isEmpty()) {
            throw new BusinessException(409, "所选座位已被其他订单占用，请刷新座位图");
        }
    }

    private void validateLockOwnership(long screeningId, List<Long> seatIds, String owner) {
        List<String> keys = seatIds.stream().map(seatId -> lockKey(screeningId, seatId)).toList();
        List<String> owners = redisTemplate.opsForValue().multiGet(keys);
        boolean allOwned = owners != null && owners.size() == seatIds.size()
                && owners.stream().allMatch(owner::equals);
        if (!allOwned) {
            throw new BusinessException(409, "座位锁已失效，请重新锁座");
        }
    }

    private void unlockSeats(long screeningId, List<Long> seatIds, String owner) {
        seatIds.forEach(seatId -> redisTemplate.execute(UNLOCK_SCRIPT,
                List.of(lockKey(screeningId, seatId)), owner));
    }

    private long insertOrder(String orderNo, long userId, long screeningId, BigDecimal totalAmount, String lockOwner,
                             LocalDateTime expireAt) {
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbcTemplate.update(connection -> {
            PreparedStatement statement = connection.prepareStatement(
                    "INSERT INTO ticket_order (order_no, user_id, screening_id, total_amount, status, lock_owner, expire_at) "
                            + "VALUES (?, ?, ?, ?, 'UNPAID', ?, ?)",
                    Statement.RETURN_GENERATED_KEYS);
            statement.setString(1, orderNo);
            statement.setLong(2, userId);
            statement.setLong(3, screeningId);
            statement.setBigDecimal(4, totalAmount);
            statement.setString(5, lockOwner);
            statement.setObject(6, expireAt);
            return statement;
        }, keyHolder);
        Number key = keyHolder.getKey();
        if (key == null) {
            throw new BusinessException(500, "创建订单失败");
        }
        return key.longValue();
    }

    private void insertOrderItems(long orderId, List<Long> seatIds, BigDecimal price) {
        seatIds.forEach(seatId -> jdbcTemplate.update(
                "INSERT INTO order_item (order_id, seat_id, price, ticket_status) VALUES (?, ?, ?, 'VALID')",
                orderId, seatId, price));
    }

    private OrderSnapshot findOrderSnapshot(long userId, String orderNo) {
        return loadOrderSnapshot(userId, orderNo, false);
    }

    private OrderSnapshot lockOrderSnapshot(long userId, String orderNo) {
        return loadOrderSnapshot(userId, orderNo, true);
    }

    private OrderSnapshot loadOrderSnapshot(long userId, String orderNo, boolean forUpdate) {
        try {
            return jdbcTemplate.queryForObject(
                    "SELECT o.id, o.order_no, o.user_id, o.screening_id, o.total_amount, o.status, o.lock_owner, o.expire_at, "
                            + "o.paid_at, s.start_time FROM ticket_order o JOIN screening s ON s.id = o.screening_id "
                            + "WHERE o.order_no = ? AND o.user_id = ?" + (forUpdate ? " FOR UPDATE" : ""),
                            (rs, rowNum) -> new OrderSnapshot(rs.getLong("id"), rs.getString("order_no"),
                            rs.getLong("user_id"), rs.getLong("screening_id"), rs.getBigDecimal("total_amount"),
                            rs.getString("status"), rs.getString("lock_owner"),
                            rs.getObject("expire_at", LocalDateTime.class),
                            rs.getObject("paid_at", LocalDateTime.class),
                            rs.getObject("start_time", LocalDateTime.class), orderSeatIds(rs.getLong("id"))),
                    orderNo, userId);
        } catch (EmptyResultDataAccessException exception) {
            throw new BusinessException(404, "订单不存在");
        }
    }

    private String paymentNoForOrder(long orderId) {
        List<String> paymentNos = jdbcTemplate.queryForList(
                "SELECT payment_no FROM payment_transaction WHERE order_id = ? FOR UPDATE", String.class, orderId);
        return paymentNos.isEmpty() ? null : paymentNos.getFirst();
    }

    private List<Long> orderSeatIds(long orderId) {
        return jdbcTemplate.queryForList("SELECT seat_id FROM order_item WHERE order_id = ?", Long.class, orderId);
    }

    private String findOrderNoByRequest(long userId, String requestId) {
        List<String> orderNos = jdbcTemplate.queryForList(
                "SELECT order_no FROM order_idempotency WHERE user_id = ? AND request_id = ?",
                String.class, userId, requestId);
        return orderNos.isEmpty() ? null : orderNos.getFirst();
    }

    private List<Long> distinctSeatIds(List<Long> seatIds) {
        if (seatIds == null || seatIds.isEmpty()) {
            throw new BusinessException(400, "至少选择一个座位");
        }
        List<Long> distinctIds = new ArrayList<>(new LinkedHashSet<>(seatIds));
        if (distinctIds.size() != seatIds.size()) {
            throw new BusinessException(400, "座位不能重复选择");
        }
        if (distinctIds.size() > MAX_SEATS_PER_ORDER) {
            throw new BusinessException(400, "每笔订单最多选择 " + MAX_SEATS_PER_ORDER + " 个座位");
        }
        return distinctIds;
    }

    private String lockKey(long screeningId, long seatId) {
        return LOCK_KEY_PREFIX + screeningId + ":" + seatId;
    }

    private record Screening(long hallId, BigDecimal price, LocalDateTime startTime) {
    }

    private record RefundPolicy(long cutoffMinutes, String content) {
    }

    private record OrderSnapshot(long id, String orderNo, long userId, long screeningId, BigDecimal totalAmount,
                                 String status, String lockOwner, LocalDateTime expireAt, LocalDateTime paidAt,
                                 LocalDateTime startTime, List<Long> seatIds) {
    }

}
