package continuum.evidence.collector;

import java.io.IOException;
import java.nio.file.Path;

public interface EvidenceCollector {
    void initialize(Path runDirectory) throws IOException;

    void collect(String name, byte[] content) throws IOException;
}
