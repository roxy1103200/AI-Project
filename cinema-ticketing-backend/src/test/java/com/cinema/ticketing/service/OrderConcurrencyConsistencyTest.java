package com.cinema.ticketing.service;

import com.cinema.ticketing.dto.CreateOrderRequest;
import com.cinema.ticketing.dto.OrderView;
import com.cinema.ticketing.mq.OrderMessagePublisher;
import com.cinema.ticketing.common.BusinessException;
import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.MethodOrderer;
import org.junit.jupiter.api.Order;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestMethodOrder;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.io.ClassPathResource;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.EnableTransactionManagement;
import redis.embedded.RedisServer;

import javax.sql.DataSource;
import java.io.IOException;
import java.net.ServerSocket;
import java.sql.PreparedStatement;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.IntConsumer;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;

/**
 * Measures the concurrency guarantees the resume claims, against a real Redis and a real MySQL.
 *
 * <p>The existing unit tests stub the Lua result with {@code thenReturn(1L)}, so the seat-lock
 * script is never executed and the unique indexes are never consulted. Those mocks can only
 * confirm the Java control flow; they cannot produce a "0 occurrences" number. This test runs
 * the real {@link OrderService} through a real {@code @Transactional} proxy so that a unique-key
 * violation actually rolls the surrounding transaction back.
 *
 * <p>Needs a reachable MySQL. Credentials come from the environment and fall back to the same
 * defaults as {@code application.yml}, so nothing secret lives in this file:
 * {@code DB_USERNAME} (cinema), {@code DB_PASSWORD} (cinema), {@code DB_URL}.
 */
@TestMethodOrder(MethodOrderer.OrderAnnotation.class)
class OrderConcurrencyConsistencyTest {

    private static final int REDIS_PORT = findFreePort();
    private static final int ROUNDS = 3;
    private static final int SEAT_COUNT = 60;
    private static final int CONNECTION_POOL_SIZE = 64;

    private static final String DEFAULT_DB_URL = "jdbc:mysql://localhost:3306/cinema_ticketing"
            + "?createDatabaseIfNotExist=true&useSSL=false&allowPublicKeyRetrieval=true"
            + "&serverTimezone=Asia/Shanghai&characterEncoding=utf8";

    /** Every fixture this test creates is named with this prefix so cleanup can be precise. */
    private static final String TEST_PREFIX = "zzt-";

    private static final List<String[]> REPORT = new ArrayList<>();
    private static String payFailureType = "none";

    private static RedisServer redisServer;
    private static AnnotationConfigApplicationContext context;
    private static OrderService orderService;
    private static JdbcTemplate jdbc;

    private static long testUserId;
    private static long testMovieId;
    private static long testCinemaId;
    private static long testHallId;
    private static final List<Long> seatPool = new ArrayList<>();

    // ------------------------------------------------------------------ wiring

    @Configuration
    @EnableTransactionManagement
    static class TestConfig {

        @Bean(destroyMethod = "close")
        DataSource dataSource() {
            HikariConfig config = new HikariConfig();
            config.setJdbcUrl(env("DB_URL", DEFAULT_DB_URL));
            config.setUsername(env("DB_USERNAME", "cinema"));
            config.setPassword(env("DB_PASSWORD", "cinema"));
            // Threads beyond this queue on the pool; contention is still real because they
            // bunch up at the Redis EVAL and at the unique index rather than being serialised.
            config.setMaximumPoolSize(CONNECTION_POOL_SIZE);
            config.setPoolName("zzt-pool");
            return new HikariDataSource(config);
        }

        @Bean
        JdbcTemplate jdbcTemplate(DataSource dataSource) {
            return new JdbcTemplate(dataSource);
        }

        @Bean
        PlatformTransactionManager transactionManager(DataSource dataSource) {
            return new DataSourceTransactionManager(dataSource);
        }

        @Bean(destroyMethod = "destroy")
        RedisConnectionFactory redisConnectionFactory() {
            return new LettuceConnectionFactory("127.0.0.1", REDIS_PORT);
        }

