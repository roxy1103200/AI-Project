package com.cinema.ticketing.payment;

import com.alipay.api.AlipayApiException;
import com.alipay.api.AlipayClient;
import com.alipay.api.AlipayResponse;
import com.alipay.api.DefaultAlipayClient;
import com.alipay.api.domain.*;
import com.alipay.api.request.*;
import com.alipay.api.internal.util.AlipaySignature;
import org.springframework.stereotype.Component;
import org.springframework.web.util.UriComponentsBuilder;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Map;

@Component
public class AlipaySandboxChannel implements PaymentChannel {
    private static final DateTimeFormatter TIME = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
    private final PaymentProperties properties;
    private volatile AlipayClient client;

    public AlipaySandboxChannel(PaymentProperties properties) { this.properties = properties; }

    private AlipayClient client(PaymentStore.Payment payment) {
        if (!payment.appId().equals(properties.getAlipay().getAppId())
                || !payment.sellerId().equals(properties.getAlipay().getSellerId())
                || !payment.environment().equals(properties.getEnvironment())) throw new Unavailable("CONFIG_MISMATCH");
        if (client == null) synchronized (this) {
            if (client == null) {
                properties.requireChannelConfiguration();
                var config = properties.getAlipay();
                var sdk = new DefaultAlipayClient(config.getGatewayUrl(), config.getAppId(),
                        properties.readKey(config.getPrivateKeyFile()), "json", "UTF-8",
                        properties.readKey(config.getAlipayPublicKeyFile()), "RSA2");
                sdk.setConnectTimeout(3000);
                sdk.setReadTimeout(6000);
                client = sdk;
            }
        }
        return client;
    }

    @Override
    public String cashier(PaymentStore.Payment payment) {
        var model = new AlipayTradePagePayModel();
        model.setOutTradeNo(payment.paymentNo());
        model.setTotalAmount(payment.amount().toPlainString());
        model.setSubject("影院电影票订单 " + payment.orderNo());
        model.setProductCode("FAST_INSTANT_TRADE_PAY");
        model.setTimeExpire(payment.expireAt().format(TIME));
        var request = new AlipayTradePagePayRequest();
        request.setBizModel(model);
        request.setNotifyUrl(properties.getAlipay().getNotifyUrl());
        request.setReturnUrl(UriComponentsBuilder.fromUriString(properties.getAlipay().getReturnUrl())
                .queryParam("orderNo", payment.orderNo()).build().encode().toUriString());
        try { return client(payment).pageExecute(request, "POST").getBody(); }
        catch (AlipayApiException exception) { throw new Unavailable("CHANNEL_UNAVAILABLE"); }
    }

    @Override
    public Trade query(PaymentStore.Payment payment) {
        var model = new AlipayTradeQueryModel();
        model.setOutTradeNo(payment.paymentNo());
        var request = new AlipayTradeQueryRequest();
        request.setBizModel(model);
        try {
            var response = client(payment).execute(request);
            if ("ACQ.TRADE_NOT_EXIST".equals(response.getSubCode())) return new Trade("NOT_FOUND", payment.paymentNo(), null, null, null);
            requireSuccess(response);
            LocalDateTime paid = response.getSendPayDate() == null ? null
                    : LocalDateTime.ofInstant(response.getSendPayDate().toInstant(), PaymentProperties.ZONE);
            return new Trade(response.getTradeStatus(), response.getOutTradeNo(), response.getTradeNo(),
                    new BigDecimal(response.getTotalAmount()), paid);
        } catch (AlipayApiException exception) { throw new Unavailable("CHANNEL_UNAVAILABLE"); }
    }

    @Override
    public String close(PaymentStore.Payment payment) {
        var model = new AlipayTradeCloseModel();
        model.setOutTradeNo(payment.paymentNo());
        var request = new AlipayTradeCloseRequest();
        request.setBizModel(model);
        try {
            var response = client(payment).execute(request);
            requireSuccess(response);
            if (!payment.paymentNo().equals(response.getOutTradeNo())) throw new Unavailable("CHANNEL_RESULT_MISMATCH");
            return "CLOSED";
        } catch (AlipayApiException exception) { throw new Unavailable("CHANNEL_UNAVAILABLE"); }
    }

    @Override
    public boolean refund(PaymentStore.Payment payment, PaymentStore.Refund refund) {
        var model = new AlipayTradeRefundModel();
        model.setOutTradeNo(payment.paymentNo());
        model.setOutRequestNo(refund.refundNo());
        model.setRefundAmount(refund.amount().toPlainString());
        model.setRefundReason(refund.reason());
        var request = new AlipayTradeRefundRequest();
        request.setBizModel(model);
        try {
            var response = client(payment).execute(request);
            requireSuccess(response);
            if (!payment.paymentNo().equals(response.getOutTradeNo()) || !payment.tradeNo().equals(response.getTradeNo())
                    || response.getRefundFee() == null || refund.amount().compareTo(new BigDecimal(response.getRefundFee())) != 0) {
                throw new Unavailable("CHANNEL_RESULT_MISMATCH");
            }
            return "Y".equals(response.getFundChange());
        } catch (AlipayApiException exception) { throw new Unavailable("CHANNEL_UNAVAILABLE"); }
    }

    @Override
    public boolean refundSucceeded(PaymentStore.Payment payment, PaymentStore.Refund refund) {
        var model = new AlipayTradeFastpayRefundQueryModel();
        model.setOutTradeNo(payment.paymentNo());
        model.setOutRequestNo(refund.refundNo());
        var request = new AlipayTradeFastpayRefundQueryRequest();
        request.setBizModel(model);
        try {
            var response = client(payment).execute(request);
            if ("ACQ.TRADE_NOT_EXIST".equals(response.getSubCode()) || "ACQ.REFUND_NOT_EXIST".equals(response.getSubCode())) return false;
            requireSuccess(response);
            if (!"REFUND_SUCCESS".equals(response.getRefundStatus())) return false;
            if (!payment.paymentNo().equals(response.getOutTradeNo()) || !refund.refundNo().equals(response.getOutRequestNo())
                    || !payment.tradeNo().equals(response.getTradeNo()) || response.getRefundAmount() == null
                    || refund.amount().compareTo(new BigDecimal(response.getRefundAmount())) != 0) throw new Unavailable("CHANNEL_RESULT_MISMATCH");
            return true;
        } catch (AlipayApiException exception) { throw new Unavailable("CHANNEL_UNAVAILABLE"); }
    }

    @Override
    public boolean verify(Map<String, String> parameters) {
        if (!"RSA2".equals(parameters.get("sign_type"))) return false;
        try {
            return AlipaySignature.rsaCheckV1(parameters,
                    properties.readKey(properties.getAlipay().getAlipayPublicKeyFile()), "UTF-8", "RSA2");
        } catch (AlipayApiException exception) { return false; }
    }

    private void requireSuccess(AlipayResponse response) {
        if (!response.isSuccess()) {
            String code = response.getSubCode() == null ? response.getCode() : response.getSubCode();
            throw new Unavailable(code != null && code.matches("[A-Za-z0-9_.]{1,64}") ? code : "CHANNEL_REJECTED");
        }
    }
}
