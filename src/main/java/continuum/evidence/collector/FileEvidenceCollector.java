package continuum.evidence.collector;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.Comparator;
import java.util.List;
import java.util.Objects;
import java.util.stream.Stream;

/**
 * Deterministic file-backed evidence collector.
 */
public class FileEvidenceCollector implements EvidenceCollector {
    private Path runDirectory;

    @Override
    public void initialize(Path runDirectory) throws IOException {
        this.runDirectory = Objects.requireNonNull(runDirectory, "runDirectory");
        prepareRunDirectory(runDirectory);
    }

    @Override
    public void collect(String name, byte[] content) throws IOException {
        if (runDirectory == null) {
            throw new IOException("Evidence collector is not initialized");
        }

        Path target = runDirectory.resolve(name).normalize();
        if (!target.startsWith(runDirectory.normalize())) {
            throw new IOException("Artifact path escapes run directory: " + name);
        }

        Path parent = target.getParent();
        if (parent != null) {
            Files.createDirectories(parent);
        }

        Files.write(
                target,
                content == null ? new byte[0] : content,
                StandardOpenOption.CREATE,
                StandardOpenOption.TRUNCATE_EXISTING
        );
    }

    private void prepareRunDirectory(Path directory) throws IOException {
        Path parent = directory.getParent();
        if (parent != null) {
            Files.createDirectories(parent);
        }

        if (Files.exists(directory)) {
            if (!Files.isDirectory(directory)) {
                throw new IOException("Run path exists and is not a directory: " + directory);
            }
            clearDirectory(directory);
            return;
        }

        Files.createDirectories(directory);
    }

    private void clearDirectory(Path directory) throws IOException {
        try (Stream<Path> stream = Files.walk(directory)) {
            List<Path> paths = stream
                    .filter(path -> !path.equals(directory))
                    .sorted(Comparator.reverseOrder())
                    .toList();
            for (Path path : paths) {
                Files.deleteIfExists(path);
            }
        }
    }
}
