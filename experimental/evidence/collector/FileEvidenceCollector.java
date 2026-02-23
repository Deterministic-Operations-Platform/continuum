package evidence.collector;

import core.scenario.Scenario;
import core.scenario.ScenarioStep;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.TreeMap;

/**
 * Filesystem-backed evidence collector with deterministic artifact output.
 */
public final class FileEvidenceCollector implements EvidenceCollector {
    private static final String FILE_SCENARIO = "scenario.yaml";
    private static final String FILE_SUMMARY = "summary.json";
    private static final String FILE_EVENTS = "events.log";
    private static final String FILE_MANIFEST = "manifest.json";
    private static final List<String> MANIFEST_ARTIFACT_ORDER = List.of(
            FILE_SCENARIO,
            FILE_SUMMARY,
            FILE_EVENTS,
            FILE_MANIFEST
    );

    private final List<Map<String, Object>> recordedEvents = new ArrayList<>();
    private Path runDirectory;
    private String activeRunId;

    @Override
    public void startRun(String runId, Scenario scenario, Path runDirectory) {
        this.activeRunId = Objects.requireNonNull(runId, "runId");
        this.runDirectory = Objects.requireNonNull(runDirectory, "runDirectory");

        try {
            prepareRunDirectory(runDirectory);
            String scenarioContent = scenario == null || scenario.rawDefinition() == null ? "" : scenario.rawDefinition();
            Files.writeString(
                    runDirectory.resolve(FILE_SCENARIO),
                    scenarioContent,
                    StandardCharsets.UTF_8,
                    StandardOpenOption.CREATE,
                    StandardOpenOption.TRUNCATE_EXISTING
            );
            recordedEvents.clear();
        } catch (IOException ex) {
            throw new RuntimeException("Failed to start evidence run in " + runDirectory, ex);
        }
    }

    @Override
    public void recordStep(String runId, ScenarioStep step, Map<String, Object> event) {
        if (runDirectory == null) {
            return;
        }
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("runId", runId);
        entry.put("stepId", step == null ? "" : step.id());
        entry.put("stepName", step == null ? "" : step.name());
        entry.put("stepType", step == null ? "" : step.type());
        entry.put("plugin", step == null ? "" : step.plugin());
        entry.put("event", normalizeValue(event == null ? Map.of() : event));
        recordedEvents.add(entry);
    }

    @Override
    public void completeRun(String runId, Map<String, Object> summary) {
        try {
            ensureInitialized(runId);

            Map<String, Object> summaryPayload = normalizeMap(summary == null ? Map.of() : summary);
            Files.writeString(
                    runDirectory.resolve(FILE_SUMMARY),
                    toJson(summaryPayload) + System.lineSeparator(),
                    StandardCharsets.UTF_8,
                    StandardOpenOption.CREATE,
                    StandardOpenOption.TRUNCATE_EXISTING
            );

            writeEvents();
            writeManifest(runId);
        } catch (IOException ex) {
            throw new RuntimeException("Failed to complete evidence run in " + runDirectory, ex);
        }
    }

    private void ensureInitialized(String runId) throws IOException {
        if (runDirectory == null) {
            throw new IOException("Evidence collector has not been initialized");
        }
        if (!Objects.equals(activeRunId, runId)) {
            throw new IOException("Evidence run id mismatch. Expected " + activeRunId + " but got " + runId);
        }
    }

    private void prepareRunDirectory(Path directory) throws IOException {
        Path parent = directory.getParent();
        if (parent != null) {
            Files.createDirectories(parent);
        }

        if (Files.exists(directory) && !Files.isDirectory(directory)) {
            throw new IOException("Run path exists and is not a directory: " + directory);
        }

        Files.createDirectories(directory);
    }

