package com.cinema.ticketing.ai;

import com.cinema.ticketing.auth.AuthService;
import com.cinema.ticketing.common.ApiResponse;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

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
                                    @Valid @RequestBody ChatRequest request) {
        long userId = authService.requireUserId(token);
        return ApiResponse.success(aiGatewayService.chat(userId,
                new AiGatewayService.ChatRequest(request.sessionId(), request.question()), false));
    }

    @PostMapping(value = "/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public ResponseEntity<String> stream(@RequestHeader("X-Auth-Token") String token,
                                         @Valid @RequestBody ChatRequest request) {
        long userId = authService.requireUserId(token);
        return ResponseEntity.ok()
                .contentType(MediaType.TEXT_EVENT_STREAM)
                .body(aiGatewayService.chat(userId,
                        new AiGatewayService.ChatRequest(request.sessionId(), request.question()), true));
    }

    public record ChatRequest(@NotBlank String sessionId, @NotBlank String question) {
    }
}
