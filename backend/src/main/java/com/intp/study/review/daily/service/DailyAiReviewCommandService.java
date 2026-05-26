package com.intp.study.review.daily.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.intp.study.ai.dto.GenerateTextRequest;
import com.intp.study.ai.dto.GenerateTextResponse;
import com.intp.study.ai.service.ApiProviderCommandService;
import com.intp.study.common.error.ResourceNotFoundException;
import com.intp.study.common.tenant.CurrentUserProvider;
import com.intp.study.review.daily.dto.DailyAiReviewPlanDto;
import com.intp.study.review.daily.dto.EvaluateDailyAiReviewRequest;
import com.intp.study.review.daily.dto.GenerateDailyAiReviewRequest;
import com.intp.study.review.service.ReviewTaskCommandService;
import com.intp.study.review.dto.MarkReviewResultRequest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;

import java.time.LocalDate;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.Set;

@Service
public class DailyAiReviewCommandService {
    private static final int MAX_DAILY_REVIEW_QUESTIONS = 6;
    private static final int DEFAULT_DAILY_REVIEW_QUESTIONS = 5;

    private final JdbcTemplate jdbcTemplate;
    private final CurrentUserProvider currentUserProvider;
    private final ApiProviderCommandService aiService;
    private final ReviewTaskCommandService reviewTaskCommandService;
    private final DailyReviewQueryService dailyReviewQueryService;
    private final ObjectMapper objectMapper;
    private final TransactionTemplate transactionTemplate;

    public DailyAiReviewCommandService(
            JdbcTemplate jdbcTemplate,
            CurrentUserProvider currentUserProvider,
            ApiProviderCommandService aiService,
            ReviewTaskCommandService reviewTaskCommandService,
            DailyReviewQueryService dailyReviewQueryService,
            ObjectMapper objectMapper,
            TransactionTemplate transactionTemplate
    ) {
        this.jdbcTemplate = jdbcTemplate;
        this.currentUserProvider = currentUserProvider;
        this.aiService = aiService;
        this.reviewTaskCommandService = reviewTaskCommandService;
        this.dailyReviewQueryService = dailyReviewQueryService;
        this.objectMapper = objectMapper;
        this.transactionTemplate = transactionTemplate;
    }

    public DailyAiReviewPlanDto generateTodayPlan(GenerateDailyAiReviewRequest request) {
        long userId = currentUserProvider.requireUserId();
        String today = LocalDate.now().toString();
        List<ObjectNode> candidates = collectCandidates(userId, MAX_DAILY_REVIEW_QUESTIONS);
        if (candidates.isEmpty()) {
            throw new IllegalArgumentException("今天没有可生成自测题的知识点。请先创建知识卡片，或等待复习任务到期。");
        }
        int maxQuestions = Math.min(Math.min(DEFAULT_DAILY_REVIEW_QUESTIONS, MAX_DAILY_REVIEW_QUESTIONS), candidates.size());
        String candidatesJson = toJson(candidates);
        String prompt = dailyPlanPrompt(today, maxQuestions, candidatesJson);
        GenerateTextResponse response = aiService.generate(new GenerateTextRequest(
                request.providerKey(),
                request.model(),
                prompt,
                request.maxOutputTokens() == null ? 1800 : request.maxOutputTokens(),
                null,
                request.apiKey()
        ));
        ObjectNode plan = normalizePlan(loadJsonObject(response.text()), candidates, maxQuestions);
        transactionTemplate.executeWithoutResult(status ->
                saveTodayPlan(userId, today, request.providerKey(), firstNonBlank(request.model(), response.model()), plan, candidates)
        );
        return dailyReviewQueryService.findTodayAiPlanForCurrentUser()
                .orElseThrow(() -> new ResourceNotFoundException("Daily AI review plan not found."));
    }

