package com.cinema.ticketing.common;

import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseEntity;

import static org.junit.jupiter.api.Assertions.assertEquals;

class GlobalExceptionHandlerTest {

    @Test
    void businessExceptionUsesHttpStatusCode() {
        GlobalExceptionHandler handler = new GlobalExceptionHandler();

        ResponseEntity<ApiResponse<Void>> response = handler.handleBusinessException(
                new BusinessException(409, "订单状态冲突"));

        assertEquals(409, response.getStatusCode().value());
        assertEquals(409, response.getBody().code());
    }
}
