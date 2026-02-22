import {
  ErrorClassification,
  ExecutionPlan,
  RuntimeResult,
  StepExecutionResult,
  StepStatus,
  TransportPlugin,
  VerificationPlugin,
} from './contracts';

const DEFAULT_TIMEOUT_MS = 30_000;

export class Runtime {
  async execute(plan: ExecutionPlan): Promise<RuntimeResult> {
    const startedAt = new Date().toISOString();
    const stepResults: StepExecutionResult[] = [];

    for (const resolved of plan.steps) {
      const step = resolved.step;
      const started = Date.now();

      const stepResult: StepExecutionResult = {
        id: step.id,
        name: step.name,
        status: 'running',
        startedAt: new Date(started).toISOString(),
        retriesUsed: 0,
      };

      try {
        await this.executeWithPolicy(resolved.plugin, step.input, step.type, step.timeoutMs ?? DEFAULT_TIMEOUT_MS, step.retries ?? 0);
        stepResult.status = 'passed';
      } catch (error) {
        stepResult.status = 'failed';
        stepResult.errorClassification = this.classifyError(error);
        stepResult.errorMessage = error instanceof Error ? error.message : String(error);
      }

      const ended = Date.now();
      stepResult.endedAt = new Date(ended).toISOString();
      stepResult.durationMs = ended - started;
      stepResults.push(stepResult);

      if (stepResult.status === 'failed') {
        this.markRemainingStepsSkipped(plan.steps.slice(stepResults.length).map((s) => s.step), stepResults);
        break;
      }
    }

    const endedAt = new Date().toISOString();
    const failed = stepResults.some((s) => s.status === 'failed');

    return {
      runId: plan.runId,
      scenarioName: plan.scenario.name,
      status: failed ? 'failed' : 'passed',
      startedAt,
      endedAt,
      durationMs: Date.parse(endedAt) - Date.parse(startedAt),
      steps: stepResults,
    };
  }

  private async executeWithPolicy(
    plugin: TransportPlugin | VerificationPlugin,
    input: Record<string, unknown>,
    type: 'transport' | 'verification',
    timeoutMs: number,
    retries: number,
  ): Promise<void> {
    let attempts = 0;

    while (attempts <= retries) {
      attempts += 1;
      try {
        if (type === 'transport') {
          const response = await this.withTimeout((plugin as TransportPlugin).send(input), timeoutMs);
          if (!response.result.ok) throw new Error('Transport plugin returned ok=false');
        } else {
          const response = await this.withTimeout((plugin as VerificationPlugin).verify(input), timeoutMs);
          if (!response.result.ok) throw new Error('Verification plugin returned ok=false');
        }
        return;
      } catch (error) {
        if (attempts > retries) throw error;
      }
    }
  }

  private withTimeout<T>(promise: Promise<T>, timeoutMs: number): Promise<T> {
    return Promise.race([
      promise,
      new Promise<T>((_, reject) => {
        setTimeout(() => reject(new Error(`Timeout after ${timeoutMs}ms`)), timeoutMs);
      }),
    ]);
  }

  private classifyError(error: unknown): ErrorClassification {
    const message = error instanceof Error ? error.message.toLowerCase() : String(error).toLowerCase();
    if (message.includes('timeout')) return 'timeout';
    if (message.includes('assert')) return 'assertion_failed';
    if (message.includes('config')) return 'configuration_error';
    if (message.includes('plugin')) return 'plugin_error';
    return 'runtime_error';
  }

  private markRemainingStepsSkipped(
    steps: Array<{ id: string; name: string }>,
    results: StepExecutionResult[],
  ): void {
    steps.forEach((step) => {
      results.push({
        id: step.id,
        name: step.name,
        status: 'skipped' as StepStatus,
        retriesUsed: 0,
        errorClassification: 'dependency_failed',
        errorMessage: 'Skipped due to previous step failure',
      });
    });
  }
}