    public ObjectNode evaluateTodayPlan(EvaluateDailyAiReviewRequest request) {
        long userId = currentUserProvider.requireUserId();
        DailyAiReviewPlanDto planRow = dailyReviewQueryService.findTodayAiPlanForCurrentUser()
                .orElseThrow(() -> new ResourceNotFoundException("Daily AI review plan not found."));
        ObjectNode plan = readObject(planRow.planJson());
        ObjectNode answers = objectMapper.createObjectNode();
        if (request.answers() != null) {
            request.answers().forEach((key, value) -> answers.put(key, value == null ? "" : value.strip()));
        }
        String prompt = dailyGradePrompt(LocalDate.now().toString(), plan.toPrettyString(), answers.toPrettyString());
        GenerateTextResponse response = aiService.generate(new GenerateTextRequest(
                request.providerKey(),
                request.model(),
                prompt,
                request.maxOutputTokens() == null ? 2200 : request.maxOutputTokens(),
                null,
                request.apiKey()
        ));
        ObjectNode evaluation = normalizeEvaluation(loadJsonObject(response.text()), plan, answers);
        return transactionTemplate.execute(status -> saveEvaluation(userId, planRow, plan, answers, evaluation));
    }

    private List<ObjectNode> collectCandidates(long userId, int limit) {
        String today = LocalDate.now().toString();
        return jdbcTemplate.query("""
                SELECT *
                FROM (
                    SELECT
                        kc.id AS knowledge_id,
                        kc.subject,
                        kc.topic,
                        kc.core_question,
                        kc.one_sentence,
                        kc.logic_or_formula,
                        kc.application,
                        kc.mastery,
                        kc.need_review,
                        kc.created_at,
                        (
                            SELECT rt.id
                            FROM review_tasks rt
                            WHERE rt.knowledge_id = kc.id
                              AND rt.user_id = kc.user_id
                              AND rt.review_date <= ?
                              AND rt.status = '待复习'
                            ORDER BY rt.review_date ASC, rt.id ASC
                            LIMIT 1
                        ) AS task_id,
                        (
                            SELECT rt.review_stage
                            FROM review_tasks rt
                            WHERE rt.knowledge_id = kc.id
                              AND rt.user_id = kc.user_id
                              AND rt.review_date <= ?
                              AND rt.status = '待复习'
                            ORDER BY rt.review_date ASC, rt.id ASC
                            LIMIT 1
                        ) AS review_stage,
                        (
                            SELECT m.cause_category
                            FROM mistakes m
                            WHERE m.user_id = kc.user_id
                              AND (m.knowledge_id = kc.id OR (m.subject = kc.subject AND m.topic = kc.topic))
                            ORDER BY m.created_at DESC, m.id DESC
                            LIMIT 1
                        ) AS last_cause
                    FROM knowledge_cards kc
                    WHERE kc.user_id = ?
                )
                WHERE task_id IS NOT NULL OR mastery < 70 OR need_review = 1
                ORDER BY
                    CASE WHEN task_id IS NOT NULL THEN 0 ELSE 1 END,
                    mastery ASC,
                    created_at DESC,
                    knowledge_id DESC
                LIMIT ?
                """, (rs, rowNum) -> {
            ObjectNode node = objectMapper.createObjectNode();
            node.put("knowledge_id", rs.getLong("knowledge_id"));
            long taskId = rs.getLong("task_id");
            if (rs.wasNull()) {
                node.putNull("task_id");
            } else {
                node.put("task_id", taskId);
            }
            node.put("subject", defaultString(rs.getString("subject")));
            node.put("topic", defaultString(rs.getString("topic")));
            node.put("core_question", defaultString(rs.getString("core_question")));
            node.put("one_sentence", defaultString(rs.getString("one_sentence")));
            node.put("logic_or_formula", clip(rs.getString("logic_or_formula"), 500));
            node.put("application", clip(rs.getString("application"), 400));
            int mastery = rs.getInt("mastery");
            node.put("mastery", mastery);
            String reviewStage = rs.getString("review_stage");
            node.put("review_stage", defaultString(reviewStage).isBlank()
                    ? (mastery < 70 ? "低掌握度重点复习" : "常规复习")
                    : reviewStage);
            node.put("last_cause", defaultString(rs.getString("last_cause")));
            return node;
        }, today, today, userId, limit);
    }

