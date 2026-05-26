package com.intp.study.ppt.service;

import com.intp.study.common.tenant.CurrentUserProvider;
import com.intp.study.ppt.dto.ImportDeckResponse;
import org.apache.pdfbox.Loader;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.rendering.ImageType;
import org.apache.pdfbox.rendering.PDFRenderer;
import org.apache.pdfbox.text.PDFTextStripper;
import org.apache.poi.xslf.usermodel.XMLSlideShow;
import org.apache.poi.xslf.usermodel.XSLFShape;
import org.apache.poi.xslf.usermodel.XSLFSlide;
import org.apache.poi.xslf.usermodel.XSLFTextShape;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.SecureRandom;
import java.sql.PreparedStatement;
import java.sql.Statement;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.Locale;
import java.util.Objects;

@Service
public class PptImportService {
    private static final long DEFAULT_MAX_UPLOAD_BYTES = 200L * 1024L * 1024L;

    private final JdbcTemplate jdbcTemplate;
    private final CurrentUserProvider currentUserProvider;
    private final Path storageRoot;
    private final SecureRandom secureRandom = new SecureRandom();

    public PptImportService(
            JdbcTemplate jdbcTemplate,
            CurrentUserProvider currentUserProvider,
            @Value("${intp.storage.root:data}") String storageRoot
    ) {
        this.jdbcTemplate = jdbcTemplate;
        this.currentUserProvider = currentUserProvider;
        this.storageRoot = Path.of(storageRoot).toAbsolutePath().normalize();
    }

    @Transactional
    public ImportDeckResponse importDeck(MultipartFile file, String subject, String title) {
        long userId = currentUserProvider.requireUserId();
        if (file == null || file.isEmpty()) {
            throw new IllegalArgumentException("上传文件不能为空。");
        }
        long size = file.getSize();
        if (size <= 0 || size > DEFAULT_MAX_UPLOAD_BYTES) {
            throw new IllegalArgumentException("上传文件大小超出限制。");
        }
        String original = file.getOriginalFilename() == null ? "deck" : file.getOriginalFilename();
        String suffix = suffix(original);
        if (!".pdf".equals(suffix) && !".pptx".equals(suffix)) {
            throw new IllegalArgumentException("仅支持 PPTX 或 PDF 文件。");
        }
        ensureQuota(userId, size);
        try {
            Path userDir = storageRoot.resolve("users").resolve(String.valueOf(userId)).resolve("decks").resolve(randomId()).normalize();
            Files.createDirectories(userDir);
            String safeName = safeStem(original) + suffix;
            Path target = userDir.resolve(safeName).normalize();
            if (!target.startsWith(storageRoot)) {
                throw new IllegalArgumentException("非法文件路径。");
            }
            file.transferTo(target);
            List<ImportedSlide> slides = ".pdf".equals(suffix)
                    ? extractPdf(target, userDir.resolve("page_images"))
                    : extractPptx(target);
            if (slides.isEmpty()) {
                slides = List.of(new ImportedSlide(1, suffix.equals(".pdf") ? "PDF 第 1 页" : "PPT 第 1 页", "未提取到可用文字。", "source=" + suffix.substring(1), ""));
            }
            long deckId = createDeck(userId, safeName, defaultString(title, safeStem(original)), defaultString(subject), target, slides.size());
            createSlides(userId, deckId, slides);
            return new ImportDeckResponse(deckId, defaultString(title, safeStem(original)), slides.size(), "已导入");
        } catch (Exception ex) {
            throw new IllegalArgumentException("PPT/PDF 导入失败：" + ex.getMessage(), ex);
        }
    }

    private long createDeck(long userId, String filename, String title, String subject, Path target, int slideCount) {
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbcTemplate.update(connection -> {
            PreparedStatement ps = connection.prepareStatement("""
                    INSERT INTO ppt_decks (user_id, filename, title, subject, file_path, slide_count, status)
                    VALUES (?, ?, ?, ?, ?, ?, '待整理')
                    """, Statement.RETURN_GENERATED_KEYS);
            ps.setLong(1, userId);
            ps.setString(2, filename);
            ps.setString(3, title);
            ps.setString(4, subject);
            ps.setString(5, storageRoot.relativize(target.toAbsolutePath().normalize()).toString());
            ps.setInt(6, slideCount);
            return ps;
        }, keyHolder);
        return Objects.requireNonNull(keyHolder.getKey()).longValue();
    }

