package com.cinema.ticketing.service;

import static org.junit.jupiter.api.Assertions.*;

import com.cinema.ticketing.common.BusinessException;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.aop.framework.ProxyFactory;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.transaction.annotation.AnnotationTransactionAttributeSource;
import org.springframework.transaction.interceptor.TransactionInterceptor;

import java.util.List;
import java.util.UUID;

/** Real SQL and Spring transactions verify isolation, optimistic writes and outbox recovery. */
class AiMemoryServiceTest {
    private JdbcTemplate jdbc;
    private AiMemoryService service;

    @BeforeEach
    void setup() {
        var source =
                new DriverManagerDataSource(
                        "jdbc:h2:mem:"
                                + UUID.randomUUID()
                                + ";MODE=MySQL;DB_CLOSE_DELAY=-1;DATABASE_TO_LOWER=TRUE",
                        "sa",
                        "");
        jdbc = new JdbcTemplate(source);
        jdbc.execute("CREATE TABLE users(id BIGINT PRIMARY KEY)");
        jdbc.update("INSERT INTO users VALUES(1),(2)");
        new ResourceDatabasePopulator(new ClassPathResource("ai-memory-schema.sql"))
                .execute(source);
        var proxy = new ProxyFactory(new AiMemoryService(jdbc));
        proxy.addAdvice(
                new TransactionInterceptor(
                        new DataSourceTransactionManager(source),
                        new AnnotationTransactionAttributeSource()));
        service = (AiMemoryService) proxy.getProxy();
    }

    private String create() {
        return (String)
                service.create(1, new AiMemoryService.Input("我喜欢科幻电影", "GENRE", null, null))
                        .get("id");
    }

    @Test
    void ownersAndVersionsAreCheckedOnEveryReadAndWrite() {
        String id = create();
        assertEquals(1, service.list(1).size());
        assertTrue(service.list(2).isEmpty());
        var candidate = new AiMemoryService.Candidate(UUID.fromString(id), 1);
        assertTrue(
                service.verify(new AiMemoryService.VerifyInput(2, List.of(candidate))).isEmpty());
        assertEquals(
                404,
                assertThrows(BusinessException.class, () -> service.delete(2, id, 1)).getCode());
        service.update(1, id, new AiMemoryService.Input("喜欢喜剧", "GENRE", null, 1));
        assertTrue(
                service.verify(new AiMemoryService.VerifyInput(1, List.of(candidate))).isEmpty());
        assertEquals(
                409,
                assertThrows(
                                BusinessException.class,
                                () ->
                                        service.update(
                                                1,
                                                id,
                                                new AiMemoryService.Input(
                                                        "旧修改", "GENERAL", null, 1)))
                        .getCode());
        service.delete(1, id, 2);
        assertTrue(service.list(1).isEmpty());
        assertTrue(
                service.verify(
                                new AiMemoryService.VerifyInput(
                                        1,
                                        List.of(
                                                new AiMemoryService.Candidate(
                                                        UUID.fromString(id), 2))))
                        .isEmpty());
    }

    @Test
    void sqlAndOutboxCommitTogether() {
        jdbc.execute("DROP TABLE ai_memory_index_outbox");
        assertThrows(Exception.class, this::create);
        assertTrue(service.list(1).isEmpty(), "failed outbox insertion must roll back memory");
    }

    @Test
    void orderedJobsUseLeasesAndRejectLateAcknowledgements() {
        String id = create();
        service.update(1, id, new AiMemoryService.Input("喜欢喜剧", "GENRE", null, 1));
        var first = service.claim();
        assertEquals(1, first.size());
        assertTrue(service.claim().isEmpty());
        long jobId = ((Number) first.getFirst().get("jobId")).longValue();
        UUID oldLease = UUID.fromString((String) first.getFirst().get("leaseToken"));
        jdbc.update(
                "UPDATE ai_memory_index_outbox SET"
                    + " lease_until=DATEADD('MINUTE',-1,CURRENT_TIMESTAMP) WHERE id=?",
                jobId);
        var retried = service.claim().getFirst();
        assertEquals(
                409,
                assertThrows(
                                BusinessException.class,
                                () ->
                                        service.ack(
                                                jobId, new AiMemoryService.JobAck(oldLease, true)))
                        .getCode());
        service.ack(
                jobId,
                new AiMemoryService.JobAck(
                        UUID.fromString((String) retried.get("leaseToken")), true));
        assertEquals(2, ((Number) service.claim().getFirst().get("eventVersion")).intValue());
    }

    @Test
    void failedJobsRetryAndRebuildIncludesDeletion() {
        String id = create();
        var job = service.claim().getFirst();
        long jobId = ((Number) job.get("jobId")).longValue();
        service.ack(
                jobId,
                new AiMemoryService.JobAck(UUID.fromString((String) job.get("leaseToken")), false));
        assertTrue(service.claim().isEmpty());
        jdbc.update("UPDATE ai_memory_index_outbox SET available_at=CURRENT_TIMESTAMP");
        job = service.claim().getFirst();
        service.ack(
                jobId,
                new AiMemoryService.JobAck(UUID.fromString((String) job.get("leaseToken")), true));
        service.delete(1, id, 1);
        job = service.claim().getFirst();
        assertEquals("DELETED", ((java.util.Map<?, ?>) job.get("memory")).get("status"));
        service.ack(
                ((Number) job.get("jobId")).longValue(),
                new AiMemoryService.JobAck(UUID.fromString((String) job.get("leaseToken")), true));
        assertEquals(1, service.rebuild());
        assertEquals(2, ((Number) service.claim().getFirst().get("eventVersion")).intValue());
    }
}