    private ObjectNode normalizePlan(ObjectNode payload, List<ObjectNode> candidates, int maxQuestions) {
        Set<Long> candidateIds = new HashSet<>();
        Map<Long, ObjectNode> byId = new HashMap<>();
        for (ObjectNode candidate : candidates) {
            long id = candidate.path("knowledge_id").asLong();
            candidateIds.add(id);
            byId.put(id, candidate);
        }
        ArrayNode questions = objectMapper.createArrayNode();
        JsonNode rawQuestions = payload.path("questions");
        if (rawQuestions.isArray()) {
            for (JsonNode item : rawQuestions) {
                long knowledgeId = item.path("knowledge_id").asLong(-1);
                String question = item.path("question").asText("").strip();
                if (!candidateIds.contains(knowledgeId) || question.isBlank()) {
                    continue;
                }
                ObjectNode normalized = objectMapper.createObjectNode();
                normalized.put("question_id", firstNonBlank(item.path("question_id").asText(), "q" + (questions.size() + 1)));
                normalized.put("knowledge_id", knowledgeId);
                normalized.put("topic", firstNonBlank(item.path("topic").asText(), byId.get(knowledgeId).path("topic").asText()));
                normalized.put("question_type", firstNonBlank(item.path("question_type").asText(), "概念解释题"));
                normalized.put("question", question);
                ArrayNode expected = objectMapper.createArrayNode();
                if (item.path("expected_points").isArray()) {
                    item.path("expected_points").forEach(point -> {
                        String text = point.asText("").strip();
                        if (!text.isBlank()) {
                            expected.add(text);
                        }
                    });
                }
                normalized.set("expected_points", expected);
                questions.add(normalized);
                if (questions.size() >= maxQuestions) {
                    break;
                }
            }
        }
        if (questions.isEmpty()) {
            for (int i = 0; i < Math.min(maxQuestions, candidates.size()); i++) {
                ObjectNode candidate = candidates.get(i);
                ObjectNode question = objectMapper.createObjectNode();
                question.put("question_id", "q" + (i + 1));
                question.put("knowledge_id", candidate.path("knowledge_id").asLong());
                question.put("topic", candidate.path("topic").asText());
                question.put("question_type", "概念解释题");
                question.put("question", "闭卷解释：" + candidate.path("topic").asText() + " 想解决什么核心问题？它和前面学过的哪些概念容易混淆？");
                ArrayNode expected = objectMapper.createArrayNode();
                expected.add(firstNonBlank(candidate.path("core_question").asText(), "说明核心问题"));
                expected.add(firstNonBlank(candidate.path("one_sentence").asText(), "给出一句话解释"));
                question.set("expected_points", expected);
                questions.add(question);
            }
        }
        ObjectNode normalized = objectMapper.createObjectNode();
        normalized.put("main_line", firstNonBlank(payload.path("main_line").asText(), "今天用少量问题检查到期复习和低掌握度知识点。"));
        normalized.set("questions", questions);
        return normalized;
    }

