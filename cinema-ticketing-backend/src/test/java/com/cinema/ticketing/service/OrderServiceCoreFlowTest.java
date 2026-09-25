package com.cinema.ticketing.service;

import com.cinema.ticketing.dto.CreateOrderRequest;
import com.cinema.ticketing.dto.OrderView;
import com.cinema.ticketing.mq.OrderMessagePublisher;
import com.cinema.ticketing.common.BusinessException;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.PreparedStatementCreator;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.support.KeyHolder;

import java.math.BigDecimal;
import java.sql.ResultSet;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.startsWith;
import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class OrderServiceCoreFlowTest {

    private final JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
    private final StringRedisTemplate redisTemplate = mock(StringRedisTemplate.class);
    private final OrderMessagePublisher publisher = mock(OrderMessagePublisher.class);
    private final OrderService orderService = new OrderService(jdbcTemplate, redisTemplate, publisher);

    @Test
    void lockConflictReturns409WhenLuaReturnsZero() throws Exception {
        stubScreening(1L, 7L, new BigDecimal("42.00"), LocalDateTime.now().plusHours(2));
        when(jdbcTemplate.queryForObject(startsWith("SELECT COUNT(*)"), eq(Integer.class), any(Object[].class)))
                .thenReturn(1);
        when(redisTemplate.execute(any(DefaultRedisScript.class), any(List.class), eq("owner"), anyString()))
                .thenReturn(0L);

        BusinessException exception = assertThrows(BusinessException.class,
                () -> orderService.lockSeats("owner", 1L, List.of(11L)));

        assertEquals(409, exception.getCode());
    }

    @Test
    void duplicateRequestIdReturnsExistingOrderWithoutCreatingAnother() throws Exception {
        stubLockedUser();
        when(jdbcTemplate.queryForList(startsWith("SELECT order_no"), eq(String.class), anyLong(), anyString()))
                .thenReturn(List.of("OEXISTING"));
        stubOrderSnapshot("OEXISTING", "UNPAID", LocalDateTime.now().plusHours(2));
        when(jdbcTemplate.queryForList(startsWith("SELECT oi.id"), any(Object[].class))).thenReturn(List.of());

        OrderView result = orderService.createOrder(9L, "owner",
                new CreateOrderRequest(1L, List.of(11L), "request-1"));

        assertEquals("OEXISTING", result.orderNo());
        verify(jdbcTemplate, never()).update(startsWith("INSERT INTO ticket_order"), any(Object[].class));
    }

    @Test
    void paymentUsesUnpaidStatusGuard() throws Exception {
        stubOrderSnapshot("OPAY", "UNPAID", LocalDateTime.now().plusHours(2));
        when(jdbcTemplate.queryForList(startsWith("SELECT oi.id"), any(Object[].class))).thenReturn(List.of());
        when(jdbcTemplate.update(anyString(), any(Object[].class))).thenReturn(1);
        when(redisTemplate.execute(any(DefaultRedisScript.class), any(List.class), anyString())).thenReturn(1L);

        orderService.pay(9L, "owner", "OPAY", "PAY-1");

        ArgumentCaptor<String> sqlCaptor = ArgumentCaptor.forClass(String.class);
        verify(jdbcTemplate, org.mockito.Mockito.atLeastOnce()).update(sqlCaptor.capture(), any(Object[].class));
        assertEquals(true, sqlCaptor.getAllValues().stream()
                .anyMatch(sql -> sql.contains("status = 'UNPAID'")));
    }

    @Test
    void refundRejectsOrderInsideConfiguredCutoff() throws Exception {
        stubOrderSnapshot("OREFUND", "ISSUED", LocalDateTime.now().plusMinutes(10));
        when(jdbcTemplate.queryForMap(startsWith("SELECT cutoff_minutes")))
                .thenReturn(Map.of("cutoff_minutes", 30, "content", "开场前 30 分钟截止"));

        BusinessException exception = assertThrows(BusinessException.class,
                () -> orderService.refund(9L, "OREFUND", "临时有事"));

        assertEquals(400, exception.getCode());
        verify(jdbcTemplate, never()).update(startsWith("INSERT INTO refund_record"), any(Object[].class));
    }

    @Test
    void duplicateCancelMessageIsIdempotent() {
        when(jdbcTemplate.update(startsWith("INSERT IGNORE INTO message_consume_record"), any(Object[].class)))
                .thenReturn(0);

        orderService.cancelIfUnpaid("message-1", "O1");

        verify(jdbcTemplate, never()).queryForMap(anyString(), any(Object[].class));
    }

    /** 延迟消息的 TTL 有毫秒级抖动，落在 expire_at 之前一点点是正常的，不该被当成「尚未到期」。 */
    @Test
    void cancelAcceptsMessageThatLandedJustBeforeExpiry() {
        stubCancellableOrder("OJUSTEARLY", LocalDateTime.now().plusSeconds(1));

        assertEquals(true, orderService.cancelOverdueOrder("OJUSTEARLY"));

        verify(jdbcTemplate, atLeastOnce()).update(
                startsWith("UPDATE ticket_order SET status = 'CANCELLED'"), any(Object[].class));
    }

    /** 真正提前送达的消息（重试路径）仍要拒掉，否则会把没到期的订单取消掉。 */
    @Test
    void cancelRejectsMessageThatArrivedFarTooEarly() {
        stubCancellableOrder("OTOOSOON", LocalDateTime.now().plusMinutes(1));

        assertThrows(IllegalStateException.class, () -> orderService.cancelOverdueOrder("OTOOSOON"));
        verify(jdbcTemplate, never()).update(
                startsWith("UPDATE ticket_order SET status = 'CANCELLED'"), any(Object[].class));
    }

    /**
     * 延迟必须是 ORDER_TTL 这个常量本身。曾经的写法是拿 expireAt 减第二个 now()，多读一次时钟
     * 让 TTL 比真实剩余时间短几毫秒，消息落在 expire_at 之前，每次自动取消都白烧一次重试。
     */
    @Test
    void createOrderSchedulesCancellationForTheFullOrderTtl() throws Exception {
        stubLockedUser();
        when(jdbcTemplate.queryForList(startsWith("SELECT order_no"), eq(String.class), anyLong(), anyString()))
                .thenReturn(List.of());
        stubScreening(1L, 7L, new BigDecimal("42.00"), LocalDateTime.now().plusHours(2));
        when(jdbcTemplate.queryForList(startsWith("SELECT id FROM seat"), eq(Long.class), any(Object[].class)))
                .thenReturn(List.of(11L));
        when(jdbcTemplate.queryForList(startsWith("SELECT oi.seat_id"), eq(Long.class), any(Object[].class)))
                .thenReturn(List.of());
        when(jdbcTemplate.queryForObject(startsWith("SELECT COUNT(*)"), eq(Integer.class), any(Object[].class)))
                .thenReturn(1);
        ValueOperations<String, String> valueOperations = mock(ValueOperations.class);
        when(redisTemplate.opsForValue()).thenReturn(valueOperations);
        when(valueOperations.multiGet(any(List.class))).thenReturn(List.of("owner"));
        when(jdbcTemplate.update(any(PreparedStatementCreator.class), any(KeyHolder.class))).thenAnswer(invocation -> {
            invocation.<KeyHolder>getArgument(1).getKeyList().add(Map.of("GENERATED_KEY", 20L));
            return 1;
        });
        when(jdbcTemplate.queryForList(startsWith("SELECT oi.id"), any(Object[].class))).thenReturn(List.of());
        stubOrderSnapshot("OANY", "UNPAID", LocalDateTime.now().plusHours(2));

        orderService.createOrder(9L, "owner", new CreateOrderRequest(1L, List.of(11L), "request-1"));

        verify(publisher).scheduleCancellation(anyString(), eq(Duration.ofMinutes(5)));
    }

    /** cancelOverdueOrder 只读一条 SQL：order_no → (id, screening_id, status, expire_at, lock_owner)。 */
    private void stubCancellableOrder(String orderNo, LocalDateTime expireAt) {
        when(jdbcTemplate.queryForMap(startsWith("SELECT id, screening_id"), eq(orderNo)))
                .thenReturn(Map.of("id", 20L, "screening_id", 1L, "status", "UNPAID",
                        "expire_at", expireAt, "lock_owner", "owner"));
        when(jdbcTemplate.update(startsWith("UPDATE ticket_order SET status = 'CANCELLED'"), any(Object[].class)))
                .thenReturn(1);
        when(jdbcTemplate.queryForList(startsWith("SELECT seat_id"), eq(Long.class), anyLong()))
                .thenReturn(List.of(11L));
    }

    private void stubLockedUser() {
        when(jdbcTemplate.queryForList(eq("SELECT id FROM users WHERE id = ? FOR UPDATE"), eq(Long.class), eq(9L)))
                .thenReturn(List.of(9L));
    }

    private void stubScreening(long screeningId, long hallId, BigDecimal price, LocalDateTime startTime)
            throws Exception {
        ResultSet resultSet = mock(ResultSet.class);
        when(resultSet.getLong("hall_id")).thenReturn(hallId);
        when(resultSet.getBigDecimal("price")).thenReturn(price);
        when(resultSet.getObject("start_time", LocalDateTime.class)).thenReturn(startTime);
        doAnswer(invocation -> ((RowMapper<?>) invocation.getArgument(1)).mapRow(resultSet, 0))
                .when(jdbcTemplate).queryForObject(startsWith("SELECT hall_id"), any(RowMapper.class), eq(screeningId));
    }

    private void stubOrderSnapshot(String orderNo, String status, LocalDateTime startTime) throws Exception {
        ResultSet resultSet = mock(ResultSet.class);
        when(resultSet.getLong("id")).thenReturn(20L);
        when(resultSet.getString("order_no")).thenReturn(orderNo);
        when(resultSet.getLong("user_id")).thenReturn(9L);
        when(resultSet.getLong("screening_id")).thenReturn(1L);
        when(resultSet.getBigDecimal("total_amount")).thenReturn(new BigDecimal("42.00"));
        when(resultSet.getString("status")).thenReturn(status);
        when(resultSet.getString("lock_owner")).thenReturn("owner");
        when(resultSet.getObject("expire_at", LocalDateTime.class)).thenReturn(LocalDateTime.now().plusHours(1));
        when(resultSet.getObject("paid_at", LocalDateTime.class)).thenReturn(null);
        when(resultSet.getObject("start_time", LocalDateTime.class)).thenReturn(startTime);
        when(jdbcTemplate.queryForList(startsWith("SELECT seat_id"), eq(Long.class), anyLong()))
                .thenReturn(List.of(11L));
        doAnswer(invocation -> ((RowMapper<?>) invocation.getArgument(1)).mapRow(resultSet, 0))
                .when(jdbcTemplate).queryForObject(startsWith("SELECT o.id"), any(RowMapper.class), anyString(), anyLong());
    }
}
