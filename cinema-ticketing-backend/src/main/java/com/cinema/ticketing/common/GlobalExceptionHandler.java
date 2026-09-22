package com.cinema.ticketing.common;

import jakarta.validation.ConstraintViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.servlet.resource.NoResourceFoundException;

@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    @ExceptionHandler(BusinessException.class)
    public ResponseEntity<ApiResponse<Void>> handleBusinessException(BusinessException exception) {
        return ResponseEntity.status(statusOf(exception.getCode()))
                .body(ApiResponse.failure(exception.getCode(), exception.getMessage()));
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ApiResponse<Void>> handleMethodArgumentNotValid(MethodArgumentNotValidException exception) {
        String message = exception.getBindingResult().getFieldErrors().stream()
                .findFirst()
                .map(error -> error.getField() + ": " + error.getDefaultMessage())
                .orElse("请求参数校验失败");
        return ResponseEntity.badRequest().body(ApiResponse.failure(HttpStatus.BAD_REQUEST.value(), message));
    }

    @ExceptionHandler(ConstraintViolationException.class)
    public ResponseEntity<ApiResponse<Void>> handleConstraintViolation(ConstraintViolationException exception) {
        return ResponseEntity.badRequest().body(ApiResponse.failure(HttpStatus.BAD_REQUEST.value(), exception.getMessage()));
    }

    /**
     * 静态资源找不到（访问 /、/favicon.ico 等），语义是 404，不该落到下面 Exception 兜底里变成 500。
     */
    @ExceptionHandler(NoResourceFoundException.class)
    public ResponseEntity<ApiResponse<Void>> handleNoResourceFound(NoResourceFoundException exception) {
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(ApiResponse.failure(HttpStatus.NOT_FOUND.value(), "接口不存在: /" + exception.getResourcePath()));
    }

    /**
     * 请求体解析失败（非法 JSON、非 UTF-8 字节等），语义是客户端错误 400。
     * 典型触发：Git Bash 里用 curl -d '{"k":"中文"}'，参数传给原生 curl.exe 时会被转成 GBK。
     */
    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ResponseEntity<ApiResponse<Void>> handleHttpMessageNotReadable(HttpMessageNotReadableException exception) {
        log.warn("请求体解析失败: {}", exception.getMessage());
        return ResponseEntity.badRequest()
                .body(ApiResponse.failure(HttpStatus.BAD_REQUEST.value(), "请求体格式错误，请确认是合法 JSON 且为 UTF-8 编码"));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ApiResponse<Void>> handleUnexpectedException(Exception exception) {
        log.error("Unhandled request exception", exception);
        return ResponseEntity.internalServerError()
                .body(ApiResponse.failure(HttpStatus.INTERNAL_SERVER_ERROR.value(), "服务器内部错误"));
    }

    private HttpStatus statusOf(int code) {
        try {
            return HttpStatus.valueOf(code);
        } catch (IllegalArgumentException ignored) {
            return HttpStatus.INTERNAL_SERVER_ERROR;
        }
    }
}