    private ObjectNode normalizeEvaluation(ObjectNode payload, ObjectNode plan, ObjectNode answers) {
        Map<String, JsonNode> questions = new HashMap<>();
        plan.path("questions").forEach(question -> questions.put(question.path("question_id").asText(), question));
        ArrayNode evaluations = objectMapper.createArrayNode();
        Set<String> seen = new HashSet<>();
        if (payload.path("evaluations").isArray()) {
            for (JsonNode item : payload.path("evaluations")) {
                String questionId = item.path("question_id").asText("");
                if (!questions.containsKey(questionId)) {
                    continue;
                }
                seen.add(questionId);
                evaluations.add(normalizeEvaluationItem(item, questions.get(questionId), item.path("score").asInt(0)));
            }
        }
        for (Map.Entry<String, JsonNode> entry : questions.entrySet()) {
            if (seen.contains(entry.getKey())) {
                continue;
            }
            String answer = answers.path(entry.getKey()).asText("").strip();
            int score = answer.isBlank() ? 0 : 50;
            ObjectNode fallback = objectMapper.createObjectNode();
            fallback.put("question_id", entry.getKey());
            fallback.put("knowledge_id", entry.getValue().path("knowledge_id").asLong());
            fallback.put("score", score);
            fallback.put("result", normalizeResult(null, score));
            fallback.put("cause_category", answer.isBlank() ? "前置知识缺失" : "概念不清");
            fallback.put("feedback", "未获得有效批改，已按回答完整度保守估计。");
            fallback.put("correct_answer", "请重新生成或手动复盘本题。");
            fallback.put("next_question", "这个知识点想解决什么核心问题？");
            evaluations.add(fallback);
        }
        ObjectNode normalized = objectMapper.createObjectNode();
        normalized.put("overall_summary", firstNonBlank(payload.path("overall_summary").asText(), "已根据本次自测更新掌握度。"));
        normalized.set("evaluations", evaluations);
        return normalized;
    }

    private ObjectNode normalizeEvaluationItem(JsonNode item, JsonNode question, int score) {
        int clampedScore = clamp(score);
        ObjectNode normalized = objectMapper.createObjectNode();
        normalized.put("question_id", question.path("question_id").asText());
        normalized.put("knowledge_id", question.path("knowledge_id").asLong());
        normalized.put("score", clampedScore);
        normalized.put("result", normalizeResult(item.path("result").asText(), clampedScore));
        normalized.put("cause_category", normalizeCause(item.path("cause_category").asText()));
        normalized.put("feedback", item.path("feedback").asText("").strip());
        normalized.put("correct_answer", item.path("correct_answer").asText("").strip());
        normalized.put("next_question", item.path("next_question").asText("").strip());
        return normalized;
    }

    private ArrayNode applyEvaluationResults(long userId, DailyAiReviewPlanDto planRow, ObjectNode plan, ObjectNode evaluation) {
        List<ObjectNode> sourceItems = readArray(planRow.sourceSnapshotJson());
        Map<Long, ObjectNode> sourceByKnowledgeId = new HashMap<>();
        for (ObjectNode source : sourceItems) {
            sourceByKnowledgeId.put(source.path("knowledge_id").asLong(), source);
        }
        Map<Long, java.util.ArrayList<JsonNode>> grouped = new HashMap<>();
        evaluation.path("evaluations").forEach(item -> grouped
                .computeIfAbsent(item.path("knowledge_id").asLong(), ignored -> new java.util.ArrayList<>())
                .add(item));
        ArrayNode updates = objectMapper.createArrayNode();
        for (Map.Entry<Long, java.util.ArrayList<JsonNode>> entry : grouped.entrySet()) {
            long knowledgeId = entry.getKey();
            int avgScore = Math.round((float) entry.getValue().stream().mapToInt(item -> item.path("score").asInt()).sum() / entry.getValue().size());
            String result = normalizeResult(null, avgScore);
            Integer before = findMastery(userId, knowledgeId);
            if (before == null) {
                continue;
            }
            ObjectNode source = sourceByKnowledgeId.get(knowledgeId);
            if (source != null && !source.path("task_id").isNull() && source.path("task_id").asLong(0) > 0) {
                reviewTaskCommandService.markResult(source.path("task_id").asLong(), new MarkReviewResultRequest(result));
            } else {
                int after = applyReviewResult(before, result);
                jdbcTemplate.update("""
                        UPDATE knowledge_cards
                        SET mastery = ?, need_review = ?
                        WHERE id = ? AND user_id = ?
                        """, after, (after < 70 || "仍然模糊".equals(result) || "完全不会".equals(result)) ? 1 : 0, knowledgeId, userId);
                if ("仍然模糊".equals(result)) {
                    createExtraReview(userId, knowledgeId, 2, "AI 追加复习：2 天后");
                } else if ("完全不会".equals(result)) {
                    createExtraReview(userId, knowledgeId, 1, "AI 重点突破：1 天后");
                }
            }
            int after = findMastery(userId, knowledgeId) == null ? before : findMastery(userId, knowledgeId);
            ObjectNode update = objectMapper.createObjectNode();
            update.put("knowledge_id", knowledgeId);
            update.put("topic", source == null ? topicForPlan(plan, knowledgeId) : source.path("topic").asText(""));
            update.put("score", avgScore);
            update.put("result", result);
            update.put("mastery_before", before);
            update.put("mastery_after", after);
            updates.add(update);
        }
        return updates;
    }

