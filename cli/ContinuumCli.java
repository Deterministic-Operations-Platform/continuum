package cli;

import core.runtime.ContinuumRuntime;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * Minimal CLI skeleton for continuum v0.1.
 */
public final class ContinuumCli {
    private ContinuumCli() {
    }

    public static void main(String[] args) {
        if (args.length == 0) {
            printUsage();
            return;
        }

        String command = args[0];
        try {
            switch (command) {
                case "init" -> init();
                case "run" -> run(args);
                default -> printUsage();
            }
        } catch (IOException ex) {
            System.err.println("I/O error: " + ex.getMessage());
            System.exit(1);
        }
    }

    private static void init() throws IOException {
        Files.createDirectories(Path.of("scenarios"));
        Files.createDirectories(Path.of("runs"));
        System.out.println("Initialized continuum workspace: scenarios/ and runs/");
    }

    private static void run(String[] args) throws IOException {
        if (args.length < 2) {
            System.err.println("Missing scenario path. Usage: continuum run <scenario-path>");
            System.exit(2);
        }

        Path scenarioPath = Path.of(args[1]);
        ContinuumRuntime runtime = new ContinuumRuntime();
        ContinuumRuntime.RunSummary summary = runtime.run(scenarioPath, Path.of("runs"));

        System.out.println("Run complete: " + summary.runId());
        System.out.println("Summary: runs/" + summary.runId() + "/summary.json");
    }

    private static void printUsage() {
        System.out.println("continuum <command>");
        System.out.println("  init                Initialize local scaffold directories");
        System.out.println("  run <scenario-path> Load scenario and write runs/<run-id>/summary.json");
    }
}
