package com.cinema.ticketing.controller;

import com.cinema.ticketing.common.ApiResponse;
import com.cinema.ticketing.dto.AiChatRequest;
import com.cinema.ticketing.service.AiGatewayService;
import com.cinema.ticketing.service.AuthService;
import jakarta.validation.Valid;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

@RestController
@RequestMapping("/api/ai")
public class AiGatewayController {

    private final AuthService authService;
    private final AiGatewayService aiGatewayService;

    public AiGatewayController(AuthService authService, AiGatewayService aiGatewayService) {
        this.authService = authService;
        this.aiGatewayService = aiGatewayService;
    }

    @PostMapping("/chat")
    public ApiResponse<String> chat(@RequestHeader("X-Auth-Token") String token,
                                    @Valid @RequestBody AiChatRequest request) {
        long userId = authService.requireUserId(token);
        return ApiResponse.success(aiGatewayService.chat(userId, request));
    }

    @PostMapping(value = "/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public ResponseEntity<StreamingResponseBody> stream(@RequestHeader("X-Auth-Token") String token,
                                         @Valid @RequestBody AiChatRequest request) {
        long userId = authService.requireUserId(token);
        return ResponseEntity.ok()
                .contentType(MediaType.TEXT_EVENT_STREAM)
                .body(aiGatewayService.stream(userId, request));
    }
}