        @Bean
        StringRedisTemplate redisTemplate(RedisConnectionFactory connectionFactory) {
            return new StringRedisTemplate(connectionFactory);
        }

        /** Not under test; a real one would need a live broker. */
        @Bean
        OrderMessagePublisher orderMessagePublisher() {
            return mock(OrderMessagePublisher.class);
        }

        @Bean
        OrderService orderService(JdbcTemplate jdbcTemplate, StringRedisTemplate redisTemplate,
                                  OrderMessagePublisher publisher) {
            return new OrderService(jdbcTemplate, redisTemplate, publisher);
        }
    }

    // ------------------------------------------------------------------ lifecycle

    @BeforeAll
    static void setUp() throws Exception {
        redisServer = new RedisServer(REDIS_PORT);
        redisServer.start();

        context = new AnnotationConfigApplicationContext(TestConfig.class);
        jdbc = context.getBean(JdbcTemplate.class);
        orderService = context.getBean(OrderService.class);

        new ResourceDatabasePopulator(new ClassPathResource("schema.sql"))
                .execute(context.getBean(DataSource.class));

        cleanupFixtures();
        seedFixtures();
    }

    @AfterAll
    static void tearDown() throws IOException {
        printReport();
        if (context != null) {
            try {
                if ("true".equals(System.getProperty("zzt.keepFixtures"))) {
                    // Lets verify-consistency.sql be run against the rows this test just wrote,
                    // so the Java assertions and the standalone SQL can be compared directly.
                    System.out.println("zzt.keepFixtures=true -> test rows kept. "
                            + "Run again without the flag to remove them.");
                } else {
                    cleanupFixtures();
                }
            } finally {
                context.close();
            }
        }
        if (redisServer != null) {
            redisServer.stop();
        }
    }

    // ------------------------------------------------------------------ scenarios

    @Test
    @Order(1)
    @DisplayName("座位并发抢占：200 个不同用户同抢一个座位，只允许 1 个成功")
    void seatLockIsGrantedToExactlyOneOwnerUnderContention() throws Exception {
        int threads = 200;
        int totalDuplicates = 0;

        for (int round = 1; round <= ROUNDS; round++) {
            final int r = round;
            long screeningId = newScreening();
            long seatId = seatPool.get(0);
            clearLocks(screeningId, List.of(seatId));

            AtomicInteger granted = new AtomicInteger();
            AtomicInteger rejected = new AtomicInteger();
            List<Throwable> unexpected = Collections.synchronizedList(new ArrayList<>());

            runConcurrently(threads, i -> {
                try {
                    orderService.lockSeats(TEST_PREFIX + "lock-" + r + "-" + i, screeningId, List.of(seatId));
                    granted.incrementAndGet();
                } catch (BusinessException exception) {
                    if (exception.getCode() == 409) {
                        rejected.incrementAndGet();
                    } else {
                        unexpected.add(exception);
                    }
                } catch (Throwable throwable) {
                    unexpected.add(throwable);
                }
            });

            assertTrue(unexpected.isEmpty(), "unexpected failures in round " + r + ": " + unexpected);
            assertEquals(threads, granted.get() + rejected.get(), "every thread must either win or get 409");
            assertEquals(1, granted.get(), "round " + r + ": exactly one owner may hold the seat lock");

            totalDuplicates += granted.get() - 1;
            System.out.printf("  [座位并发抢占] 第%d轮: 线程=%d 成功锁座=%d 被拒409=%d%n",
                    r, threads, granted.get(), rejected.get());
        }

        record("座位并发抢占-重复锁定", "0 次", totalDuplicates + " 次", totalDuplicates == 0);
    }

