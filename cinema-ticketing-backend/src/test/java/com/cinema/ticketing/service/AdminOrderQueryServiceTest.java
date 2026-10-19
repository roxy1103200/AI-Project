package com.cinema.ticketing.service;

import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.payment.PaymentProperties;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import java.sql.Timestamp;
import java.time.*;
import java.util.List;
import org.junit.jupiter.api.*;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.aop.framework.ProxyFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.embedded.*;
import org.springframework.transaction.annotation.AnnotationTransactionAttributeSource;
import org.springframework.transaction.interceptor.TransactionInterceptor;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class AdminOrderQueryServiceTest {
    private EmbeddedDatabase database;
    private JdbcTemplate jdbc;
    private PaymentProperties properties;
    private AdminOrderQueryService service;
    private static final String ORDER_NO = "ORDER-A9EC9EE9";
    private static final Clock CLOCK = Clock.fixed(Instant.parse("2026-10-19T02:00:00Z"), ZoneId.of("Asia/Shanghai"));

    @BeforeEach void setup() {
        database = new EmbeddedDatabaseBuilder().setType(EmbeddedDatabaseType.H2)
                .setName("admin-" + java.util.UUID.randomUUID() + ";MODE=MySQL;DATABASE_TO_LOWER=TRUE")
                .addScript("admin-order-query.sql").build();
        jdbc = spy(new JdbcTemplate(database));
        properties = new PaymentProperties();
        properties.setEnabled(true);
        properties.getAlipay().setAppId("9021000169666161");
        properties.getAlipay().setSellerId("2088000000001234");
        var proxy = new ProxyFactory(new AdminOrderQueryService(jdbc, properties, CLOCK));
        proxy.setProxyTargetClass(true);
        proxy.addAdvice(new TransactionInterceptor(new DataSourceTransactionManager(database), new AnnotationTransactionAttributeSource()));
        service = (AdminOrderQueryService) proxy.getProxy();
    }

    @AfterEach void shutdown() { database.shutdown(); }

    private void payment(String state, String app) {
        jdbc.update("INSERT INTO payment_order(id,order_id,out_trade_no,status,channel,environment,app_id,seller_id,amount,checkout_token_hash,lease_owner) "
                + "VALUES(1,1,'PAY-1',?,'ALIPAY','SANDBOX',?,'2088000000001234',79.90,'TOKEN_SECRET','LEASE_SECRET')", state, app);
    }

    private void receipt() {
        jdbc.update("INSERT INTO payment_transaction VALUES(1,1,'RECEIPT-1','TRADE-1',79.90,'SUCCESS','MOCK','MOCK','2026-10-19 09:59:00')");
    }

    private void refund(long id, String status, String type, int attempts) {
        jdbc.update("INSERT INTO refund_record(id,order_id,refund_no,amount,status,channel,environment,reason_type,attempts,requested_at) "
                + "VALUES(?,1,?,79.90,?,'ALIPAY','SANDBOX',?,?,'2026-10-19 10:00:00')", id, "REFUND-" + id, status, type, attempts);
    }

    @Test void unpaidOrderIsExactReadOnlyAndDoesNotInventPayment() {
        clearInvocations(jdbc);
        var detail = service.find("  " + ORDER_NO + "  ");
        assertEquals(ORDER_NO, detail.order().orderNo());
        assertEquals("79.90", detail.order().totalAmount());
        assertEquals(2, detail.tickets().size());
        assertEquals("39.95", detail.tickets().getFirst().price());
        assertNull(detail.payment());
        assertTrue(detail.refunds().isEmpty());
        assertFalse(detail.eligibility().canCheckIn());
        assertFalse(detail.eligibility().canRefund());
        assertEquals(List.of("CREATED"), detail.events().stream().map(e -> e.type()).toList());
        for (var invocation : mockingDetails(jdbc).getInvocations()) {
            if (invocation.getArguments().length > 0 && invocation.getArguments()[0] instanceof String sql) {
                assertTrue(sql.startsWith("SELECT"), sql);
                assertFalse(sql.contains("FOR UPDATE"));
                assertFalse(sql.contains("SELECT *"));
            }
        }
        assertEquals("UNPAID", jdbc.queryForObject("SELECT status FROM ticket_order WHERE id=1", String.class));
    }

    @Test void validatesInputAndDoesNotTreatSqlOrDatabaseErrorsAsMissingOrders() {
        for (String value : new String[]{"", "  ", "x".repeat(65), "A\u0000B"}) {
            assertEquals(400, assertThrows(BusinessException.class, () -> service.find(value)).getCode());
        }
        assertEquals(404, assertThrows(BusinessException.class, () -> service.find("' OR 1=1 --")).getCode());
        jdbc.execute("DROP TABLE seat");
        assertThrows(org.springframework.dao.DataAccessException.class, () -> service.find(ORDER_NO));
    }

    @Test void closingAndConfigurationMismatchRemainPendingAndSecretsAreExcluded() throws Exception {
        payment("CLOSING", "\t 9021000169663958");
        jdbc.update("UPDATE payment_order SET close_requested_at='2026-10-19 09:59:00',last_error_code='CONFIG_MISMATCH'");
        var detail = service.find(ORDER_NO);
        assertTrue(detail.order().description().contains("尚未确认取消"));
        assertEquals("MISMATCH", detail.diagnostics().configurationMatch());
        assertEquals("****3958", detail.diagnostics().storedIdentity().appId());
        assertEquals(1, detail.diagnostics().issues().stream().filter(i -> i.code().equals("CONFIG_MISMATCH")).count());
        assertTrue(detail.events().stream().anyMatch(e -> e.type().equals("CLOSE_REQUESTED")));
        assertFalse(detail.events().stream().anyMatch(e -> e.type().equals("CANCELLED")));
        var json = JsonMapper.builder().addModule(new JavaTimeModule()).build().writeValueAsString(detail);
        for (String secret : new String[]{"9021000169663958", "9021000169666161", "2088000000001234", "PASSWORD_SECRET", "PHONE_SECRET", "TOKEN_SECRET", "LEASE_SECRET", "password_hash", "checkout_token_hash"}) assertFalse(json.contains(secret), secret);
        assertEquals("\t 9021000169663958", jdbc.queryForObject("SELECT app_id FROM payment_order", String.class));
    }

    @ParameterizedTest @ValueSource(strings={"SUCCESS","CLOSED"})
    void completedPaymentsDoNotCompareWithNewConfiguration(String status) {
        payment(status, "old-app");
        assertEquals("UNKNOWN", service.find(ORDER_NO).diagnostics().configurationMatch());
    }

    @Test void incompleteConfigurationIsUnknownAndMatchingConfigurationIsRecognized() {
        payment("PAYING", "\uFEFF\t9021000169666161 ");
        assertEquals("MATCH", service.find(ORDER_NO).diagnostics().configurationMatch());
        properties.getAlipay().setAppId("");
        assertEquals("UNKNOWN", service.find(ORDER_NO).diagnostics().configurationMatch());
    }

    @Test void legacyMockReceiptAndMultipleRefundsDoNotDuplicateTicketsOrAmounts() {
        receipt();
        jdbc.update("UPDATE ticket_order SET status='ISSUED'");
        jdbc.update("UPDATE order_item SET ticket_status='VALID'");
        refund(1,"REFUNDED","CUSTOMER",0);
        refund(2,"UNKNOWN","CUSTOMER",8);
        var detail = service.find(ORDER_NO);
        assertNull(detail.payment());
        assertEquals("MOCK", detail.receipts().getFirst().channel());
        assertEquals(2, detail.tickets().size());
        assertEquals(2, detail.refunds().size());
        assertEquals("79.90", detail.order().totalAmount());
        assertTrue(detail.diagnostics().issues().stream().anyMatch(i -> i.code().equals("REFUND_REVIEW_REQUIRED")));
    }

    @ParameterizedTest @ValueSource(strings={"PENDING","UNKNOWN"})
    void refundInProgressCannotBeUsedOrRequestedAgain(String refundState) {
        receipt(); refund(1,refundState,"CUSTOMER",1);
        jdbc.update("UPDATE ticket_order SET status='REFUNDING'");
        var detail = service.find(ORDER_NO);
        assertTrue(detail.order().description().contains("电影票暂不可使用"));
        assertFalse(detail.eligibility().canCheckIn());
        assertFalse(detail.eligibility().canRefund());
        assertFalse(detail.events().stream().anyMatch(e -> e.type().equals("REFUNDED")));
    }

    @ParameterizedTest @ValueSource(strings={"PENDING","REFUNDED"})
    void latePaymentCompensationPreservesCancelledOrderAndReceipt(String refundState) {
        receipt(); refund(1,refundState,"LATE_PAYMENT",1);
        jdbc.update("UPDATE ticket_order SET status='CANCELLED'");
        if (refundState.equals("REFUNDED")) jdbc.update("UPDATE refund_record SET refunded_at='2026-10-19 10:01:00'");
        var detail = service.find(ORDER_NO);
        assertEquals("CANCELLED", detail.order().status());
        assertEquals("SUCCESS", detail.receipts().getFirst().status());
        assertTrue(detail.order().description().contains(refundState.equals("REFUNDED") ? "补偿退款已确认" : "原路退回"));
        assertFalse(detail.eligibility().canRefund());
    }

    @Test void perTicketCheckInPreservesFirstCheckInAndBlocksRefund() {
        receipt();
        jdbc.update("UPDATE ticket_order SET status='ISSUED'");
        jdbc.update("UPDATE screening SET start_time='2026-10-19 10:10:00'");
        jdbc.update("UPDATE order_item SET ticket_status='VALID'");
        jdbc.update("UPDATE order_item SET checked_in_at='2026-10-19 09:59:00',checked_in_by=2 WHERE id=1");
        var detail = service.find(ORDER_NO);
        assertTrue(detail.eligibility().canCheckIn());
        assertFalse(detail.eligibility().canRefund());
        assertEquals("checker", detail.tickets().getFirst().checkedInByName());
        assertNull(detail.tickets().getLast().checkedInAt());
        jdbc.update("UPDATE order_item SET checked_in_at='2026-10-19 10:00:00' WHERE id=2");
        assertFalse(service.find(ORDER_NO).eligibility().canCheckIn());
    }

    @Test void missingHistoricalAssociationsDoNotHideOrderOrInventEligibility() {
        jdbc.update("UPDATE ticket_order SET status='ISSUED'");
        jdbc.update("DELETE FROM users"); jdbc.update("DELETE FROM screening"); jdbc.update("DELETE FROM seat");
        var detail = service.find(ORDER_NO);
        assertEquals(1L, detail.customer().id());
        assertNull(detail.customer().username());
        assertEquals(3, detail.dataWarnings().size());
        assertEquals(2, detail.tickets().size());
        assertFalse(detail.eligibility().canCheckIn());
        assertFalse(detail.eligibility().canRefund());
        assertTrue(detail.eligibility().refundReason().contains("资料不完整"));
    }

    @Test void unknownOrInconsistentStatesAreFlaggedWithoutRepair() {
        jdbc.update("UPDATE ticket_order SET status='FUTURE_STATUS'");
        assertTrue(service.find(ORDER_NO).diagnostics().issues().stream().anyMatch(i -> i.code().equals("UNKNOWN_ORDER_STATUS")));
        jdbc.update("UPDATE ticket_order SET status='UNPAID'"); receipt();
        assertTrue(service.find(ORDER_NO).diagnostics().issues().stream().anyMatch(i -> i.code().equals("STATE_REVIEW_REQUIRED")));
        assertEquals("UNPAID", service.find(ORDER_NO).order().status());
    }

    @Test void timesUseShanghaiAndDurationExcludesTurnaround() {
        var detail = service.find(ORDER_NO);
        assertEquals(ZoneOffset.ofHours(8), detail.serverTime().getOffset());
        assertEquals(15, detail.screening().startTime().getHour());
        assertEquals(17, detail.screening().viewingEndTime().getHour());
        var stored = jdbc.queryForObject("SELECT created_at FROM ticket_order", Timestamp.class);
        assertEquals(stored.toInstant(), detail.order().createdAt().toInstant());
        assertEquals("Asia/Shanghai", detail.timeZone());
    }

    @Test void queryUsesReadOnlyRepeatableReadAndRepeatsAnExistingRowConsistently() {
        doAnswer(invocation -> {
            assertTrue(org.springframework.transaction.support.TransactionSynchronizationManager.isCurrentTransactionReadOnly());
            assertEquals(java.sql.Connection.TRANSACTION_REPEATABLE_READ,
                    org.springframework.transaction.support.TransactionSynchronizationManager.getCurrentTransactionIsolationLevel());
            var result = invocation.callRealMethod();
            try (var connection = database.getConnection(); var statement = connection.createStatement()) {
                statement.executeUpdate("UPDATE ticket_order SET status='ISSUED' WHERE id=1");
            }
            assertEquals("UNPAID", jdbc.queryForObject("SELECT status FROM ticket_order WHERE id=1", String.class));
            return result;
        }).when(jdbc).queryForList(startsWith("SELECT o.id"), any(Object[].class));
        var detail = service.find(ORDER_NO);
        assertEquals("UNPAID", detail.order().status());
        assertEquals("ISSUED", jdbc.queryForObject("SELECT status FROM ticket_order WHERE id=1", String.class));
    }

    @Test void ordinaryRefundAndUnpaidCancellationPreserveTheirDifferentFacts() {
        jdbc.update("UPDATE ticket_order SET status='CANCELLED'");
        var cancelled = service.find(ORDER_NO);
        assertTrue(cancelled.order().description().contains("无需退款"));
        assertFalse(cancelled.eligibility().canCheckIn());
        receipt(); refund(1,"REFUNDED","CUSTOMER",1);
        jdbc.update("UPDATE ticket_order SET status='REFUNDED'");
        jdbc.update("UPDATE order_item SET ticket_status='REFUNDED'");
        jdbc.update("UPDATE refund_record SET refunded_at='2026-10-19 10:00:00'");
        var refunded = service.find(ORDER_NO);
        assertTrue(refunded.order().description().contains("电影票已失效"));
        assertTrue(refunded.tickets().stream().allMatch(t -> t.status().equals("REFUNDED")));
        assertFalse(refunded.eligibility().canCheckIn());
        assertTrue(refunded.events().stream().anyMatch(e -> e.type().equals("REFUNDED")));
    }

    @Test void refundDeadlineUsesCurrentPolicyAndRejectsAtExactBoundary() {
        receipt(); jdbc.update("UPDATE ticket_order SET status='ISSUED'");
        assertTrue(service.find(ORDER_NO).eligibility().canRefund());
        jdbc.update("UPDATE screening SET start_time='2026-10-19 10:30:00'");
        assertFalse(service.find(ORDER_NO).eligibility().canRefund());
        jdbc.update("UPDATE refund_policy SET enabled=FALSE");
        assertNull(service.find(ORDER_NO).eligibility().refundDeadline());
        assertTrue(service.find(ORDER_NO).eligibility().refundReason().contains("规则暂不可用"));
    }

    @Test void channelErrorIsOnlyReportedFromLocalRecordsAndCreatesNoAdditionalEvents() {
        payment("CLOSING", "9021000169666161");
        jdbc.update("UPDATE payment_order SET last_error_code='CHANNEL_UNAVAILABLE',last_query_at='2026-10-19 09:59:00'");
        var detail = service.find(ORDER_NO);
        assertEquals("CLOSING", detail.payment().status());
        assertTrue(detail.diagnostics().issues().stream().anyMatch(i -> i.code().equals("CHANNEL_UNAVAILABLE")));
        assertEquals(List.of("CREATED"), detail.events().stream().map(e -> e.type()).toList());
    }
}
