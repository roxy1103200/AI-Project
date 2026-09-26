package com.cinema.ticketing.service;

import com.cinema.ticketing.common.BusinessException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.attribute.FileTime;
import java.util.List;

@Service
public class MoviePosterService {

    private static final Logger log = LoggerFactory.getLogger(MoviePosterService.class);
    private static final long MAX_IMAGE_BYTES = 5L * 1024 * 1024;
    private static final List<String> EXTENSIONS = List.of("jpg", "png", "webp");

    private final JdbcTemplate jdbcTemplate;
    private final Path directory;

    public MoviePosterService(JdbcTemplate jdbcTemplate,
                              @Value("${media.movie-image-directory:../图片}") String imageDirectory) {
        this.jdbcTemplate = jdbcTemplate;
        this.directory = Path.of(imageDirectory).toAbsolutePath().normalize();
        try {
            Files.createDirectories(directory);
        } catch (IOException exception) {
            throw new IllegalStateException("无法创建影片图片目录: " + directory, exception);
        }
    }

    public String save(long movieId, MultipartFile file) {
        requireMovie(movieId);
        if (file == null || file.isEmpty() || file.getSize() > MAX_IMAGE_BYTES) {
            throw new BusinessException(400, "请选择不超过 5 MB 的图片");
        }

        Path temporary = null;
        try {
            byte[] bytes = file.getBytes();
            if (bytes.length == 0 || bytes.length > MAX_IMAGE_BYTES) {
                throw new BusinessException(400, "请选择不超过 5 MB 的图片");
            }
            String extension = detectExtension(bytes);
            Path target = pathFor(movieId, extension);
            temporary = Files.createTempFile(directory, "movie-" + movieId + "-", ".upload");
            Files.write(temporary, bytes);
            try {
                Files.move(temporary, target, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
            } catch (AtomicMoveNotSupportedException exception) {
                Files.move(temporary, target, StandardCopyOption.REPLACE_EXISTING);
            }
            for (String otherExtension : EXTENSIONS) {
                if (!otherExtension.equals(extension)) {
                    try {
                        Files.deleteIfExists(pathFor(movieId, otherExtension));
                    } catch (IOException cleanupFailure) {
                        log.warn("新图片已保存，但旧图片清理失败，影片 ID: {}", movieId, cleanupFailure);
                    }
                }
            }
            return "/api/movies/" + movieId + "/poster";
        } catch (IOException exception) {
            log.error("保存影片图片失败，影片 ID: {}", movieId, exception);
            throw new BusinessException(500, "影片图片保存失败");
        } finally {
            if (temporary != null) {
                try {
                    Files.deleteIfExists(temporary);
                } catch (IOException exception) {
                    log.warn("清理临时影片图片失败: {}", temporary, exception);
                }
            }
        }
    }

    public Path find(long movieId) {
        requireMovie(movieId);
        Path latest = null;
        FileTime latestModified = FileTime.fromMillis(Long.MIN_VALUE);
        for (String extension : EXTENSIONS) {
            Path path = pathFor(movieId, extension);
            if (Files.isRegularFile(path)) {
                try {
                    FileTime modified = Files.getLastModifiedTime(path);
                    if (modified.compareTo(latestModified) > 0) {
                        latest = path;
                        latestModified = modified;
                    }
                } catch (IOException exception) {
                    throw new BusinessException(500, "影片图片读取失败");
                }
            }
        }
        if (latest == null) {
            throw new BusinessException(404, "影片图片不存在");
        }
        return latest;
    }

    public void delete(long movieId) {
        requireMovie(movieId);
        try {
            deleteFiles(movieId);
        } catch (IOException exception) {
            log.error("删除影片图片失败，影片 ID: {}", movieId, exception);
            throw new BusinessException(500, "影片图片删除失败");
        }
    }

    public void removeAfterMovieDeleted(long movieId) {
        try {
            deleteFiles(movieId);
        } catch (IOException exception) {
            log.warn("影片已删除，但图片清理失败，影片 ID: {}", movieId, exception);
        }
    }

    private void deleteFiles(long movieId) throws IOException {
        for (String extension : EXTENSIONS) {
            Files.deleteIfExists(pathFor(movieId, extension));
        }
    }

    private void requireMovie(long movieId) {
        if (movieId <= 0 || jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM movie WHERE id = ?", Integer.class, movieId) == 0) {
            throw new BusinessException(404, "影片不存在");
        }
    }

    private Path pathFor(long movieId, String extension) {
        return directory.resolve("movie-" + movieId + "." + extension);
    }

    private String detectExtension(byte[] bytes) {
        if (bytes.length >= 3 && (bytes[0] & 0xff) == 0xff
                && (bytes[1] & 0xff) == 0xd8 && (bytes[2] & 0xff) == 0xff) {
            return "jpg";
        }
        if (bytes.length >= 8 && (bytes[0] & 0xff) == 0x89 && bytes[1] == 'P'
                && bytes[2] == 'N' && bytes[3] == 'G' && (bytes[4] & 0xff) == 0x0d
                && (bytes[5] & 0xff) == 0x0a && (bytes[6] & 0xff) == 0x1a
                && (bytes[7] & 0xff) == 0x0a) {
            return "png";
        }
        if (bytes.length >= 12 && bytes[0] == 'R' && bytes[1] == 'I'
                && bytes[2] == 'F' && bytes[3] == 'F' && bytes[8] == 'W'
                && bytes[9] == 'E' && bytes[10] == 'B' && bytes[11] == 'P') {
            return "webp";
        }
        throw new BusinessException(400, "仅支持 JPG、PNG 或 WebP 图片");
    }
}