    private void saveTodayPlan(long userId, String today, String providerKey, String model, ObjectNode plan, List<ObjectNode> candidates) {
        jdbcTemplate.update("""
                INSERT INTO daily_ai_review_plans (
                    user_id, review_date, provider_key, model, plan_json, source_snapshot_json, status
                )
                VALUES (?, ?, ?, ?, ?, ?, '待回答')
                ON CONFLICT(user_id, review_date) DO UPDATE SET
                    provider_key = excluded.provider_key,
                    model = excluded.model,
                    plan_json = excluded.plan_json,
                    source_snapshot_json = excluded.source_snapshot_json,
                    answers_json = '{}',
                    evaluation_json = '',
                    status = excluded.status,
                    created_at = datetime('now', 'localtime'),
                    evaluated_at = ''
                """, userId, today, providerKey, model, plan.toString(), toJson(candidates));
    }

    private ObjectNode saveEvaluation(
            long userId,
            DailyAiReviewPlanDto planRow,
            ObjectNode plan,
            ObjectNode answers,
            ObjectNode evaluation
    ) {
        ArrayNode updates = applyEvaluationResults(userId, planRow, plan, evaluation);
        evaluation.set("mastery_updates", updates);
        jdbcTemplate.update("""
                UPDATE daily_ai_review_plans
                SET answers_json = ?,
                    evaluation_json = ?,
                    status = '已批改',
                    evaluated_at = datetime('now', 'localtime')
                WHERE id = ? AND user_id = ?
                """, answers.toString(), evaluation.toString(), planRow.id(), userId);
        return evaluation;
    }

    private String dailyPlanPrompt(String today, int maxQuestions, String candidatesJson) {
        return """
                你是我的 INTP 问题驱动学习复习教练。请根据今天需要复习的知识卡片，生成一份“轻量闭卷自测计划”。

                日期：%s
                最多题数：%d

                候选知识点 JSON：
                %s

                请只返回一个合法 JSON 对象，不要返回 Markdown，不要使用代码块。格式：
                {"main_line":"...","questions":[{"question_id":"q1","knowledge_id":1,"topic":"...","question_type":"概念解释题","question":"...","expected_points":["要点1"]}]}
                """.formatted(today, maxQuestions, candidatesJson);
    }

    private String dailyGradePrompt(String today, String planJson, String answersJson) {
        return """
                你是我的 INTP 问题驱动学习批改教练。请根据自测题、标准要点和我的回答，判断每个知识点的掌握程度，并给出精简纠错。

                日期：%s

                自测计划 JSON：
                %s

                我的回答 JSON：
                %s

                请只返回合法 JSON 对象，不要 Markdown。格式：
                {"overall_summary":"...","evaluations":[{"question_id":"q1","knowledge_id":1,"score":80,"result":"基本掌握","cause_category":"概念不清","feedback":"...","correct_answer":"...","next_question":"..."}]}
                """.formatted(today, planJson, answersJson);
    }