    @Test
    @Order(2)
    @DisplayName("下单幂等：同一 requestId 并发 100 次，只落 1 笔订单")
    void concurrentDuplicateRequestsCreateExactlyOneOrder() throws Exception {
        int threads = 100;
        int totalDuplicateOrders = 0;
        int worstRejected = 0;

        for (int round = 1; round <= ROUNDS; round++) {
            final int r = round;
            long screeningId = newScreening();
            long seatId = seatPool.get(r);
            clearLocks(screeningId, List.of(seatId));

            String owner = TEST_PREFIX + "idem-owner-" + r;
            String requestId = TEST_PREFIX + "idem-req-" + r;
            orderService.lockSeats(owner, screeningId, List.of(seatId));

            List<String> returnedOrderNos = Collections.synchronizedList(new ArrayList<>());
            AtomicInteger rejected = new AtomicInteger();

            runConcurrently(threads, i -> {
                try {
                    OrderView view = orderService.createOrder(testUserId, owner,
                            new CreateOrderRequest(screeningId, List.of(seatId), requestId));
                    returnedOrderNos.add(view.orderNo());
                } catch (DuplicateKeyException | BusinessException exception) {
                    // The losing threads collide on uk_order_request.
                    rejected.incrementAndGet();
                }
            });

            int orders = count("SELECT COUNT(*) FROM ticket_order WHERE screening_id = ? AND user_id = ?",
                    screeningId, testUserId);
            int idempotencyRows = count(
                    "SELECT COUNT(*) FROM order_idempotency WHERE user_id = ? AND request_id = ?",
                    testUserId, requestId);
            int distinctOrderNos = new HashSet<>(returnedOrderNos).size();

            System.out.printf("  [下单幂等] 第%d轮: 线程=%d 返回订单号种类=%d 落库订单=%d 幂等记录=%d 冲突被拒=%d%n",
                    r, threads, distinctOrderNos, orders, idempotencyRows, rejected.get());

            assertEquals(1, orders, "round " + r + ": the unique index must leave exactly one order");
            assertEquals(1, idempotencyRows, "round " + r + ": exactly one idempotency record");
            assertTrue(distinctOrderNos <= 1, "round " + r + ": every success must reference the same order");

            totalDuplicateOrders += orders - 1;
            worstRejected = Math.max(worstRejected, rejected.get());
        }

        record("下单幂等-重复订单", "0 笔", totalDuplicateOrders + " 笔", totalDuplicateOrders == 0);
        // Reported separately: a losing thread surfaces DuplicateKeyException, for which
        // GlobalExceptionHandler has no branch, so the caller gets HTTP 500 instead of the
        // existing order. The stored order count is still correct -- these are two facts.
        recordDefect("下单幂等-并发冲突返回500", worstRejected);
    }

    @Test
    @Order(3)
    @DisplayName("防超卖：50 个座位、300 线程抢座下单，同一座位不得出现在两笔订单")
    void oversellNeverHappensAcrossConcurrentOrders() throws Exception {
        int seatCount = 50;
        int threads = 300;
        int totalOversold = 0;

        for (int round = 1; round <= ROUNDS; round++) {
            final int r = round;
            long screeningId = newScreening();
            List<Long> seats = List.copyOf(seatPool.subList(0, seatCount));
            clearLocks(screeningId, seats);

            AtomicInteger locked = new AtomicInteger();
            AtomicInteger ordered = new AtomicInteger();

            runConcurrently(threads, i -> {
                long seatId = seats.get(i % seatCount);
                String owner = TEST_PREFIX + "os-" + r + "-" + i;
                try {
                    orderService.lockSeats(owner, screeningId, List.of(seatId));
                    locked.incrementAndGet();
                } catch (BusinessException exception) {
                    return;     // seat already taken, expected
                }
                try {
                    orderService.createOrder(testUserId, owner, new CreateOrderRequest(
                            screeningId, List.of(seatId), TEST_PREFIX + "os-req-" + r + "-" + i));
                    ordered.incrementAndGet();
                } catch (RuntimeException exception) {
                    // A thread that lost the lock race can still reach here if its lock expired;
                    // it must not, however, produce a second order for the same seat.
                }
            });

            int oversold = count("""
                    SELECT COUNT(*) FROM (
                      SELECT oi.seat_id
                      FROM order_item oi JOIN ticket_order o ON o.id = oi.order_id
                      WHERE o.screening_id = ? AND o.status IN ('UNPAID', 'PAID', 'ISSUED')
                      GROUP BY oi.seat_id HAVING COUNT(DISTINCT oi.order_id) > 1
                    ) duplicated""", screeningId);

            System.out.printf("  [防超卖] 第%d轮: 线程=%d 座位=%d 锁座成功=%d 下单成功=%d 重复售出座位=%d%n",
                    r, threads, seatCount, locked.get(), ordered.get(), oversold);

            assertEquals(0, oversold, "round " + r + ": no seat may appear in two live orders");
            assertTrue(ordered.get() <= seatCount, "round " + r + ": sold more tickets than seats");
            totalOversold += oversold;
        }

        record("防超卖-超卖", "0 笔", totalOversold + " 笔", totalOversold == 0);
    }

