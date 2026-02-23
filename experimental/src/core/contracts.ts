export type StepType = 'transport' | 'verification';

export interface LifecycleConfig {
  plugin: string;
  start?: Record<string, unknown>;
  readiness?: Record<string, unknown>;
  stop?: Record<string, unknown>;
}

export interface ScenarioStep {
  id: string;
  name: string;
  type: StepType;
  plugin: string;
  input: Record<string, unknown>;
  timeoutMs?: number;
  retries?: number;
  dependsOn?: string[];
}

export interface EvidenceExportStrategy {
  format: 'json';
  includeEnvironment?: boolean;
}

export interface Scenario {
  name: string;
  rail: string;
  lifecycle?: LifecycleConfig;
  steps: ScenarioStep[];
  evidence: EvidenceExportStrategy;
}

export interface EvidencePolicy {
  includeEnvironment: boolean;
  emitChecksums: boolean;
}

export interface ResolvedLifecyclePlan {
  plugin: LifecyclePlugin;
  config: LifecycleConfig;
}

export interface ResolvedStepPlan {
  step: ScenarioStep;
  plugin: TransportPlugin | VerificationPlugin;
}

export interface ExecutionPlan {
  runId: string;
  scenario: Scenario;
  lifecycle?: ResolvedLifecyclePlan;
  steps: ResolvedStepPlan[];
  evidencePolicy: EvidencePolicy;
  createdAt: string;
}

export interface TransportResult {
  ok: boolean;
  statusCode?: number;
  payload?: unknown;
  metadata?: Record<string, unknown>;
}

export interface VerificationResult {
  ok: boolean;
  assertions: Array<{ name: string; passed: boolean; details?: string }>;
  metadata?: Record<string, unknown>;
}

export interface LifecycleResult {
  ok: boolean;
  metadata?: Record<string, unknown>;
}

export interface EvidenceArtifact {
  name: string;
  contentType: 'application/json' | 'text/plain';
  data: unknown;
}

export interface PluginEvidence {
  artifacts: EvidenceArtifact[];
}

export interface TransportPlugin {
  send(request: Record<string, unknown>): Promise<{ result: TransportResult; evidence: PluginEvidence }>;
}

export interface VerificationPlugin {
  verify(query: Record<string, unknown>): Promise<{ result: VerificationResult; evidence: PluginEvidence }>;
}

export interface LifecyclePlugin {
  start?(input: Record<string, unknown>): Promise<{ result: LifecycleResult; evidence: PluginEvidence }>;
  readiness?(input: Record<string, unknown>): Promise<{ result: LifecycleResult; evidence: PluginEvidence }>;
  stop?(input: Record<string, unknown>): Promise<{ result: LifecycleResult; evidence: PluginEvidence }>;
}

export type StepStatus = 'pending' | 'running' | 'passed' | 'failed' | 'skipped';
export type RunStatus = 'passed' | 'failed';

export type ErrorClassification =
  | 'timeout'
  | 'plugin_error'
  | 'assertion_failed'
  | 'dependency_failed'
  | 'configuration_error'
  | 'runtime_error';

export interface StepExecutionResult {
  id: string;
  name: string;
  status: StepStatus;
  startedAt?: string;
  endedAt?: string;
  durationMs?: number;
  retriesUsed: number;
  errorClassification?: ErrorClassification;
  errorMessage?: string;
}

export interface RuntimeResult {
  runId: string;
  scenarioName: string;
  status: RunStatus;
  startedAt: string;
  endedAt: string;
  durationMs: number;
  steps: StepExecutionResult[];
}
