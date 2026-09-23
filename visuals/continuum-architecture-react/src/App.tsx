import { useEffect, useMemo, useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { Background, Controls, MarkerType, ReactFlow, type Edge, type Node } from '@xyflow/react';
import { Activity, Braces, ChevronLeft, ChevronRight, FileArchive, FileCode2, Fingerprint, GitBranch, Pause, Play, RotateCcw, ShieldCheck, Sparkles, TerminalSquare, Zap } from 'lucide-react';
import { bundleFiles, stageCopy, stages, steps, workflow, workflowYaml } from './data';

type ArtifactTab = 'gates' | 'evidence' | 'outputs' | 'hash' | 'bundle' | 'replay';

const positions = [
  { x: 24, y: 140 },
  { x: 250, y: 140 },
  { x: 476, y: 140 },
  { x: 702, y: 140 },
];

function canonical(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  const record = value as Record<string, unknown>;
  return '{' + Object.keys(record).sort().map((key) => JSON.stringify(key) + ':' + canonical(record[key])).join(',') + '}';
}

async function sha256(value: unknown) {
  const payload = typeof value === 'string' ? value : canonical(value);
  const bytes = new TextEncoder().encode(payload);
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest)).map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

function shortHash(value: string) {
  return value ? value.slice(0, 10) + '…' + value.slice(-6) : 'pending';
}