    @Test
    @Order(4)
    @DisplayName("支付幂等：同一 paymentNo 并发 50 次，只落 1 条流水")
    void concurrentDuplicatePaymentsCreateExactlyOneTransaction() throws Exception {
        int threads = 50;
        int totalDuplicatePayments = 0;
        int worstFailures = 0;
        String failureType = "none";

        for (int round = 1; round <= ROUNDS; round++) {
            final int r = round;
            long screeningId = newScreening();
            long seatId = seatPool.get(r + 5);
            clearLocks(screeningId, List.of(seatId));

            String owner = TEST_PREFIX + "pay-owner-" + r;
            String paymentNo = TEST_PREFIX + "pay-no-" + r;
            orderService.lockSeats(owner, screeningId, List.of(seatId));
            OrderView order = orderService.createOrder(testUserId, owner,
                    new CreateOrderRequest(screeningId, List.of(seatId), TEST_PREFIX + "pay-req-" + r));

            AtomicInteger settled = new AtomicInteger();
            List<Throwable> failed = Collections.synchronizedList(new ArrayList<>());

            runConcurrently(threads, i -> {
                try {
                    orderService.pay(testUserId, owner, order.orderNo(), paymentNo);
                    settled.incrementAndGet();
                } catch (Throwable throwable) {
                    failed.add(throwable);
                }
            });

            int transactions = count("SELECT COUNT(*) FROM payment_transaction WHERE payment_no = ?", paymentNo);
            String status = jdbc.queryForObject(
                    "SELECT status FROM ticket_order WHERE order_no = ?", String.class, order.orderNo());

            System.out.printf("  [支付幂等] 第%d轮: 线程=%d 流水条数=%d 订单终态=%s 成功=%d 抛异常=%d%n",
                    r, threads, transactions, status, settled.get(), failed.size());

            // The invariants that matter: money is captured once, and the order settles once.
            assertEquals(1, transactions, "round " + r + ": one payment_no must yield one transaction");
            assertEquals("ISSUED", status, "round " + r + ": the order must settle exactly once");
            totalDuplicatePayments += transactions - 1;
            if (failed.size() > worstFailures) {
                worstFailures = failed.size();
                failureType = failed.getFirst().getClass().getSimpleName();
            }
        }

        record("支付幂等-重复支付", "0 笔", totalDuplicatePayments + " 笔", totalDuplicatePayments == 0);
        // The compensating read after a duplicate payment key is issued inside the same
        // transaction, so under REPEATABLE READ it cannot see the winner's committed row and
        // queryForMap throws instead of returning it. Money is still captured once; the caller
        // just gets a 500. Recorded here rather than asserted, so the claim above stays honest.
        REPORT.add(new String[]{"支付幂等-补偿查询失效", "0 个请求", worstFailures + " 个请求",
                worstFailures == 0 ? "PASS" : "缺陷"});
        payFailureType = failureType;
    }

    // ------------------------------------------------------------------ fixtures

