package com.cinema.ticketing.ai;

import com.cinema.ticketing.common.BusinessException;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;
import org.springframework.util.StreamUtils;

import java.io.IOException;
import java.util.Map;

@Service
public class AiGatewayService {

    private final RestClient restClient;
    private final String internalToken;

    public AiGatewayService(@Value("${ai.service-url}") String serviceUrl,
                            @Value("${ai.internal-token}") String internalToken) {
        this.restClient = RestClient.builder()
                .requestFactory(new SimpleClientHttpRequestFactory())
                .baseUrl(serviceUrl)
                .build();
        this.internalToken = internalToken;
    }

    public StreamingResponseBody stream(long userId, ChatRequest request) {
        return outputStream -> {
            try {
                restClient.post()
                        .uri("/ai/stream")
                        .contentType(MediaType.APPLICATION_JSON)
                        .header("X-Internal-Token", internalToken)
                        .body(Map.of("user_id", userId, "session_id", request.sessionId(),
                                "question", request.question()))
                        .exchange((clientRequest, clientResponse) -> {
                            StreamUtils.copy(clientResponse.getBody(), outputStream);
                            outputStream.flush();
                            return null;
                        });
            } catch (RestClientException exception) {
                throw new IOException("AI 流式服务暂时不可用", exception);
            }
        };
    }

    public String chat(long userId, ChatRequest request) {
        try {
            return restClient.post()
                    .uri("/ai/chat")
                    .contentType(MediaType.APPLICATION_JSON)
                    .header("X-Internal-Token", internalToken)
                    .body(Map.of("user_id", userId, "session_id", request.sessionId(),
                            "question", request.question()))
                    .retrieve()
                    .body(String.class);
        } catch (RestClientException exception) {
            throw new BusinessException(502, "AI 服务暂时不可用");
        }
    }

    public record ChatRequest(String sessionId, String question) {
    }
}