    private void createSlides(long userId, long deckId, List<ImportedSlide> slides) {
        jdbcTemplate.batchUpdate("""
                INSERT INTO ppt_slides (user_id, deck_id, slide_number, title, slide_text, notes, image_path)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, slides, 100, (ps, slide) -> {
            ps.setLong(1, userId);
            ps.setLong(2, deckId);
            ps.setInt(3, slide.slideNumber());
            ps.setString(4, slide.title());
            ps.setString(5, slide.text());
            ps.setString(6, slide.notes());
            ps.setString(7, slide.imagePath());
        });
    }

    private List<ImportedSlide> extractPdf(Path path, Path imageDir) throws Exception {
        Files.createDirectories(imageDir);
        try (PDDocument document = Loader.loadPDF(path.toFile())) {
            if (document.isEncrypted()) {
                throw new IllegalArgumentException("暂不支持加密 PDF。");
            }
            PDFTextStripper stripper = new PDFTextStripper();
            PDFRenderer renderer = new PDFRenderer(document);
            List<ImportedSlide> slides = new ArrayList<>();
            for (int i = 1; i <= document.getNumberOfPages(); i++) {
                stripper.setStartPage(i);
                stripper.setEndPage(i);
                String text = defaultString(stripper.getText(document));
                String title = firstLine(text, "PDF 第 " + i + " 页");
                Path imagePath = imageDir.resolve("page_%03d.png".formatted(i));
                BufferedImage image = renderer.renderImageWithDPI(i - 1, 144, ImageType.RGB);
                ImageIO.write(image, "png", imagePath.toFile());
                slides.add(new ImportedSlide(i, title, text, "source=pdf", storageRoot.relativize(imagePath.toAbsolutePath().normalize()).toString()));
            }
            return slides;
        }
    }

    private List<ImportedSlide> extractPptx(Path path) throws Exception {
        try (InputStream input = Files.newInputStream(path);
             XMLSlideShow show = new XMLSlideShow(input)) {
            List<ImportedSlide> slides = new ArrayList<>();
            int number = 1;
            for (XSLFSlide slide : show.getSlides()) {
                List<String> lines = new ArrayList<>();
                for (XSLFShape shape : slide.getShapes()) {
                    if (shape instanceof XSLFTextShape textShape) {
                        String text = defaultString(textShape.getText());
                        if (!text.isBlank()) {
                            for (String line : text.split("\\R")) {
                                if (!line.strip().isBlank()) {
                                    lines.add(line.strip());
                                }
                            }
                        }
                    }
                }
                String text = String.join("\n", lines);
                slides.add(new ImportedSlide(number, firstLine(text, "PPT 第 " + number + " 页"), text, "source=pptx", ""));
                number++;
            }
            return slides;
        }
    }

    private void ensureQuota(long userId, long uploadSize) {
        Long quota = jdbcTemplate.queryForObject("SELECT upload_quota_bytes FROM users WHERE id = ?", Long.class, userId);
        long used = directorySize(storageRoot.resolve("users").resolve(String.valueOf(userId)));
        if (quota != null && quota > 0 && used + uploadSize > quota) {
            throw new IllegalArgumentException("上传失败：已超过当前账户的上传容量配额。");
        }
    }

    private long directorySize(Path path) {
        if (!Files.exists(path)) {
            return 0;
        }
        try (var stream = Files.walk(path)) {
            return stream.filter(Files::isRegularFile).mapToLong(item -> {
                try {
                    return Files.size(item);
                } catch (Exception ignored) {
                    return 0;
                }
            }).sum();
        } catch (Exception ignored) {
            return 0;
        }
    }

    private String randomId() {
        byte[] bytes = new byte[12];
        secureRandom.nextBytes(bytes);
        return DateTimeFormatter.ofPattern("yyyyMMddHHmmss").format(LocalDateTime.now()) + "-" + HexFormat.of().formatHex(bytes);
    }

    private String suffix(String filename) {
        int index = filename.lastIndexOf('.');
        return index < 0 ? "" : filename.substring(index).toLowerCase(Locale.ROOT);
    }

    private String safeStem(String filename) {
        String name = filename;
        int slash = Math.max(name.lastIndexOf('/'), name.lastIndexOf('\\'));
        if (slash >= 0) {
            name = name.substring(slash + 1);
        }
        int dot = name.lastIndexOf('.');
        if (dot > 0) {
            name = name.substring(0, dot);
        }
        String safe = name.replaceAll("[^0-9A-Za-z\\u4e00-\\u9fff._-]+", "_").replaceAll("^[._-]+|[._-]+$", "");
        return safe.isBlank() ? "deck" : safe;
    }

    private String defaultString(String value) {
        return value == null ? "" : value.strip();
    }

    private String defaultString(String value, String fallback) {
        String text = defaultString(value);
        return text.isBlank() ? fallback : text;
    }

    private String firstLine(String text, String fallback) {
        for (String line : defaultString(text).split("\\R")) {
            String clean = line.strip();
            if (!clean.isBlank()) {
                return clean.length() > 80 ? clean.substring(0, 80) : clean;
            }
        }
        return fallback;
    }

    private record ImportedSlide(int slideNumber, String title, String text, String notes, String imagePath) {
    }
}
