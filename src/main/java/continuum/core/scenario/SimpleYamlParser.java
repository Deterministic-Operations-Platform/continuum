package continuum.core.scenario;

import continuum.core.errors.ScenarioValidationError;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Tiny deterministic YAML subset parser:
 * - top-level key: value pairs
 * - top-level list of maps using "- key: value"
 */
public class SimpleYamlParser {
    public Map<String, Object> parse(String yamlContent) {
        Map<String, Object> root = new LinkedHashMap<>();
        List<Map<String, Object>> currentList = null;
        String currentContainerKey = null;
        Map<String, Object> currentMapping = null;
        Map<String, Object> currentItem = null;

        String[] lines = yamlContent.split("\\r?\\n");
        for (int i = 0; i < lines.length; i++) {
            String rawLine = lines[i];
            if (rawLine == null) {
                continue;
            }

            String trimmed = rawLine.trim();
            if (trimmed.isEmpty() || trimmed.startsWith("#")) {
                continue;
            }

            if (!rawLine.startsWith(" ") && trimmed.endsWith(":")) {
                currentContainerKey = trimmed.substring(0, trimmed.length() - 1).trim();
                currentList = null;
                currentMapping = null;
                currentItem = null;
                continue;
            }

            if (trimmed.startsWith("- ")) {
                if (currentContainerKey == null) {
                    throw new ScenarioValidationError("Invalid YAML list item at line " + (i + 1));
                }
                if (currentList == null) {
                    currentList = new ArrayList<>();
                    root.put(currentContainerKey, currentList);
                }
                currentItem = new LinkedHashMap<>();
                currentList.add(currentItem);
                String itemBody = trimmed.substring(2).trim();
                if (!itemBody.isEmpty()) {
                    parseKeyValueInto(itemBody, currentItem, i + 1);
                }
                continue;
            }

            if (rawLine.startsWith(" ") && currentItem != null) {
                parseKeyValueInto(trimmed, currentItem, i + 1);
                continue;
            }

            if (rawLine.startsWith(" ") && currentContainerKey != null) {
                if (currentList != null) {
                    throw new ScenarioValidationError("Invalid YAML list entry at line " + (i + 1));
                }
                if (currentMapping == null) {
                    currentMapping = new LinkedHashMap<>();
                    root.put(currentContainerKey, currentMapping);
                }
                parseKeyValueInto(trimmed, currentMapping, i + 1);
                continue;
            }

            if (!rawLine.startsWith(" ")) {
                parseKeyValueInto(trimmed, root, i + 1);
                currentList = null;
                currentContainerKey = null;
                currentMapping = null;
                currentItem = null;
                continue;
            }

            throw new ScenarioValidationError("Unsupported YAML structure at line " + (i + 1));
        }

        return root;
    }

    private void parseKeyValueInto(String text, Map<String, Object> target, int lineNumber) {
        int colonIndex = text.indexOf(':');
        if (colonIndex <= 0) {
            throw new ScenarioValidationError("Invalid key/value at line " + lineNumber);
        }

        String key = text.substring(0, colonIndex).trim();
        String valueText = text.substring(colonIndex + 1).trim();
        Object value = parseScalar(valueText);
        target.put(key, value);
    }

    private Object parseScalar(String valueText) {
        if (valueText.isEmpty()) {
            return "";
        }

        valueText = stripInlineComment(valueText);
        if (valueText.isEmpty()) {
            return "";
        }

        if ((valueText.startsWith("\"") && valueText.endsWith("\""))
                || (valueText.startsWith("'") && valueText.endsWith("'"))) {
            return valueText.substring(1, valueText.length() - 1);
        }

        if ("true".equalsIgnoreCase(valueText)) {
            return true;
        }
        if ("false".equalsIgnoreCase(valueText)) {
            return false;
        }

        try {
            if (valueText.contains(".")) {
                return Double.parseDouble(valueText);
            }
            return Integer.parseInt(valueText);
        } catch (NumberFormatException ignored) {
            return valueText;
        }
    }

    private String stripInlineComment(String valueText) {
        boolean inSingleQuote = false;
        boolean inDoubleQuote = false;

        for (int i = 0; i < valueText.length(); i++) {
            char current = valueText.charAt(i);
            if (current == '\'' && !inDoubleQuote) {
                inSingleQuote = !inSingleQuote;
                continue;
            }
            if (current == '"' && !inSingleQuote) {
                inDoubleQuote = !inDoubleQuote;
                continue;
            }

            if (current == '#' && !inSingleQuote && !inDoubleQuote) {
                if (i == 0 || Character.isWhitespace(valueText.charAt(i - 1))) {
                    return valueText.substring(0, i).trim();
                }
            }
        }

        return valueText;
    }
}