    private ObjectNode loadJsonObject(String rawText) {
        String text = rawText == null ? "" : rawText.strip();
        if (text.startsWith("```")) {
            text = text.replaceFirst("(?is)^```(?:json)?\\s*", "").replaceFirst("(?is)\\s*```$", "").strip();
        }
        int start = text.indexOf('{');
        int end = text.lastIndexOf('}');
        if (start >= 0 && end > start) {
            text = text.substring(start, end + 1);
        }
        return readObject(text);
    }

    private ObjectNode readObject(String json) {
        try {
            JsonNode node = objectMapper.readTree(json == null || json.isBlank() ? "{}" : json);
            return node.isObject() ? (ObjectNode) node : objectMapper.createObjectNode();
        } catch (Exception ex) {
            throw new IllegalArgumentException("AI review JSON could not be parsed.", ex);
        }
    }

    private List<ObjectNode> readArray(String json) {
        try {
            JsonNode node = objectMapper.readTree(json == null || json.isBlank() ? "[]" : json);
            if (!node.isArray()) {
                return List.of();
            }
            java.util.ArrayList<ObjectNode> items = new java.util.ArrayList<>();
            for (JsonNode item : node) {
                if (item.isObject()) {
                    items.add((ObjectNode) item);
                }
            }
            return items;
        } catch (Exception ex) {
            return List.of();
        }
    }

    private String toJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException ex) {
            throw new IllegalArgumentException("JSON serialization failed.", ex);
        }
    }

    private Integer findMastery(long userId, long knowledgeId) {
        return jdbcTemplate.query("""
                SELECT mastery
                FROM knowledge_cards
                WHERE id = ? AND user_id = ?
                """, (rs, rowNum) -> rs.getInt("mastery"), knowledgeId, userId).stream().findFirst().orElse(null);
    }

    private int applyReviewResult(int currentMastery, String result) {
        int delta = switch (result) {
            case "完全掌握" -> 15;
            case "基本掌握" -> 5;
            case "仍然模糊" -> -5;
            case "完全不会" -> -15;
            default -> 0;
        };
        return clamp(currentMastery + delta);
    }

    private void createExtraReview(long userId, long knowledgeId, int days, String stage) {
        jdbcTemplate.update("""
                INSERT INTO review_tasks (user_id, knowledge_id, review_date, review_stage)
                VALUES (?, ?, ?, ?)
                """, userId, knowledgeId, LocalDate.now().plusDays(days).toString(), stage);
    }

    private String normalizeResult(String value, int score) {
        if ("完全掌握".equals(value) || "基本掌握".equals(value) || "仍然模糊".equals(value) || "完全不会".equals(value)) {
            return value;
        }
        if (score >= 85) {
            return "完全掌握";
        }
        if (score >= 65) {
            return "基本掌握";
        }
        if (score >= 40) {
            return "仍然模糊";
        }
        return "完全不会";
    }

    private String normalizeCause(String value) {
        Set<String> causes = Set.of("概念不清", "公式记错", "条件漏看", "计算失误", "题型没识别", "思路方向错", "表达不严谨", "前置知识缺失");
        return causes.contains(value) ? value : "概念不清";
    }

    private int clamp(int value) {
        return Math.max(0, Math.min(100, value));
    }

    private String topicForPlan(ObjectNode plan, long knowledgeId) {
        for (JsonNode question : plan.path("questions")) {
            if (question.path("knowledge_id").asLong() == knowledgeId) {
                return question.path("topic").asText("未命名知识点");
            }
        }
        return "未命名知识点";
    }

    private String defaultString(String value) {
        return value == null ? "" : value;
    }

    private String firstNonBlank(String... values) {
        for (String value : values) {
            if (value != null && !value.isBlank()) {
                return value;
            }
        }
        return "";
    }

    private String clip(String value, int limit) {
        String normalized = String.join(" ", defaultString(value).split("\\s+")).strip();
        return normalized.length() <= limit ? normalized : normalized.substring(0, limit) + "...";
    }
}
