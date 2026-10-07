package com.cinema.ticketing.service;

import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.common.GlobalExceptionHandler;
import com.cinema.ticketing.config.AccountSecuritySchemaInitializer;
import com.cinema.ticketing.controller.AccountSecurityController;
import com.cinema.ticketing.mapper.UserMapper;

import org.apache.ibatis.session.SqlSessionFactory;
import org.junit.jupiter.api.*;
import org.mybatis.spring.SqlSessionFactoryBean;
import org.mybatis.spring.SqlSessionTemplate;
import org.springframework.context.annotation.*;
import org.springframework.core.io.ClassPathResource;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.transaction.annotation.EnableTransactionManagement;

import redis.embedded.RedisServer;

import java.net.ServerSocket;
import java.time.Duration;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;

import javax.sql.DataSource;

/** Real mapper, SQL transactions and isolated Redis; no real accounts or external services. */
class AccountSecurityIntegrationTest {
    private static RedisServer server;
    private static int port;
    private static AnnotationConfigApplicationContext context;
    private AuthService auth;
    private AccountSecurityService accounts;
    private AiHandoffService handoff;
    private JdbcTemplate jdbc;
    private StringRedisTemplate redis;
    private String admin;
    private MockMvc mvc;

    @Configuration
    @EnableTransactionManagement
    static class Wiring {
        @Bean
        DataSource dataSource() {
            return new DriverManagerDataSource(
                    "jdbc:h2:mem:security;MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1",
                    "sa",
                    "");
        }

        @Bean
        JdbcTemplate jdbc(DataSource source) {
            return new JdbcTemplate(source);
        }

        @Bean
        DataSourceTransactionManager transactionManager(DataSource source) {
            return new DataSourceTransactionManager(source);
        }

        @Bean
        SqlSessionFactory sqlSessionFactory(DataSource source) throws Exception {
            var factory = new SqlSessionFactoryBean();
            factory.setDataSource(source);
            factory.setMapperLocations(new ClassPathResource("UserMapper.xml"));
            return factory.getObject();
        }

        @Bean
        UserMapper mapper(SqlSessionFactory factory) {
            return new SqlSessionTemplate(factory).getMapper(UserMapper.class);
        }

        @Bean
        LettuceConnectionFactory connection() {
            return new LettuceConnectionFactory("127.0.0.1", port);
        }

        @Bean
        StringRedisTemplate redis(LettuceConnectionFactory connection) {
            return new StringRedisTemplate(connection);
        }

        @Bean
        AuthService auth(UserMapper mapper, StringRedisTemplate redis) {
            return new AuthService(mapper, redis);
        }

        @Bean
        AccountSecurityService accounts(JdbcTemplate jdbc, AuthService auth) {
            return new AccountSecurityService(jdbc, auth);
        }

        @Bean
        AiHandoffService handoff(StringRedisTemplate redis, AuthService auth) {
            return new AiHandoffService(redis, auth);
        }
    }

    @BeforeAll
    static void start() throws Exception {
        try (var listener = new ServerSocket(0)) {
            port = listener.getLocalPort();
        }
        server = new RedisServer(port);
        server.start();
        context = new AnnotationConfigApplicationContext(Wiring.class);
        context.getBean(JdbcTemplate.class)
                .execute(
                        "CREATE TABLE users (id BIGINT AUTO_INCREMENT PRIMARY KEY, username"
                            + " VARCHAR(64) UNIQUE, password_hash VARCHAR(100), phone VARCHAR(32),"
                            + " role VARCHAR(16), status VARCHAR(16), session_version BIGINT NOT"
                            + " NULL DEFAULT 0)");
    }

    @AfterAll
    static void stop() throws Exception {
        if (context != null) context.close();
        if (server != null) server.stop();
    }

    @BeforeEach
    void seed() {
        auth = context.getBean(AuthService.class);
        accounts = context.getBean(AccountSecurityService.class);
        handoff = context.getBean(AiHandoffService.class);
        jdbc = context.getBean(JdbcTemplate.class);
        redis = context.getBean(StringRedisTemplate.class);
        jdbc.update("DELETE FROM users");
        String hash = new BCryptPasswordEncoder().encode("test-password-123");
        for (int id = 1; id <= 3; id++)
            jdbc.update(
                    "INSERT INTO users (id,username,password_hash,role,status) VALUES"
                        + " (?,?,?,?,'ACTIVE')",
                    id,
                    "fixture" + id,
                    hash,
                    id == 3 ? "USER" : "ADMIN");
        admin = login(1);
        mvc =
                MockMvcBuilders.standaloneSetup(
                                new AccountSecurityController(auth, accounts, "fixture-internal"))
                        .setControllerAdvice(new GlobalExceptionHandler())
                        .build();
    }

