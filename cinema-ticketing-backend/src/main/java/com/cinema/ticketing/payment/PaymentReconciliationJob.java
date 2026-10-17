package com.cinema.ticketing.payment;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
public class PaymentReconciliationJob {
    private static final Logger log = LoggerFactory.getLogger(PaymentReconciliationJob.class);
    private final PaymentStore store;
    private final PaymentService payments;
    public PaymentReconciliationJob(PaymentStore store, PaymentService payments) { this.store = store; this.payments = payments; }

    @Scheduled(fixedDelayString = "${payment.reconcile-delay-ms:15000}", initialDelayString = "${payment.reconcile-initial-delay-ms:60000}")
    public void run() {
        for (long id : store.pendingPayments()) {
            try { payments.reconcile(id); }
            catch (RuntimeException exception) { log.warn("支付补偿暂未完成，支付记录 {}", id); }
        }
        for (long id : store.pendingRefunds()) {
            try { payments.reconcileRefund(id); }
            catch (RuntimeException exception) { log.warn("退款补偿暂未完成，退款记录 {}", id); }
        }
    }
}
