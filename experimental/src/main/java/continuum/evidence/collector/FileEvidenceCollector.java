package continuum.evidence.collector;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.Objects;

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

        if (name == null || name.trim().isEmpty()) {
            throw new IOException("Artifact name must not be empty");
        }

        Path normalizedRunDirectory = runDirectory.normalize().toAbsolutePath();
        Path absoluteTarget = normalizedRunDirectory.resolve(name).normalize();
        if (!absoluteTarget.startsWith(normalizedRunDirectory)) {
            throw new IOException("Artifact path escapes run directory: " + name);
        }

        Path parent = absoluteTarget.getParent();
        if (parent != null) {
            Files.createDirectories(parent);
        }

        Files.write(
                absoluteTarget,
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
            return;
        }

        Files.createDirectories(directory);
    }
}
