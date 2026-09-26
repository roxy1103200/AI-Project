package com.cinema.ticketing.controller;

import com.cinema.ticketing.common.ApiResponse;
import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.service.AuthService;
import com.cinema.ticketing.service.MoviePosterService;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.Resource;
import org.springframework.http.CacheControl;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;

@RestController
@RequestMapping("/api/movies/{id}/poster")
public class MoviePosterController {

    private final MoviePosterService moviePosterService;
    private final AuthService authService;

    public MoviePosterController(MoviePosterService moviePosterService, AuthService authService) {
        this.moviePosterService = moviePosterService;
        this.authService = authService;
    }

    @GetMapping
    public ResponseEntity<Resource> get(@PathVariable long id) {
        Path poster = moviePosterService.find(id);
        String filename = poster.getFileName().toString();
        MediaType contentType = filename.endsWith(".png") ? MediaType.IMAGE_PNG
                : filename.endsWith(".webp") ? MediaType.parseMediaType("image/webp") : MediaType.IMAGE_JPEG;
        try {
            return ResponseEntity.ok()
                    .contentType(contentType)
                    .contentLength(Files.size(poster))
                    .cacheControl(CacheControl.noStore())
                    .header("X-Content-Type-Options", "nosniff")
                    .body(new FileSystemResource(poster));
        } catch (IOException exception) {
            throw new BusinessException(500, "影片图片读取失败");
        }
    }

    @PostMapping(consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ApiResponse<Map<String, String>> save(
            @PathVariable long id,
            @RequestHeader(value = "X-Auth-Token", required = false) String token,
            @RequestParam(value = "file", required = false) MultipartFile file) {
        authService.requireAdmin(token);
        return ApiResponse.success(Map.of("url", moviePosterService.save(id, file)));
    }

    @DeleteMapping
    public ApiResponse<Void> delete(
            @PathVariable long id,
            @RequestHeader(value = "X-Auth-Token", required = false) String token) {
        authService.requireAdmin(token);
        moviePosterService.delete(id);
        return ApiResponse.success(null);
    }
}
