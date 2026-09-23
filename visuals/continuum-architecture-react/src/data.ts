export type DemoStep = {
  id: string;
  name: string;
  action: string;
  dependsOn: string[];
  output: Record<string, string | number>;
  required: string[];
  equals: Record<string, string | number>;
  evidence: string[];
};

export const stages = [
  ['Workflow YAML / JSON', 'Definition'],
  ['Dependency graph', 'DAG'],
  ['Deterministic execution', 'Execution'],
  ['Validation gates', 'Gates'],
  ['Evidence collection', 'Evidence'],
  ['Logs + output snapshots', 'Snapshots'],
  ['Tamper-evident hash chain', 'Integrity'],
  ['Run bundle', 'Bundle'],
  ['Replay', 'Replay'],
] as const;

export const stageCopy = [
  'Continuum starts from a YAML or JSON workflow definition and validates its structure before execution.',
  'Step dependencies become a directed acyclic graph and a topologically sorted execution plan.',
  'The scheduler follows the resolved plan in a fixed order instead of choosing a random path.',
  'Required fields, equality contracts, and evidence requirements act as validation gates. A contract failure stops downstream work.',
  'Declared evidence is materialized per step and indexed with SHA-256 digests for inspection.',
  'Readable step logs, per-step JSON outputs, and a normalized complete output snapshot are captured.',
  'Each step adds an ordered hash record linked to the previous hash, making recorded changes detectable.',
  'The run bundle assembles the manifest, captured workflow, snapshots, logs, validation result, evidence index, hash chain, and summary.',
  'Replay runs from the captured workflow snapshot and compares output snapshots to detect drift.',
];

export const steps: DemoStep[] = [
  {
    id: 'ingest',
    name: 'Capture immutable inputs',
    action: 'mock',
    dependsOn: [],
    output: { status: 'captured', artifact_id: 'BUILD-2048' },
    required: ['status', 'artifact_id'],
    equals: { status: 'captured' },
    evidence: ['input-snapshot'],
  },
  {
    id: 'verify',
    name: 'Deterministic verification',
    action: 'mock',
    dependsOn: ['ingest'],
    output: { status: 'verified', checks_passed: 12 },
    required: ['status', 'checks_passed'],
    equals: { status: 'verified' },
    evidence: ['validation-report'],
  },
  {
    id: 'approve',
    name: 'Validation gate',
    action: 'mock',
    dependsOn: ['verify'],
    output: { status: 'approved', decision: 'deterministic' },
    required: ['status', 'decision'],
    equals: { status: 'approved' },
    evidence: ['approval-record'],
  },
  {
    id: 'package',
    name: 'Assemble evidence package',
    action: 'mock',
    dependsOn: ['approve'],
    output: { status: 'complete', final_status: 'complete' },
    required: ['status', 'final_status'],
    equals: { final_status: 'complete' },
    evidence: ['bundle-record'],
  },
];

export const workflow = {
  workflow_id: 'controlled-release-verification',
  version: '0.1',
  inputs: { artifact_id: 'BUILD-2048', environment: 'staging' },
  validation_gates: ['evidence-required', 'output-contract'],
  evidence_requirements: ['output-contract'],
  steps: steps.map((step) => ({
    id: step.id,
    name: step.name,
    action: step.action,
    ...(step.dependsOn.length ? { depends_on: step.dependsOn } : {}),
    inputs: { output: step.output },
    expected_outputs: { required_fields: step.required, equals: step.equals },
    evidence: step.evidence,
  })),
};

export const workflowYaml = [
  'workflow_id: controlled-release-verification',
  'version: "0.1"',
  'inputs:',
  '  artifact_id: BUILD-2048',
  '  environment: staging',
  'validation_gates:',
  '  - evidence-required',
  '  - output-contract',
  'evidence_requirements:',
  '  - output-contract',
  'steps:',
  '  - id: ingest',
  '    name: Capture immutable inputs',
  '    action: mock',
  '    inputs:',
  '      output: { status: captured, artifact_id: BUILD-2048 }',
  '    expected_outputs:',
  '      required_fields: [status, artifact_id]',
  '      equals: { status: captured }',
  '    evidence: [input-snapshot]',
  '  - id: verify',
  '    name: Deterministic verification',
  '    action: mock',
  '    depends_on: [ingest]',
  '    inputs:',
  '      output: { status: verified, checks_passed: 12 }',
  '    expected_outputs:',
  '      required_fields: [status, checks_passed]',
  '      equals: { status: verified }',
  '    evidence: [validation-report]',
  '  - id: approve',
  '    name: Validation gate',
  '    action: mock',
  '    depends_on: [verify]',
  '    inputs:',
  '      output: { status: approved, decision: deterministic }',
  '    expected_outputs:',
  '      required_fields: [status, decision]',
  '      equals: { status: approved }',
  '    evidence: [approval-record]',
  '  - id: package',
  '    name: Assemble evidence package',
  '    action: mock',
  '    depends_on: [approve]',
  '    inputs:',
  '      output: { status: complete, final_status: complete }',
  '    expected_outputs:',
  '      required_fields: [status, final_status]',
  '      equals: { final_status: complete }',
  '    evidence: [bundle-record]',
].join('\n');

export const bundleFiles = [
  'manifest.json',
  'inputs/workflow.yaml',
  'inputs_snapshot.json',
  'outputs/ingest.json',
  'outputs/verify.json',
  'outputs/approve.json',
  'outputs/package.json',
  'outputs_snapshot.json',
  'logs/<step-id>.log',
  'validation_result.json',
  'evidence_index.json',
  'hash_chain.json',
  'summary.json',
];