    private void writeEvents() throws IOException {
        StringBuilder builder = new StringBuilder();
        for (int i = 0; i < recordedEvents.size(); i++) {
            if (i > 0) {
                builder.append(System.lineSeparator());
            }
            builder.append(toJson(normalizeMap(recordedEvents.get(i))));
        }
        if (!recordedEvents.isEmpty()) {
            builder.append(System.lineSeparator());
        }

        Files.writeString(
                runDirectory.resolve(FILE_EVENTS),
                builder.toString(),
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE,
                StandardOpenOption.TRUNCATE_EXISTING
        );
    }

    private void writeManifest(String runId) throws IOException {
        Map<String, Object> manifest = new LinkedHashMap<>();
        manifest.put("runId", runId);
        manifest.put("artifactCount", MANIFEST_ARTIFACT_ORDER.size());
        manifest.put("artifacts", MANIFEST_ARTIFACT_ORDER);

        Files.writeString(
                runDirectory.resolve(FILE_MANIFEST),
                toJson(manifest) + System.lineSeparator(),
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE,
                StandardOpenOption.TRUNCATE_EXISTING
        );
    }

    private static Map<String, Object> normalizeMap(Map<String, Object> value) {
        Map<String, Object> sorted = new TreeMap<>();
        for (Map.Entry<String, Object> entry : value.entrySet()) {
            sorted.put(entry.getKey(), normalizeValue(entry.getValue()));
        }
        Map<String, Object> normalized = new LinkedHashMap<>();
        normalized.putAll(sorted);
        return normalized;
    }

    @SuppressWarnings("unchecked")
    private static Object normalizeValue(Object value) {
        if (value instanceof Map<?, ?> mapValue) {
            Map<String, Object> converted = new LinkedHashMap<>();
            for (Map.Entry<?, ?> entry : mapValue.entrySet()) {
                converted.put(String.valueOf(entry.getKey()), normalizeValue(entry.getValue()));
            }
            return normalizeMap(converted);
        }
        if (value instanceof List<?> listValue) {
            List<Object> normalized = new ArrayList<>(listValue.size());
            for (Object item : listValue) {
                normalized.add(normalizeValue(item));
            }
            return normalized;
        }
        return value;
    }

    private static String toJson(Object value) {
        StringBuilder builder = new StringBuilder();
        appendJson(builder, value);
        return builder.toString();
    }

    @SuppressWarnings("unchecked")
    private static void appendJson(StringBuilder builder, Object value) {
        if (value == null) {
            builder.append("null");
            return;
        }
        if (value instanceof String text) {
            builder.append('"').append(escapeJson(text)).append('"');
            return;
        }
        if (value instanceof Number || value instanceof Boolean) {
            builder.append(value);
            return;
        }
        if (value instanceof Map<?, ?> mapValue) {
            builder.append('{');
            boolean first = true;
            for (Map.Entry<?, ?> entry : mapValue.entrySet()) {
                if (!first) {
                    builder.append(',');
                }
                first = false;
                builder.append('"').append(escapeJson(String.valueOf(entry.getKey()))).append('"').append(':');
                appendJson(builder, entry.getValue());
            }
            builder.append('}');
            return;
        }
        if (value instanceof List<?> listValue) {
            builder.append('[');
            for (int i = 0; i < listValue.size(); i++) {
                if (i > 0) {
                    builder.append(',');
                }
                appendJson(builder, listValue.get(i));
            }
            builder.append(']');
            return;
        }

        builder.append('"').append(escapeJson(String.valueOf(value))).append('"');
    }

    private static String escapeJson(String value) {
        StringBuilder escaped = new StringBuilder(value.length() + 8);
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            switch (c) {
                case '"' -> escaped.append("\\\"");
                case '\\' -> escaped.append("\\\\");
                case '\b' -> escaped.append("\\b");
                case '\f' -> escaped.append("\\f");
                case '\n' -> escaped.append("\\n");
                case '\r' -> escaped.append("\\r");
                case '\t' -> escaped.append("\\t");
                default -> {
                    if (c < 0x20) {
                        escaped.append(String.format("\\u%04x", (int) c));
                    } else {
                        escaped.append(c);
                    }
                }
            }
        }
        return escaped.toString();
    }
}