function App() {
  const reducedMotion = useReducedMotion();
  const [stage, setStage] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [format, setFormat] = useState<'yaml' | 'json'>('yaml');
  const [selected, setSelected] = useState(0);
  const [execution, setExecution] = useState(-1);
  const [contractMismatch, setContractMismatch] = useState(false);
  const [tampered, setTampered] = useState(false);
  const [drift, setDrift] = useState(false);
  const [artifactTab, setArtifactTab] = useState<ArtifactTab>('gates');
  const [outputStep, setOutputStep] = useState('ingest');
  const [hashes, setHashes] = useState<string[]>([]);
  const [chain, setChain] = useState<{ stepId: string; output: string; prev: string; hash: string }[]>([]);

  const stageTab = ['gates','gates','gates','gates','evidence','outputs','hash','bundle','replay'][stage] as ArtifactTab;

  useEffect(() => setArtifactTab(stageTab), [stageTab]);

  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => setStage((value) => value >= 8 ? 0 : value + 1), 3300);
    return () => window.clearInterval(timer);
  }, [playing]);

  useEffect(() => {
    if (stage < 2) setExecution(-1);
    else if (stage === 2 && execution < 0) setExecution(0);
    else if (stage >= 4 && !contractMismatch) setExecution(4);
  }, [stage, contractMismatch, execution]);

  useEffect(() => {
    void (async () => {
      const outputHashes: string[] = [];
      const records: { stepId: string; output: string; prev: string; hash: string }[] = [];
      let prev = '';
      for (const step of steps) {
        const output = await sha256(step.output);
        outputHashes.push(output);
        const body = {
          step_id: step.id,
          output_sha256: output,
          evidence: ['output-contract', ...step.evidence].map((type) => 'evidence/' + step.id + '-' + type + '.json'),
          prev_hash: prev,
        };
        const hash = await sha256(body);
        records.push({ stepId: step.id, output, prev, hash });
        prev = hash;
      }
      setHashes(outputHashes);
      setChain(records);
    })();
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'ArrowRight') setStage((value) => Math.min(8, value + 1));
      if (event.key === 'ArrowLeft') setStage((value) => Math.max(0, value - 1));
      if (event.key === ' ') {
        event.preventDefault();
        setPlaying((value) => !value);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  function currentOutput(index: number) {
    const output = structuredClone(steps[index].output) as Record<string, string | number>;
    if (contractMismatch && index === 1) output.status = 'mismatch';
    if (tampered && index === 2) output.decision = 'altered';
    return output;
  }

  function stepStatus(index: number) {
    if (stage < 2) return 'queued';
    if (contractMismatch) {
      if (index < 1) return 'passed';
      if (index === 1) return 'failed';
      return 'blocked';
    }
    if (execution === index) return 'running';
    if (execution > index || stage >= 4) return 'passed';
    return 'queued';
  }

  const nodes = useMemo<Node[]>(() => steps.map((step, index) => {
    const status = stepStatus(index);
    return {
      id: step.id,
      position: positions[index],
      draggable: false,
      selectable: false,
      className: 'continuum-node ' + status,
      style: { width: 178, borderRadius: 10 },
      data: {
        label: (
          <button onClick={() => setSelected(index)} className="w-full text-left" aria-label={'Inspect ' + step.name}>
            <div className="mb-2 flex items-center justify-between">
              <span className="mono text-[9px] uppercase tracking-[.12em] text-cyan-300">{step.id}</span>
              <span className={'status-dot ' + status} />
            </div>
            <div className="text-[12px] font-semibold leading-tight text-slate-100">{step.name}</div>
            <div className="mono mt-2 text-[8px] uppercase text-slate-500">{step.dependsOn.length ? 'depends: ' + step.dependsOn.join(', ') : 'root step'}</div>
          </button>
        ),
      },
    };
  }), [stage, execution, contractMismatch]);

  const edges = useMemo<Edge[]>(() => steps.slice(1).map((step, index) => ({
    id: 'edge-' + index,
    source: steps[index].id,
    target: step.id,
    animated: stage >= 1 && !reducedMotion,
    markerEnd: { type: MarkerType.ArrowClosed, color: '#4bd9d0' },
    style: { stroke: stage >= 1 ? '#4bd9d0' : '#314a5c', strokeWidth: stage >= 1 ? 1.7 : 1 },
  })), [stage, reducedMotion]);

  async function runPlan() {
    setContractMismatch(false);
    for (let index = 0; index < steps.length; index += 1) {
      setExecution(index);
      setSelected(index);
      await new Promise((resolve) => window.setTimeout(resolve, reducedMotion ? 80 : 620));
    }
    setExecution(4);
  }

  const validationRows = steps.flatMap((step, index) => {
    const output = currentOutput(index);
    const blocked = contractMismatch && index > 1;
    const requiredPass = step.required.every((key) => key in output);
    const equalsPass = Object.entries(step.equals).every(([key, value]) => output[key] === value);
    const evidencePass = step.evidence.length > 0;
    const status = (pass: boolean) => blocked ? 'blocked' : stage >= 3 ? (pass ? 'pass' : 'fail') : 'pending';
    return [
      [step.id, 'required fields', status(requiredPass)],
      [step.id, 'equals contract', status(equalsPass)],
      [step.id, 'evidence-required', status(evidencePass)],
    ] as const;
  });

  const snapshot = Object.fromEntries(steps.map((step, index) => [step.id, currentOutput(index)]));

  return (
    <div className="min-h-screen bg-[#07111a] text-slate-100">
      <div className="pointer-events-none fixed inset-0 tech-grid opacity-75" />
      <div className="relative mx-auto w-[min(1580px,calc(100%_-_24px))] pb-10">
        <Header />
        <Hero />

        <section className="grid border-b border-slate-700/50 sm:grid-cols-2 xl:grid-cols-5">
          {['YAML / JSON definitions','Dependency-aware execution','Validation gates','Evidence + SHA-256 integrity','Replay drift detection'].map((item, index) => (
            <div key={item} className="flex min-h-14 items-center gap-3 border-slate-700/40 px-4 mono text-[9px] uppercase tracking-[.05em] text-slate-500 xl:border-r">
              <span className="text-cyan-300">{String(index + 1).padStart(2, '0')}</span>{item}
            </div>
          ))}
        </section>

        <section className="sticky top-0 z-40 mt-5 overflow-hidden rounded-xl border border-slate-700/60 bg-[#07111a]/95 shadow-2xl shadow-black/25 backdrop-blur-xl">
          <div className="flex min-h-12 items-center border-b border-slate-700/50">
            <button onClick={() => setPlaying((value) => !value)} className="flex min-h-12 items-center gap-2 border-r border-slate-700/50 px-4 mono text-[9px] uppercase tracking-[.08em] text-slate-400 hover:bg-white/[.025] hover:text-white">
              {playing ? <Pause size={14} /> : <Play size={14} />}{playing ? 'Pause tour' : 'Play guided tour'}
            </button>
            <div className="hidden flex-1 px-4 mono text-[10px] uppercase tracking-[.07em] text-slate-200 md:block">{String(stage + 1).padStart(2, '0')} · {stages[stage][0]}</div>
            <div className="ml-auto flex">
              <button disabled={stage === 0} onClick={() => setStage((value) => Math.max(0, value - 1))} className="grid min-h-12 w-12 place-items-center border-l border-slate-700/50 text-slate-400 disabled:opacity-25"><ChevronLeft size={16} /></button>
              <button disabled={stage === 8} onClick={() => setStage((value) => Math.min(8, value + 1))} className="grid min-h-12 w-12 place-items-center border-l border-slate-700/50 text-slate-400 disabled:opacity-25"><ChevronRight size={16} /></button>
            </div>
          </div>
          <div className="grid min-w-[900px] grid-cols-9 overflow-x-auto">
            {stages.map(([label, short], index) => (
              <button key={label} onClick={() => setStage(index)} className={'stage-button relative min-h-16 border-r border-slate-700/40 px-3 py-2 text-left ' + (index === stage ? 'active bg-cyan-300/[.07]' : index < stage ? 'done' : '')}>
                <span className="mono block text-[8px] text-cyan-300/70">{String(index + 1).padStart(2, '0')}</span>
                <span className={'mono mt-1 block text-[9px] uppercase tracking-[.04em] ' + (index === stage ? 'text-slate-100' : 'text-slate-500')}>{short}</span>
              </button>
            ))}
          </div>
        </section>

        <section className={'stage-canvas s' + stage + ' mt-4 grid min-h-[700px] overflow-hidden rounded-xl border border-slate-700/60 bg-slate-950/25 shadow-2xl shadow-black/30'}>
          <DefinitionZone stage={stage} format={format} setFormat={setFormat} />
          <ExecutionZone stage={stage} selected={selected} execution={execution} contractMismatch={contractMismatch} nodes={nodes} edges={edges} setContractMismatch={setContractMismatch} runPlan={runPlan} />
          <EvidenceZone
            stage={stage}
            tab={artifactTab}
            setTab={setArtifactTab}
            validationRows={validationRows}
            hashes={hashes}
            chain={chain}
            tampered={tampered}
            setTampered={setTampered}
            snapshot={snapshot}
            outputStep={outputStep}
            setOutputStep={setOutputStep}
            currentOutput={currentOutput}
            drift={drift}
            setDrift={setDrift}
          />
        </section>

        <motion.div key={stage} initial={{ opacity:0, y:5 }} animate={{ opacity:1, y:0 }} className="mt-3 rounded-lg border border-slate-700/50 bg-white/[.015] px-3 py-2.5 mono text-[9px] leading-5 text-slate-500">
          <span className="text-slate-200">{stages[stage][0]}.</span> {stageCopy[stage]}
        </motion.div>

        <footer className="mt-8 grid gap-4 border-t border-slate-700/50 pt-6 mono text-[8px] uppercase leading-5 tracking-[.04em] text-slate-600 md:grid-cols-[1fr_auto]">
          <div><span className="text-slate-400">Scope:</span> workflow → deterministic plan → validation → evidence → hash chain → run bundle → replay. No company-specific integration is implied.</div>
          <div>Tamper-evident ≠ tamper-proof · SHA-256 integrity indicators</div>
        </footer>
      </div>
    </div>
  );
}

function Header() {
  return (
    <header className="flex min-h-16 items-center justify-between border-b border-slate-700/50">
      <div className="flex items-center gap-3">
        <div className="grid h-9 w-9 place-items-center rounded-md border border-cyan-300/30 bg-cyan-300/10 mono text-sm font-bold text-cyan-200">C</div>
        <div><div className="text-sm font-semibold">Continuum</div><div className="mono text-[9px] uppercase tracking-[.12em] text-slate-500">Architecture experience</div></div>
      </div>
      <div className="hidden items-center gap-2 mono text-[9px] uppercase tracking-[.08em] text-slate-500 md:flex"><span className="h-2 w-2 rounded-full bg-emerald-300 shadow-[0_0_0_6px_rgba(110,231,183,.07)]" />Local deterministic demo · no external systems</div>
    </header>
  );
}

function Hero() {
  return (
    <section className="grid gap-8 border-b border-slate-700/50 py-12 lg:grid-cols-[1.35fr_.65fr] lg:items-end lg:py-14">
      <div>
        <div className="mb-4 mono text-[10px] uppercase tracking-[.14em] text-cyan-300">Deterministic orchestration · Replayable evidence</div>
        <h1 className="max-w-5xl text-[clamp(3rem,6.4vw,6.6rem)] font-semibold leading-[.91] tracking-[-.055em] text-slate-50">Deterministic execution you can replay, inspect, and audit.</h1>
        <p className="mt-6 max-w-3xl text-[17px] leading-8 text-slate-400">Define a workflow. Execute the same plan. Capture the evidence. Prove what happened.</p>
      </div>
      <motion.aside initial={{ opacity:0, y:14 }} animate={{ opacity:1, y:0 }} className="rounded-xl border border-slate-700/60 bg-slate-950/35 p-5 shadow-2xl shadow-black/20">
        <div className="mono text-[9px] uppercase tracking-[.12em] text-slate-500">Product position</div>
        <div className="mt-4 flex flex-wrap gap-2">{['Deterministic','Replayable','Auditable','Vendor-neutral'].map((tag) => <span key={tag} className="rounded-md border border-slate-700/70 px-2.5 py-1.5 mono text-[9px] uppercase text-slate-300">{tag}</span>)}</div>
        <p className="mt-5 border-t border-slate-700/50 pt-4 text-sm leading-6 text-slate-400">A standalone orchestration framework for high-stakes engineering workflows with validation, evidence capture, SHA-256 integrity, and replay drift detection.</p>
      </motion.aside>
    </section>
  );
}

function DefinitionZone({ stage, format, setFormat }: { stage:number; format:'yaml'|'json'; setFormat:(value:'yaml'|'json')=>void }) {
  return (
    <section className={'zone p-4 ' + (stage === 0 ? 'zone-active' : '')}>
      <div className="mb-3 flex min-h-10 items-start justify-between gap-3">
        <div><div className="mono text-[8px] uppercase tracking-[.14em] text-cyan-300">Definition</div><h2 className="mt-1 text-sm font-semibold">Workflow source</h2></div>
        <div className="flex overflow-hidden rounded-md border border-slate-700/70 bg-black/20">{(['yaml','json'] as const).map((item) => <button key={item} onClick={() => setFormat(item)} className={'min-h-8 px-3 mono text-[8px] uppercase ' + (format === item ? 'bg-cyan-300 text-[#07111a]' : 'text-slate-500')}>{item}</button>)}</div>
      </div>
      <div className="relative h-[620px] overflow-hidden rounded-lg border border-slate-700/60 bg-[#050d14]">
        <div className="flex min-h-10 items-center justify-between border-b border-slate-700/50 px-3 mono text-[8px] uppercase tracking-[.06em] text-slate-500"><span>{format === 'yaml' ? 'workflow.yaml' : 'workflow.json'}</span><span>Illustrative · real schema</span></div>
        <pre className="h-[580px] overflow-auto whitespace-pre p-4 mono text-[10px] leading-[1.7] text-slate-300 scrollbar-thin">{format === 'yaml' ? workflowYaml : JSON.stringify(workflow, null, 2)}</pre>
        {stage === 0 && <motion.div initial={{ opacity:0 }} animate={{ opacity:1 }} className="pointer-events-none absolute left-2 right-2 top-[84px] h-7 border border-cyan-300/25 bg-cyan-300/[.04] shadow-[inset_3px_0_0_#4bd9d0]" />}
      </div>
    </section>
  );
}

function ExecutionZone({ stage, selected, execution, contractMismatch, nodes, edges, setContractMismatch, runPlan }: {
  stage:number; selected:number; execution:number; contractMismatch:boolean; nodes:Node[]; edges:Edge[];
  setContractMismatch:(value:boolean)=>void; runPlan:()=>void;
}) {
  const step = steps[selected];
  return (
    <section className={'zone zone-execution border-l border-slate-700/50 p-4 ' + (stage >= 1 && stage <= 3 ? 'zone-active' : '')}>
      <div className="mb-3 flex min-h-10 items-start justify-between gap-3">
        <div><div className="mono text-[8px] uppercase tracking-[.14em] text-cyan-300">Execution</div><h2 className="mt-1 text-sm font-semibold">Dependency plan</h2></div>
        <div className="mono text-[8px] uppercase text-slate-500">DAG · topological plan</div>
      </div>
      <div className="overflow-hidden rounded-lg border border-slate-700/60 bg-[#07121b]">
        <div className="flex min-h-11 gap-2 overflow-x-auto border-b border-slate-700/50 px-3 py-2">
          {steps.map((item,index) => <span key={item.id} className={'rounded border px-2 py-1 mono text-[8px] uppercase ' + (execution === index ? 'border-cyan-300 bg-cyan-300 text-[#07111a]' : 'border-slate-700/60 text-slate-500')}>{index + 1} · {item.id}</span>)}
        </div>
        <div className="flow-wrap">
          <ReactFlow nodes={nodes} edges={edges} fitView fitViewOptions={{ padding:.18 }} minZoom={.55} maxZoom={1.2} nodesDraggable={false} panOnScroll={false}>
            <Background gap={28} size={1} color="#1d2c38" />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
        <div className="m-3 grid gap-3 rounded-lg border border-slate-700/60 bg-[#050d14]/95 p-3 sm:grid-cols-[105px_1fr]">
          <div><div className="mono text-[8px] uppercase tracking-[.12em] text-cyan-300">Selected step</div><div className="mt-1 text-sm font-semibold">{step.id}</div></div>
          <div><div className="text-[12px] font-semibold">{step.name}</div><div className="mono mt-1 text-[8px] text-slate-500">action={step.action} · depends_on={step.dependsOn.join(', ') || 'none'}</div><div className="mt-2 flex flex-wrap gap-1.5"><span className="micro-tag">required: {step.required.join(', ')}</span><span className="micro-tag">evidence: {step.evidence.join(', ')}</span></div></div>
          {stage === 2 && <div className="sm:col-span-2"><button className="action-primary" onClick={runPlan}><Zap size={13} />Run deterministic plan</button></div>}
          {stage === 3 && <div className="sm:col-span-2"><button className="action-warning" onClick={() => setContractMismatch(!contractMismatch)}><ShieldCheck size={13} />{contractMismatch ? 'Reset contract simulation' : 'Simulate contract mismatch'}</button></div>}
        </div>
      </div>
    </section>
  );
}

function EvidenceZone(props: {
  stage:number; tab:ArtifactTab; setTab:(value:ArtifactTab)=>void;
  validationRows: readonly (readonly [string,string,string])[];
  hashes:string[]; chain:{stepId:string;output:string;prev:string;hash:string}[];
  tampered:boolean; setTampered:(value:boolean)=>void;
  snapshot:Record<string,unknown>; outputStep:string; setOutputStep:(value:string)=>void;
  currentOutput:(index:number)=>Record<string,string|number>;
  drift:boolean; setDrift:(value:boolean)=>void;
}) {
  const tabs: ArtifactTab[] = ['gates','evidence','outputs','hash','bundle','replay'];
  return (
    <section className={'zone zone-evidence border-l border-slate-700/50 p-4 ' + (props.stage >= 4 ? 'zone-active' : '')}>
      <div className="mb-3 flex min-h-10 items-start justify-between gap-3"><div><div className="mono text-[8px] uppercase tracking-[.14em] text-cyan-300">Evidence</div><h2 className="mt-1 text-sm font-semibold">Run artifacts</h2></div><div className="mono text-[8px] uppercase text-slate-500">{props.stage < 3 ? 'awaiting execution' : props.stage < 7 ? 'artifacts captured' : props.stage === 7 ? 'bundle assembled' : 'replay ready'}</div></div>
      <div className="min-h-[620px] overflow-hidden rounded-lg border border-slate-700/60 bg-[#07121b]">
        <div className="flex min-h-10 overflow-x-auto border-b border-slate-700/50">{tabs.map((tab) => <button key={tab} onClick={() => props.setTab(tab)} className={'border-r border-slate-700/50 px-3 mono text-[8px] uppercase whitespace-nowrap ' + (props.tab === tab ? 'bg-cyan-300/[.06] text-slate-100 shadow-[inset_0_-2px_0_#4bd9d0]' : 'text-slate-500')}>{tab}</button>)}</div>
        <div className="max-h-[580px] overflow-auto p-3 scrollbar-thin">
          <AnimatePresence mode="wait">
            <motion.div key={props.tab} initial={{ opacity:0, y:5 }} animate={{ opacity:1, y:0 }} exit={{ opacity:0, y:-4 }}>
              {props.tab === 'gates' && <GateView rows={props.validationRows} />}
              {props.tab === 'evidence' && <EvidenceView hashes={props.hashes} visible={props.stage >= 4} />}
              {props.tab === 'outputs' && <OutputView outputStep={props.outputStep} setOutputStep={props.setOutputStep} snapshot={props.snapshot} currentOutput={props.currentOutput} />}
              {props.tab === 'hash' && <HashView chain={props.chain} hashes={props.hashes} tampered={props.tampered} setTampered={props.setTampered} />}
              {props.tab === 'bundle' && <BundleView visible={props.stage >= 7} />}
              {props.tab === 'replay' && <ReplayView drift={props.drift} setDrift={props.setDrift} />}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </section>
  );
}

function GateView({ rows }: { rows: readonly (readonly [string,string,string])[] }) {
  const failed = rows.some((row) => row[2] === 'fail');
  return <div><Status bad={failed} left={failed ? 'Validation failed · fail-fast' : 'Validation gates'} right="output-contract + evidence-required" /><div className="space-y-2">{rows.map(([step,gate,status]) => <div key={step + gate} className="flex items-center justify-between gap-3 rounded-md border border-slate-700/55 bg-white/[.012] px-3 py-2 mono text-[8px]"><span className="text-slate-400">{step} · {gate}</span><span className={status === 'pass' ? 'text-emerald-300' : status === 'fail' ? 'text-red-300' : 'text-slate-600'}>{status.toUpperCase()}</span></div>)}</div></div>;
}

function EvidenceView({ hashes, visible }: { hashes:string[]; visible:boolean }) {
  return <div className="space-y-2">{steps.flatMap((step,index) => ['output-contract',...step.evidence].map((type) => <motion.div key={step.id + type} initial={false} animate={{ opacity:visible ? 1 : .3, x:visible ? 0 : 6 }} className="grid grid-cols-[1fr_auto] items-center gap-3 rounded-md border border-slate-700/55 bg-white/[.012] p-3"><div><div className="text-[11px] font-semibold">evidence/{step.id}-{type}.json</div><div className="mono mt-1 text-[8px] text-slate-600">step={step.id} · type={type}</div></div><span title={hashes[index]} className="max-w-32 truncate rounded border border-cyan-300/20 px-2 py-1 mono text-[8px] text-cyan-300">{shortHash(hashes[index])}</span></motion.div>))}</div>;
}

function OutputView({ outputStep, setOutputStep, snapshot, currentOutput }: { outputStep:string; setOutputStep:(value:string)=>void; snapshot:Record<string,unknown>; currentOutput:(index:number)=>Record<string,string|number> }) {
  const index = steps.findIndex((step) => step.id === outputStep);
  return <div><div className="mb-2 flex flex-wrap gap-1.5">{steps.map((step) => <button key={step.id} onClick={() => setOutputStep(step.id)} className={'rounded border px-2 py-1 mono text-[8px] uppercase ' + (outputStep === step.id ? 'border-cyan-300 text-slate-100' : 'border-slate-700/60 text-slate-600')}>{step.id}</button>)}<button onClick={() => setOutputStep('snapshot')} className={'rounded border px-2 py-1 mono text-[8px] uppercase ' + (outputStep === 'snapshot' ? 'border-cyan-300 text-slate-100' : 'border-slate-700/60 text-slate-600')}>snapshot</button></div>{outputStep === 'snapshot' ? <Inspect title="outputs_snapshot.json" meta="normalized output map" value={snapshot} /> : <><Inspect title={'logs/' + outputStep + '.log'} meta="readable execution log" value={'step=' + outputStep + ' action=mock status=' + currentOutput(index).status} text /><div className="h-2" /><Inspect title={'outputs/' + outputStep + '.json'} meta="deterministic step output" value={currentOutput(index)} /></>}</div>;
}

function Inspect({ title, meta, value, text=false }: { title:string; meta:string; value:unknown; text?:boolean }) {
  return <div className="overflow-hidden rounded-md border border-slate-700/55 bg-[#050d14]"><div className="flex min-h-9 items-center justify-between border-b border-slate-700/50 px-3 mono text-[8px] uppercase text-slate-600"><span>{title}</span><span>{meta}</span></div><pre className="max-h-64 overflow-auto whitespace-pre-wrap p-3 mono text-[9px] leading-5 text-slate-300">{text ? String(value) : JSON.stringify(value,null,2)}</pre></div>;
}

function HashView({ chain, hashes, tampered, setTampered }: { chain:{stepId:string;output:string;prev:string;hash:string}[]; hashes:string[]; tampered:boolean; setTampered:(value:boolean)=>void }) {
  return <div><Status bad={tampered} left={tampered ? 'Hash mismatch detected' : 'Chain matches recorded outputs'} right="Tamper-evident · SHA-256" /><button onClick={() => setTampered(!tampered)} className="action-warning mb-3"><Sparkles size={13} />{tampered ? 'Reset tamper demo' : 'Tamper demo'}</button><div className="space-y-3">{chain.map((record,index) => { const broken = tampered && index === 2; return <motion.div key={record.stepId} animate={{ borderColor:broken ? 'rgba(248,113,113,.6)' : 'rgba(51,65,85,.7)' }} className="rounded-md border bg-white/[.012] p-3"><div className="mb-2 flex items-center justify-between"><strong className="text-[11px]">{record.stepId}</strong><code className={'mono text-[8px] ' + (broken ? 'text-red-300' : 'text-cyan-300')}>{shortHash(broken ? hashes[index] + 'altered' : record.hash)}</code></div><div className="mono text-[8px] leading-5 text-slate-600">output_sha256={shortHash(record.output)}<br />prev_hash={record.prev ? shortHash(record.prev) : 'genesis'}</div>{broken && <div className="mono mt-2 text-[8px] text-red-300">Current output no longer matches the recorded output hash.</div>}</motion.div>; })}</div></div>;
}

function BundleView({ visible }: { visible:boolean }) {
  return <div><Status left="runs/demo-continuum-001/" right={visible ? 'assembled' : 'pending'} /><div className="space-y-1.5">{bundleFiles.map((file,index) => <motion.div key={file} initial={false} animate={{ opacity:visible ? 1 : .24, x:visible ? 0 : 7 }} transition={{ delay:index * .035 }} className="flex items-center gap-2 rounded-md border border-slate-700/55 bg-white/[.012] px-3 py-2 mono text-[8px]"><span className="h-1.5 w-1.5 border border-cyan-300 bg-cyan-300/10" /><span className="text-slate-300">{file}</span></motion.div>)}</div></div>;
}

function ReplayView({ drift, setDrift }: { drift:boolean; setDrift:(value:boolean)=>void }) {
  const [replaying,setReplaying] = useState(false);
  const sourceHash='e4f65a1de13795111847d6510287aa3812afe9e8a508434de19e1842e0a242fd';
  const replayHash=drift ? '97dce3fd19a4b427955e1c22da4cc87d380a69e17e09d33aa28b3d9c6ad7e201' : sourceHash;
  return <div><div className="mb-3 flex flex-wrap gap-2"><button onClick={() => { setReplaying(true); window.setTimeout(() => setReplaying(false),800); }} className="action-primary"><RotateCcw size={13} className={replaying ? 'animate-spin' : ''} />{replaying ? 'Replaying…' : 'Replay captured workflow'}</button><button onClick={() => setDrift(!drift)} className="action-warning"><Activity size={13} />{drift ? 'Reset drift simulation' : 'Simulate drift'}</button></div><ReplayCard label="Source run" name="demo-continuum-001" hash={sourceHash} /><div className="py-2 text-center mono text-[8px] uppercase text-cyan-300">inputs/workflow.yaml → replay</div><ReplayCard label="Replay run" name="replay-demo-continuum-001" hash={replayHash} /><div className={'mt-2 rounded-md border px-3 py-2.5 mono text-[8px] uppercase leading-5 ' + (drift ? 'border-red-300/30 bg-red-300/[.05] text-red-300' : 'border-emerald-300/25 bg-emerald-300/[.05] text-emerald-300')}>{drift ? 'Drift detected — output snapshots differ.' : 'No drift — output snapshots identical.'}<br />replay_report.json records both hashes.</div></div>;
}

function ReplayCard({ label, name, hash }: { label:string; name:string; hash:string }) {
  return <div className="rounded-md border border-slate-700/55 bg-white/[.012] p-3"><div className="mono text-[8px] uppercase tracking-[.1em] text-cyan-300">{label}</div><div className="mt-1 text-[11px] font-semibold">{name}</div><code className="mt-2 block break-all mono text-[8px] leading-4 text-slate-600">{hash}</code></div>;
}

function Status({ bad=false, left, right }: { bad?:boolean; left:string; right:string }) {
  return <div className={'mb-3 flex items-center justify-between gap-3 rounded-md border px-3 py-2 mono text-[8px] uppercase ' + (bad ? 'border-red-300/30 bg-red-300/[.05] text-red-300' : 'border-emerald-300/25 bg-emerald-300/[.05] text-emerald-300')}><span>{left}</span><span>{right}</span></div>;
}

export default App;
