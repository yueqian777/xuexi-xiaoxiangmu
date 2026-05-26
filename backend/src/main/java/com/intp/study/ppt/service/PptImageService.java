package com.intp.study.ppt.service;

import com.intp.study.common.error.ResourceNotFoundException;
import com.intp.study.ppt.dto.SlideDto;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.Resource;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Optional;

@Service
public class PptImageService {
    private final PptDeckQueryService pptDeckQueryService;
    private final Path storageRoot;

    public PptImageService(
            PptDeckQueryService pptDeckQueryService,
            @Value("${intp.storage.root:data}") String storageRoot
    ) {
        this.pptDeckQueryService = pptDeckQueryService;
        this.storageRoot = Path.of(storageRoot).toAbsolutePath().normalize();
    }

    public ImageResource loadSlideImage(long deckId, long slideId) {
        SlideDto slide = pptDeckQueryService.findSlideForCurrentUser(deckId, slideId)
                .orElseThrow(() -> new ResourceNotFoundException("PPT slide not found."));
        if (slide.imagePath() == null || slide.imagePath().isBlank()) {
            throw new ResourceNotFoundException("PPT slide image not found.");
        }
        Path path = resolveImagePath(slide.imagePath());
        if (!Files.isRegularFile(path)) {
            throw new ResourceNotFoundException("PPT slide image not found.");
        }
        MediaType mediaType = mediaType(path)
                .orElseThrow(() -> new ResourceNotFoundException("PPT slide image not found."));
        return new ImageResource(new FileSystemResource(path), mediaType);
    }

    private Path resolveImagePath(String rawPath) {
        try {
            Path path = Path.of(rawPath);
            Path candidate = path.isAbsolute()
                    ? path.toRealPath()
                    : storageRoot.resolve(path).normalize().toRealPath();
            Path root = storageRoot.toRealPath();
            if (!candidate.startsWith(root)) {
                throw new ResourceNotFoundException("PPT slide image not found.");
            }
            return candidate;
        } catch (IOException | RuntimeException ex) {
            if (ex instanceof ResourceNotFoundException notFound) {
                throw notFound;
            }
            throw new ResourceNotFoundException("PPT slide image not found.");
        }
    }

    private Optional<MediaType> mediaType(Path path) {
        String filename = path.getFileName().toString().toLowerCase();
        if (filename.endsWith(".png")) {
            return Optional.of(MediaType.IMAGE_PNG);
        }
        if (filename.endsWith(".jpg") || filename.endsWith(".jpeg")) {
            return Optional.of(MediaType.IMAGE_JPEG);
        }
        if (filename.endsWith(".webp")) {
            return Optional.of(MediaType.parseMediaType("image/webp"));
        }
        return Optional.empty();
    }

    public record ImageResource(Resource resource, MediaType mediaType) {
    }
}