    private static void seedFixtures() {
        testUserId = insertReturningId(
                "INSERT INTO users (username, password_hash, phone, role, status) VALUES (?, ?, ?, 'USER', 'ACTIVE')",
                TEST_PREFIX + "user", "x", null);
        testCinemaId = insertReturningId(
                "INSERT INTO cinema (name, address, phone, status) VALUES (?, ?, ?, 'ACTIVE')",
                TEST_PREFIX + "cinema", "test", null);
        testHallId = insertReturningId(
                "INSERT INTO hall (cinema_id, name, row_count, column_count, hall_type, status) "
                        + "VALUES (?, ?, 1, ?, 'STANDARD', 'ACTIVE')",
                testCinemaId, TEST_PREFIX + "hall", SEAT_COUNT);
        testMovieId = insertReturningId(
                "INSERT INTO movie (title, description, duration, genre, status) VALUES (?, ?, 120, 'TEST', 'ON_SHOW')",
                TEST_PREFIX + "movie", "test");

        for (int column = 1; column <= SEAT_COUNT; column++) {
            seatPool.add(insertReturningId(
                    "INSERT INTO seat (hall_id, row_no, column_no, seat_code, seat_type, status) "
                            + "VALUES (?, 1, ?, ?, 'STANDARD', 'AVAILABLE')",
                    testHallId, column, "Z" + column));
        }
    }

    /** Deletes only rows this test created, children before parents so the FKs hold. */
    private static void cleanupFixtures() {
        String[] statements = {
                "DELETE oi FROM order_item oi JOIN ticket_order o ON o.id = oi.order_id "
                        + "JOIN users u ON u.id = o.user_id WHERE u.username LIKE '" + TEST_PREFIX + "%'",
                "DELETE r FROM refund_record r JOIN ticket_order o ON o.id = r.order_id "
                        + "JOIN users u ON u.id = o.user_id WHERE u.username LIKE '" + TEST_PREFIX + "%'",
                "DELETE p FROM payment_transaction p JOIN ticket_order o ON o.id = p.order_id "
                        + "JOIN users u ON u.id = o.user_id WHERE u.username LIKE '" + TEST_PREFIX + "%'",
                "DELETE i FROM order_idempotency i JOIN users u ON u.id = i.user_id "
                        + "WHERE u.username LIKE '" + TEST_PREFIX + "%'",
                "DELETE o FROM ticket_order o JOIN users u ON u.id = o.user_id "
                        + "WHERE u.username LIKE '" + TEST_PREFIX + "%'",
                "DELETE FROM message_consume_record WHERE message_id LIKE '" + TEST_PREFIX + "%'",
                "DELETE s FROM screening s JOIN hall h ON h.id = s.hall_id JOIN cinema c ON c.id = h.cinema_id "
                        + "WHERE c.name LIKE '" + TEST_PREFIX + "%'",
                "DELETE FROM screening WHERE movie_id IN (SELECT id FROM movie WHERE title LIKE '" + TEST_PREFIX + "%')",
                "DELETE FROM seat WHERE hall_id IN (SELECT id FROM hall WHERE name LIKE '" + TEST_PREFIX + "%')",
                "DELETE FROM hall WHERE name LIKE '" + TEST_PREFIX + "%'",
                "DELETE FROM movie WHERE title LIKE '" + TEST_PREFIX + "%'",
                "DELETE FROM cinema WHERE name LIKE '" + TEST_PREFIX + "%'",
                "DELETE FROM users WHERE username LIKE '" + TEST_PREFIX + "%'",
        };
        for (String statement : statements) {
            jdbc.update(statement);
        }
    }

    private static long newScreening() {
        return insertReturningId(
                "INSERT INTO screening (movie_id, hall_id, start_time, end_time, price, status) "
                        + "VALUES (?, ?, DATE_ADD(NOW(), INTERVAL 2 DAY), "
                        + "DATE_ADD(DATE_ADD(NOW(), INTERVAL 2 DAY), INTERVAL 2 HOUR), 42.00, 'SCHEDULED')",
                testMovieId, testHallId);
    }

    // ------------------------------------------------------------------ helpers