    private String login(int id) {
        return auth.login("fixture" + id, "test-password-123").token();
    }

    private void rejected(String token) {
        assertEquals(
                401,
                assertThrows(BusinessException.class, () -> auth.requireUserId(token)).getCode());
        assertEquals(
                401,
                assertThrows(BusinessException.class, () -> auth.requireAdmin(token)).getCode());
        assertThrows(BusinessException.class, () -> auth.current(token));
    }

    private String credential(String token) {
        return (String) handoff.issue(token, UUID.randomUUID().toString()).get("credential");
    }

    @Test
    void demotionRevokesBothDevicesAndHandoff() {
        String first = login(2), second = login(2), oldCredential = credential(second);
        accounts.updateAccess(admin, 2, "USER", "ACTIVE", 0);
        assertTrue(redis.hasKey("auth:session:" + second));
        assertEquals(
                401,
                assertThrows(BusinessException.class, () -> handoff.resolve(oldCredential))
                        .getCode());
        rejected(first);
        rejected(second);
        String newLogin = login(2);
        assertEquals(2, auth.requireUserId(newLogin));
        assertEquals(
                403,
                assertThrows(BusinessException.class, () -> auth.requireAdmin(newLogin)).getCode());
        assertEquals(1, auth.requireUserId(admin));
    }

    @Test
    void disableThenEnableDoesNotReviveOldSessions() {
        String first = login(3), second = login(3), oldCredential = credential(first);
        accounts.updateAccess(admin, 3, "USER", "DISABLED", 0);
        assertEquals(403, assertThrows(BusinessException.class, () -> login(3)).getCode());
        rejected(second);
        accounts.updateAccess(admin, 3, "USER", "ACTIVE", 1);
        rejected(first);
        assertThrows(BusinessException.class, () -> handoff.resolve(oldCredential));
        assertEquals(3, auth.requireUserId(login(3)));
    }

    @Test
    void passwordChangeRevokesAllTokensAndOldPassword() {
        String first = login(3), second = login(3), oldCredential = credential(second);
        auth.changePassword(first, "test-password-123", "replacement-password");
        rejected(first);
        rejected(second);
        assertThrows(BusinessException.class, () -> handoff.resolve(oldCredential));
        assertThrows(BusinessException.class, () -> login(3));
        assertEquals(3, auth.requireUserId(auth.login("fixture3", "replacement-password").token()));
        assertEquals(
                1, jdbc.queryForObject("SELECT session_version FROM users WHERE id=3", Long.class));
    }

    @Test
    void invalidPasswordChangesDoNotRevokeOrChangePassword() {
        String token = login(3);
        assertThrows(
                BusinessException.class,
                () -> auth.changePassword(token, "wrong-password", "replacement-password"));
        assertThrows(
                BusinessException.class,
                () -> auth.changePassword(token, "test-password-123", "test-password-123"));
        assertThrows(
                BusinessException.class,
                () -> auth.changePassword(token, "test-password-123", "中".repeat(25)));
        assertEquals(3, auth.requireUserId(token));
        assertEquals(
                0, jdbc.queryForObject("SELECT session_version FROM users WHERE id=3", Long.class));
        assertEquals(3, auth.requireUserId(login(3)));
    }

    @Test
    void logoutOneAndLogoutAllHaveDifferentScope() {
        String first = login(3), second = login(3);
        auth.logout(first);
        rejected(first);
        assertEquals(3, auth.requireUserId(second));
        String third = login(3), oldCredential = credential(third);
        auth.logoutAll(second);
        rejected(second);
        rejected(third);
        assertThrows(BusinessException.class, () -> handoff.resolve(oldCredential));
        assertEquals(1, auth.requireUserId(admin));
    }

    @Test
    void adminForcedLogoutAndStaleUpdatesAreGuarded() {
        String first = login(3), second = login(3);
        accounts.revoke(admin, 3, 0);
        rejected(first);
        rejected(second);
        assertEquals(
                409,
                assertThrows(
                                BusinessException.class,
                                () -> accounts.updateAccess(admin, 3, "ADMIN", "ACTIVE", 0))
                        .getCode());
        assertEquals(
                "USER", jdbc.queryForObject("SELECT role FROM users WHERE id=3", String.class));
        accounts.updateAccess(admin, 3, "USER", "ACTIVE", 1);
        assertEquals(
                1, jdbc.queryForObject("SELECT session_version FROM users WHERE id=3", Long.class));
    }

