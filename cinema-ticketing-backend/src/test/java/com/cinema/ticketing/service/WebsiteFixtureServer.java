package com.cinema.ticketing.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import org.h2.tools.Server;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;

/** Test-only loopback fixture process. Not included in the production application jar. */
public class WebsiteFixtureServer {
    private static final ObjectMapper JSON = new ObjectMapper().findAndRegisterModules();
    private static final String ADVANCE_ORDER = "OWEBREG000012";
    private final JdbcTemplate jdbc;
    private final LocalDate today = LocalDate.now(ZoneId.of("Asia/Shanghai"));
    private final Map<String, String> orders = new LinkedHashMap<>();

    private WebsiteFixtureServer(String password) throws Exception {
        var source = new DriverManagerDataSource("jdbc:h2:mem:website;MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1", "sa", password);
        jdbc = new JdbcTemplate(source);
        String schema = new String(new ClassPathResource("schema.sql").getInputStream().readAllBytes(), StandardCharsets.UTF_8)
                .replace("\r\n", "\n")
                .replace("SET NAMES utf8mb4;", "")
                .replace(",\n    FULLTEXT KEY ft_knowledge_content (title, content)", "");
        new ResourceDatabasePopulator(new ByteArrayResource(schema.getBytes(StandardCharsets.UTF_8))).execute(source);
        seed();
    }

    private void seed() {
        String password = System.getenv("WEBSITE_FIXTURE_ACCOUNT_PASSWORD");
        String encoded = new BCryptPasswordEncoder().encode(password);
        jdbc.update("INSERT INTO users(id,username,password_hash,role,status) VALUES(70001,'website_reg_a',?,'USER','ACTIVE'),(70002,'website_reg_b',?,'USER','ACTIVE')", encoded, encoded);
        jdbc.update("INSERT INTO cinema(id,name,address,status) VALUES(70001,'回归测试影院','隔离测试地址','ACTIVE')");
        for (int hall = 1; hall <= 2; hall++) {
            jdbc.update("INSERT INTO hall(id,cinema_id,name,row_count,column_count,status) VALUES(?,70001,?,10,6,'ACTIVE')", 70000 + hall, "回归测试厅" + hall);
            for (int seat = 1; seat <= 60; seat++) jdbc.update("INSERT INTO seat(id,hall_id,row_no,column_no,seat_code,status) VALUES(?,?,?,?,?,'AVAILABLE')",
                    700000 + hall * 100 + seat, 70000 + hall, (seat - 1) / 6 + 1, (seat - 1) % 6 + 1, "测试座位" + seat);
        }
        movie(70001, "回归悬疑新片", today, "ON_SHOW", null);
        movie(70002, "回归悬疑旧片", today.minusDays(30), "ON_SHOW", null);
        movie(70003, "回归悬疑预售片", today.plusDays(7), "UPCOMING", today.plusDays(3).atStartOfDay());
        long screening = 71000;
        for (int day = -7; day <= 14; day++) {
            for (int film = 1; film <= 2; film++) for (int hour : new int[]{13, 19}) {
                LocalDateTime start = today.plusDays(day).atTime(hour + film - 1, 0);
                jdbc.update("INSERT INTO screening(id,movie_id,hall_id,start_time,end_time,price,status) VALUES(?,?,?,?,?,42,'SCHEDULED')",
                        ++screening, 70000 + film, 70000 + film, start, start.plusMinutes(90));
            }
        }
        LocalDateTime future = today.plusDays(2).atTime(19, 0);
        jdbc.update("INSERT INTO screening(id,movie_id,hall_id,start_time,end_time,price,status) VALUES(71999,70003,70001,?,?,42,'SCHEDULED')", future, future.plusMinutes(90));
        order(1, "UNPAID", "INIT", null, null, 180, false, 70001);
        order(2, "UNPAID", "CLOSING", null, null, 180, false, 70001);
        order(3, "CANCELLED", "CLOSED", null, null, 180, false, 70001);
        order(4, "ISSUED", "SUCCESS", null, null, 180, false, 70001);
        order(5, "ISSUED", "SUCCESS", null, null, 10, false, 70001);
        order(6, "ISSUED", "SUCCESS", null, null, -10, true, 70001);
        order(7, "REFUNDING", "SUCCESS", "PENDING", "CUSTOMER", 180, false, 70001);
        order(8, "REFUNDING", "SUCCESS", "UNKNOWN", "CUSTOMER", 180, false, 70001);
        order(9, "REFUNDED", "SUCCESS", "REFUNDED", "CUSTOMER", 180, false, 70001);
        order(10, "CANCELLED", "SUCCESS", "UNKNOWN", "LATE_PAYMENT", 180, false, 70001);
        order(11, "CANCELLED", "SUCCESS", "REFUNDED", "LATE_PAYMENT", 180, false, 70001);
        order(12, "REFUNDING", "SUCCESS", "PENDING", "CUSTOMER", 180, false, 70001);
        order(13, "BROKEN_STATE", "SUCCESS", null, null, 180, false, 70001);
        order(14, "ISSUED", "SUCCESS", null, null, 180, false, 70002);
    }

    private void movie(long id, String title, LocalDate release, String status, LocalDateTime saleStart) {
        jdbc.update("INSERT INTO movie(id,title,description,duration,release_date,genre,status,sale_start_time) VALUES(?,?,?,90,?,'悬疑',?,?)",
                id, title, "网站回归测试专用数据", release, status, saleStart);
    }