    private static void runConcurrently(int threads, IntConsumer task) throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(threads);
        CountDownLatch startLine = new CountDownLatch(1);
        List<Future<?>> futures = new ArrayList<>();
        try {
            for (int i = 0; i < threads; i++) {
                final int index = i;
                futures.add(pool.submit(() -> {
                    startLine.await();
                    task.accept(index);
                    return null;
                }));
            }
            startLine.countDown();          // release only after every worker is parked on the
            for (Future<?> future : futures) {   // latch, so the burst is genuinely simultaneous
                future.get(120, TimeUnit.SECONDS);
            }
        } finally {
            pool.shutdownNow();
        }
    }

    private static void clearLocks(long screeningId, List<Long> seatIds) {
        StringRedisTemplate redis = context.getBean(StringRedisTemplate.class);
        seatIds.forEach(seatId -> redis.delete("seat:lock:" + screeningId + ":" + seatId));
    }

    private static long insertReturningId(String sql, Object... args) {
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbc.update(connection -> {
            PreparedStatement statement = connection.prepareStatement(sql, Statement.RETURN_GENERATED_KEYS);
            for (int i = 0; i < args.length; i++) {
                statement.setObject(i + 1, args[i]);
            }
            return statement;
        }, keyHolder);
        Number key = keyHolder.getKey();
        if (key == null) {
            throw new IllegalStateException("no generated key for: " + sql);
        }
        return key.longValue();
    }

    private static int count(String sql, Object... args) {
        Integer value = jdbc.queryForObject(sql, Integer.class, args);
        return value == null ? 0 : value;
    }

    private static void record(String metric, String expected, String actual, boolean pass) {
        REPORT.add(new String[]{metric, expected, actual, pass ? "PASS" : "FAIL"});
    }

    /**
     * A measured weakness that is not one of the four claimed metrics. Kept separate from
     * {@link #record} so a passing run never reads as if the defect were part of the claim.
     */
    private static void recordDefect(String metric, int occurrences) {
        REPORT.add(new String[]{metric, "0 个请求", occurrences + " 个请求",
                occurrences == 0 ? "PASS" : "缺陷"});
    }

    private static void printReport() {
        System.out.println();
        System.out.println("=".repeat(84));
        System.out.println(" 影院项目并发一致性实测结果（真实 Redis + 真实 MySQL，每项重复 " + ROUNDS + " 轮）");
        System.out.println("=".repeat(84));
        System.out.println(pad("指标", 36) + pad("期望", 14) + pad("实测", 18) + "判定");
        System.out.println("-".repeat(84));
        for (String[] row : REPORT) {
            System.out.println(pad(row[0], 36) + pad(row[1], 14) + pad(row[2], 18) + row[3]);
        }
        System.out.println("-".repeat(84));
        System.out.println(" PASS = 该项声称的指标成立，数据没写坏。");
        System.out.println(" 缺陷 = 数据仍然正确，但并发调用方拿到 500 而不是成功响应，属于额外发现，");
        System.out.println("        不影响上面四个数字。补偿查询抛的是 " + payFailureType + "。");
        System.out.println("=".repeat(84));
    }

    /** CJK glyphs take two terminal columns, so String.format's width padding misaligns them. */
    private static String pad(String text, int columns) {
        int width = 0;
        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i);
            boolean wide = (c >= 0x1100 && c <= 0x115F)
                    || (c >= 0x2E80 && c <= 0xA4CF)
                    || (c >= 0xAC00 && c <= 0xD7A3)
                    || (c >= 0xF900 && c <= 0xFAFF)
                    || (c >= 0xFE30 && c <= 0xFE6F)
                    || (c >= 0xFF00 && c <= 0xFF60)
                    || (c >= 0xFFE0 && c <= 0xFFE6);
            width += wide ? 2 : 1;
        }
        return text + " ".repeat(Math.max(1, columns - width));
    }

    private static int findFreePort() {
        try (ServerSocket socket = new ServerSocket(0)) {
            return socket.getLocalPort();
        } catch (IOException exception) {
            throw new IllegalStateException("cannot allocate a port for embedded Redis", exception);
        }
    }

    private static String env(String name, String fallback) {
        String value = System.getenv(name);
        return value == null || value.isBlank() ? fallback : value;
    }
}
