package com.cinema.ticketing.config;

import com.cinema.ticketing.common.RateLimitFilter;
import com.cinema.ticketing.service.RateLimitService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class WebFilterConfiguration {

    /**
     * 显式用 {@code @Bean} 声明，而不是在 {@link RateLimitFilter} 上挂 {@code @Component}
     * 加 {@code @ConditionalOnBean}：条件注解在组件扫描阶段求值，结果取决于包的扫描顺序
     * （Spring 只保证它在自动配置类里可靠）。这里去掉条件，注册与否完全由本类是否被加载决定 ——
     * 全量上下文会加载本类，限流生效；{@code @WebMvcTest} 切片不加载用户 {@code @Configuration}，
     * 限流器自然缺席，与切片测试原本的预期一致。
     */
    @Bean
    public RateLimitFilter rateLimitFilter(RateLimitService rateLimitService, ObjectMapper objectMapper,
                                           @Value("${rate-limit.requests-per-minute:120}") int requestLimit,
                                           @Value("${rate-limit.trusted-proxy-header:cinema-nginx}") String trustedProxyHeader) {
        return new RateLimitFilter(rateLimitService, objectMapper, requestLimit, trustedProxyHeader);
    }
}