    @Test
    void lastAdminAndOrdinaryUserCannotModifyAccess() {
        accounts.updateAccess(admin, 2, "USER", "ACTIVE", 0);
        assertEquals(
                409,
                assertThrows(
                                BusinessException.class,
                                () -> accounts.updateAccess(admin, 1, "USER", "ACTIVE", 0))
                        .getCode());
        assertEquals(
                409,
                assertThrows(
                                BusinessException.class,
                                () -> accounts.updateAccess(admin, 1, "ADMIN", "DISABLED", 0))
                        .getCode());
        assertEquals(
                403,
                assertThrows(BusinessException.class, () -> accounts.revoke(login(3), 1, 0))
                        .getCode());
        assertEquals(1, auth.requireUserId(admin));
    }

    @Test
    void concurrentAdminRemovalsCannotRemoveEveryAdmin() throws Exception {
        String other = login(2);
        CountDownLatch start = new CountDownLatch(1);
        try (var executor = Executors.newFixedThreadPool(2)) {
            var first =
                    executor.submit(
                            () -> {
                                start.await();
                                try {
                                    accounts.updateAccess(admin, 1, "USER", "ACTIVE", 0);
                                } catch (BusinessException ignored) {
                                }
                                return null;
                            });
            var second =
                    executor.submit(
                            () -> {
                                start.await();
                                try {
                                    accounts.updateAccess(other, 2, "USER", "ACTIVE", 0);
                                } catch (BusinessException ignored) {
                                }
                                return null;
                            });
            start.countDown();
            first.get();
            second.get();
        }
        assertEquals(
                1,
                jdbc.queryForObject(
                        "SELECT COUNT(*) FROM users WHERE role='ADMIN' AND status='ACTIVE'",
                        Integer.class));
    }

    @Test
    void legacyMalformedAndNonExpiringRedisSessionsFailClosed() {
        String token = login(3);
        redis.opsForHash().delete("auth:session:" + token, "sessionVersion");
        rejected(token);
        token = login(3);
        redis.persist("auth:session:" + token);
        rejected(token);
        token = login(3);
        redis.opsForHash().put("auth:session:" + token, "sessionVersion", "corrupted");
        rejected(token);
        rejected("invalid-token");
    }

    @Test
    void directRoleAndStatusChangesAreObservedWithoutMe() {
        String token = login(2);
        jdbc.update("UPDATE users SET role='USER' WHERE id=2");
        rejected(token);
        token = login(3);
        jdbc.update("UPDATE users SET status='DISABLED' WHERE id=3");
        rejected(token);
    }

    @Test
    void verificationDoesNotExtendExpiryOrExposePassword() throws Exception {
        String token = login(3);
        redis.expire("auth:session:" + token, Duration.ofSeconds(30));
        auth.current(token);
        assertTrue(redis.getExpire("auth:session:" + token) <= 30);
        assertNull(context.getBean(UserMapper.class).findById(3).getPasswordHash());
        mvc.perform(get("/api/admin/accounts").header("X-Auth-Token", admin))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data[0].password_hash").doesNotExist());
        mvc.perform(
                        post("/internal/ai/auth/resolve")
                                .header("X-Internal-Token", "wrong")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"token\":\"" + token + "\"}"))
                .andExpect(status().isForbidden());
        mvc.perform(
                        post("/internal/ai/auth/resolve")
                                .header("X-Internal-Token", "fixture-internal")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"token\":\"" + token + "\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.userId").value(3));
        auth.logoutAll(token);
        mvc.perform(
                        post("/internal/ai/auth/resolve")
                                .header("X-Internal-Token", "fixture-internal")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"token\":\"" + token + "\"}"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void schemaMigrationIsIdempotentAndKeepsExistingUsers() {
        jdbc.execute("ALTER TABLE users DROP COLUMN session_version");
        var migration = new AccountSecuritySchemaInitializer(jdbc);
        migration.run(null);
        migration.run(null);
        assertEquals(3, jdbc.queryForObject("SELECT COUNT(*) FROM users", Integer.class));
        assertEquals(0, jdbc.queryForObject("SELECT SUM(session_version) FROM users", Long.class));
    }
}
