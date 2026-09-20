package com.cinema.ticketing.common;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockFilterChain;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class RateLimitFilterTest {

    @Test
    void ignoresForgedForwardedForHeader() throws Exception {
        RateLimitService rateLimitService = mock(RateLimitService.class);
        when(rateLimitService.allow("10.0.0.7", 120, 60)).thenReturn(true);
        RateLimitFilter filter = new RateLimitFilter(rateLimitService, new ObjectMapper(), 120, "cinema-nginx");
        MockHttpServletRequest request = request("10.0.0.7", "9.9.9.9", null, "/api/movies");

        filter.doFilter(request, new MockHttpServletResponse(), new MockFilterChain());

        verify(rateLimitService).allow(eq("10.0.0.7"), eq(120), eq(60));
    }

    @Test
    void acceptsRealIpOnlyFromTrustedProxyMarker() throws Exception {
        RateLimitService rateLimitService = mock(RateLimitService.class);
        when(rateLimitService.allow("192.168.1.20", 120, 60)).thenReturn(true);
        RateLimitFilter filter = new RateLimitFilter(rateLimitService, new ObjectMapper(), 120, "cinema-nginx");
        MockHttpServletRequest request = request("172.20.0.3", "spoofed", "cinema-nginx", "/api/movies");
        request.addHeader("X-Real-IP", "192.168.1.20");

        filter.doFilter(request, new MockHttpServletResponse(), new MockFilterChain());

        verify(rateLimitService).allow(eq("192.168.1.20"), eq(120), eq(60));
    }

    private MockHttpServletRequest request(String remoteAddress, String forwardedFor,
                                           String trustedProxy, String path) {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setRemoteAddr(remoteAddress);
        request.setRequestURI(path);
        request.addHeader("X-Forwarded-For", forwardedFor);
        if (trustedProxy != null) {
            request.addHeader("X-Trusted-Proxy", trustedProxy);
        }
        return request;
    }
}
