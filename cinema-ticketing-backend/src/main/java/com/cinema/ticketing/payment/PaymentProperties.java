package com.cinema.ticketing.payment;

import com.cinema.ticketing.common.BusinessException;
import jakarta.annotation.PostConstruct;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;
import java.net.URI;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.ZoneId;
import java.util.Set;

@Component
@ConfigurationProperties(prefix = "payment")
public class PaymentProperties {
    public static final ZoneId ZONE = ZoneId.of("Asia/Shanghai");
    private boolean enabled;
    private boolean mockEnabled;
    private boolean initializeSchema = true;
    private String environment = "SANDBOX";
    private Alipay alipay = new Alipay();

    @PostConstruct
    public void validate() {
        if (enabled) {
            if (mockEnabled) throw new IllegalStateException("沙箱支付与模拟支付不能同时启用");
            requireChannelConfiguration();
        }
    }

    public void requireEnabled() {
        if (!enabled) throw new BusinessException(503, "支付宝沙箱支付尚未配置，请联系管理员");
    }

    public void requireChannelConfiguration() {
        if (!"SANDBOX".equals(environment)) throw new IllegalStateException("当前支付模块仅开放支付宝沙箱");
        var allowed = Set.of("https://openapi-sandbox.dl.alipaydev.com/gateway.do", "https://openapi.alipaydev.com/gateway.do");
        if (!allowed.contains(alipay.gatewayUrl)) throw new IllegalStateException("支付宝沙箱网关配置不正确");
        if (!alipay.appId.matches("[0-9]{16}")) throw new IllegalStateException("ALIPAY_APP_ID 必须是沙箱页面提供的16位数字 APPID，不能包含空格或制表符");
        if (!alipay.sellerId.matches("2088[0-9]{12}")) throw new IllegalStateException("ALIPAY_SELLER_ID 必须是以2088开头的16位沙箱商户 UID");
        publicHttps(alipay.notifyUrl, "notify-url");
        URI result = URI.create(alipay.returnUrl);
        if (result.getHost() == null || result.getUserInfo() != null || result.getFragment() != null
                || result.getQuery() != null || !result.getPath().equals("/payment/result")
                || (!"https".equals(result.getScheme()) && !("http".equals(result.getScheme())
                && Set.of("localhost", "127.0.0.1").contains(result.getHost())))) {
            throw new IllegalStateException("支付回跳地址必须为 HTTPS 或本机开发地址");
        }
        try {
            var factory = java.security.KeyFactory.getInstance("RSA");
            var privateKey = applicationPrivateKey(factory);
            var publicKey = alipayPublicKey(factory);
            if (((java.security.interfaces.RSAKey) privateKey).getModulus()
                    .equals(((java.security.interfaces.RSAKey) publicKey).getModulus())) {
                throw new IllegalStateException("支付宝公钥文件中填入了应用公钥，请从沙箱应用页面复制标为“支付宝公钥”的内容");
            }
        } catch (java.security.NoSuchAlgorithmException exception) {
            throw new IllegalStateException("当前 Java 运行环境不支持 RSA 密钥");
        }
    }

    private java.security.PrivateKey applicationPrivateKey(java.security.KeyFactory factory) {
        try {
            byte[] encoded = java.util.Base64.getDecoder().decode(readKey(alipay.privateKeyFile));
            return factory.generatePrivate(new java.security.spec.PKCS8EncodedKeySpec(encoded));
        } catch (java.security.spec.InvalidKeySpecException | IllegalArgumentException exception) {
            throw new IllegalStateException("应用私钥文件内容不正确：请将沙箱应用的 Java/PKCS8 应用私钥正文保存到 "
                    + "ALIPAY_PRIVATE_KEY_FILE 指向的文件；不要填应用公钥、支付宝公钥或说明文字");
        }
    }

    private java.security.PublicKey alipayPublicKey(java.security.KeyFactory factory) {
        try {
            byte[] encoded = java.util.Base64.getDecoder().decode(readKey(alipay.alipayPublicKeyFile));
            return factory.generatePublic(new java.security.spec.X509EncodedKeySpec(encoded));
        } catch (java.security.spec.InvalidKeySpecException | IllegalArgumentException exception) {
            throw new IllegalStateException("支付宝公钥文件内容不正确：请将沙箱页面标为“支付宝公钥”的完整正文保存到 "
                    + "ALIPAY_PUBLIC_KEY_FILE 指向的文件；不要填应用公钥、证书或说明文字");
        }
    }

    private void publicHttps(String url, String label) {
        URI uri = URI.create(url);
        if (!"https".equals(uri.getScheme()) || uri.getHost() == null || uri.getUserInfo() != null
                || Set.of("localhost", "127.0.0.1", "::1").contains(uri.getHost())) {
            throw new IllegalStateException(label + " 必须是公网 HTTPS 地址");
        }
    }

    public String readKey(String file) {
        try {
            if (file == null || file.isBlank()) throw new IllegalStateException("尚未配置支付密钥文件路径");
            if (file.length() > 1024 || file.contains("-----BEGIN") || file.matches("[A-Za-z0-9+/=\\s]{100,}")) {
                throw new IllegalStateException("_KEY_FILE 必须填写文件路径，请将密钥正文保存到本机文件后再配置路径");
            }
            String key = Files.readString(Path.of(file)).replace("\uFEFF", "")
                    .replaceAll("-----[^-]+-----", "").replaceAll("\\s", "");
            if (key.isBlank()) throw new IllegalStateException("支付密钥文件为空");
            return key;
        } catch (java.io.IOException | java.nio.file.InvalidPathException exception) {
            throw new IllegalStateException("无法读取支付密钥文件，请检查路径与权限");
        }
    }

    public boolean isEnabled() { return enabled; }
    public void setEnabled(boolean value) { enabled = value; }
    public boolean isMockEnabled() { return mockEnabled; }
    public void setMockEnabled(boolean value) { mockEnabled = value; }
    public boolean isInitializeSchema() { return initializeSchema; }
    public void setInitializeSchema(boolean value) { initializeSchema = value; }
    public String getEnvironment() { return environment; }
    public void setEnvironment(String value) { environment = value; }
    public Alipay getAlipay() { return alipay; }
    public void setAlipay(Alipay value) { alipay = value; }

    private static String clean(String value) { return value == null ? "" : value.replace("\uFEFF", "").strip(); }

    public static class Alipay {
        private String gatewayUrl = "https://openapi-sandbox.dl.alipaydev.com/gateway.do";
        private String appId = "";
        private String sellerId = "";
        private String privateKeyFile = "";
        private String alipayPublicKeyFile = "";
        private String notifyUrl = "";
        private String returnUrl = "http://localhost:5173/payment/result";
        public String getGatewayUrl() { return gatewayUrl; }
        public void setGatewayUrl(String value) { gatewayUrl = clean(value); }
        public String getAppId() { return appId; }
        public void setAppId(String value) { appId = clean(value); }
        public String getSellerId() { return sellerId; }
        public void setSellerId(String value) { sellerId = clean(value); }
        public String getPrivateKeyFile() { return privateKeyFile; }
        public void setPrivateKeyFile(String value) { privateKeyFile = clean(value); }
        public String getAlipayPublicKeyFile() { return alipayPublicKeyFile; }
        public void setAlipayPublicKeyFile(String value) { alipayPublicKeyFile = clean(value); }
        public String getNotifyUrl() { return notifyUrl; }
        public void setNotifyUrl(String value) { notifyUrl = clean(value); }
        public String getReturnUrl() { return returnUrl; }
        public void setReturnUrl(String value) { returnUrl = clean(value); }
    }
}