    private void order(int index, String status, String payment, String refund, String reason, int minutes, boolean checked, long user) {
        long id = 72000 + index;
        String number = "OWEBREG%06d".formatted(index);
        orders.put("O%02d".formatted(index), number);
        LocalDateTime now = LocalDateTime.now(ZoneId.of("Asia/Shanghai")).withNano(0);
        LocalDateTime start = now.plusMinutes(minutes);
        jdbc.update("INSERT INTO screening(id,movie_id,hall_id,start_time,end_time,price,status) VALUES(?,70001,70001,?,?,42,'SCHEDULED')", id, start, start.plusMinutes(90));
        jdbc.update("INSERT INTO ticket_order(id,order_no,user_id,screening_id,total_amount,status,lock_owner,expire_at,paid_at) VALUES(?,?,?,?,42,?,'website-fixture',?,?)",
                id, number, user, id, status, now.plusMinutes(30), payment.equals("SUCCESS") ? now.minusMinutes(1) : null);
        jdbc.update("INSERT INTO order_item(order_id,seat_id,price,ticket_status,checked_in_at) VALUES(?,?,42,?,?)",
                id, 700100 + index, status.equals("UNPAID") ? "VALID" : status, checked ? now.minusMinutes(2) : null);
        jdbc.update("INSERT INTO payment_order(id,order_id,out_trade_no,environment,app_id,seller_id,amount,status,expire_at,created_at,close_requested_at) "
                + "VALUES(?,?,?,'SANDBOX','9021999999999999','2088999999999999',42,?,?,?,?)", id, id, "PWEBREG" + index, payment,
                now.plusMinutes(30), now, payment.equals("CLOSING") ? now : null);
        if (payment.equals("SUCCESS")) jdbc.update("INSERT INTO payment_transaction(payment_no,order_id,amount,status,paid_at,channel,environment,payment_order_id) "
                + "VALUES(?,?,42,'SUCCESS',?,'ALIPAY','SANDBOX',?)", "PAYWEBREG" + index, id, now.minusMinutes(1), id);
        if (refund != null) jdbc.update("INSERT INTO refund_record(order_id,amount,reason,status,refunded_at,refund_no,payment_order_id,channel,environment,reason_type,requested_at) "
                + "VALUES(?,42,'网站回归测试',?,?,?,?,'ALIPAY','SANDBOX',?,?)", id, refund, refund.equals("REFUNDED") ? now : null,
                "RWEBREG" + index, id, reason, now.minusSeconds(10));
    }

    private void handle(HttpExchange exchange) throws java.io.IOException {
        String expected = System.getenv("WEBSITE_FIXTURE_TOKEN");
        String supplied = exchange.getRequestHeaders().getFirst("X-Fixture-Token");
        if (supplied == null || !MessageDigest.isEqual(expected.getBytes(StandardCharsets.UTF_8), supplied.getBytes(StandardCharsets.UTF_8))) {
            exchange.sendResponseHeaders(401, -1); exchange.close(); return;
        }
        String path = exchange.getRequestURI().getPath();
        Object value;
        int status = 200;
        if (path.equals("/advance") && exchange.getRequestMethod().equals("POST")) {
            jdbc.update("UPDATE ticket_order SET status='REFUNDED' WHERE order_no=?", ADVANCE_ORDER);
            jdbc.update("UPDATE order_item SET ticket_status='REFUNDED' WHERE order_id=(SELECT id FROM ticket_order WHERE order_no=?)", ADVANCE_ORDER);
            jdbc.update("UPDATE refund_record SET status='REFUNDED',refunded_at=? WHERE order_id=(SELECT id FROM ticket_order WHERE order_no=?)",
                    LocalDateTime.now(ZoneId.of("Asia/Shanghai")), ADVANCE_ORDER);
            value = Map.of("advanced", ADVANCE_ORDER);
        } else if (path.equals("/snapshot")) {
            value = Map.of("reference_date", today.toString(), "time_zone", "Asia/Shanghai", "orders", orders,
                    "movies", jdbc.queryForList("SELECT id,title,genre,release_date FROM movie ORDER BY id"),
                    "screenings", jdbc.queryForList("SELECT id,movie_id,start_time,status FROM screening ORDER BY id"));
        } else { status = 404; value = Map.of("error", "Unknown test-only endpoint"); }
        byte[] body = JSON.writeValueAsBytes(value);
        exchange.getResponseHeaders().set("Content-Type", "application/json;charset=UTF-8");
        exchange.sendResponseHeaders(status, body.length); exchange.getResponseBody().write(body); exchange.close();
    }

    public static void main(String[] args) throws Exception {
        System.setProperty("h2.bindAddress", "127.0.0.1");
        String password = System.getenv("WEBSITE_FIXTURE_DB_PASSWORD");
        if (password == null || password.length() < 20 || System.getenv("WEBSITE_FIXTURE_TOKEN") == null
                || System.getenv("WEBSITE_FIXTURE_ACCOUNT_PASSWORD") == null) throw new IllegalArgumentException("Missing private fixture environment");
        var fixture = new WebsiteFixtureServer(password);
        var database = Server.createTcpServer("-tcpPort", System.getenv().getOrDefault("WEBSITE_FIXTURE_DB_PORT", "19092"), "-tcpDaemon").start();
        var control = HttpServer.create(new InetSocketAddress("127.0.0.1", Integer.parseInt(System.getenv().getOrDefault("WEBSITE_FIXTURE_PORT", "18090"))), 0);
        control.createContext("/", fixture::handle); control.start();
        Runtime.getRuntime().addShutdownHook(new Thread(() -> { control.stop(0); database.stop(); }));
        System.out.println("Website fixture ready (isolated H2, loopback only)");
        new CountDownLatch(1).await();
    }
}
