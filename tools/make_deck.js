const pptxgen = require("pptxgenjs");

const deck = new pptxgen();
deck.layout = "LAYOUT_WIDE";
deck.author = "Continuum";
deck.company = "Continuum";
deck.subject = "Investor Deck";
deck.title = "Continuum Investor Deck";

const FONT = "Aptos";
const COLORS = {
  bg: "0B1220",
  panel: "111A2E",
  accent: "4F8CFF",
  text: "FFFFFF",
  muted: "B9C2D6",
  line: "223055",
};

function titleSlide(title, subtitle) {
  const s = deck.addSlide();
  s.background = { color: COLORS.bg };

  s.addText("Continuum", {
    x: 0.85,
    y: 0.7,
    w: 12,
    h: 0.6,
    fontFace: FONT,
    fontSize: 18,
    bold: true,
    color: COLORS.accent,
  });

  s.addText(title, {
    x: 0.85,
    y: 1.4,
    w: 12,
    h: 1.0,
    fontFace: FONT,
    fontSize: 38,
    bold: true,
    color: COLORS.text,
  });

  s.addText(subtitle, {
    x: 0.85,
    y: 2.35,
    w: 11.5,
    h: 0.7,
    fontFace: FONT,
    fontSize: 16,
    color: COLORS.muted,
  });

  s.addShape(deck.ShapeType.line, {
    x: 0.85,
    y: 3.25,
    w: 11.6,
    h: 0,
    line: { color: COLORS.line, width: 1 },
  });

  s.addText("Deterministic Runs | Audit-Ready Proof | Policy Gates", {
    x: 0.85,
    y: 3.45,
    w: 12,
    h: 0.4,
    fontFace: FONT,
    fontSize: 14,
    color: COLORS.muted,
  });
}

function bulletSlide(title, bullets) {
  const s = deck.addSlide();
  s.background = { color: COLORS.bg };

  s.addText(title, {
    x: 0.85,
    y: 0.7,
    w: 12,
    h: 0.6,
    fontFace: FONT,
    fontSize: 28,
    bold: true,
    color: COLORS.text,
  });

  s.addShape(deck.ShapeType.roundRect, {
    x: 0.85,
    y: 1.55,
    w: 11.6,
    h: 5.5,
    fill: { color: COLORS.panel },
    line: { color: COLORS.line, width: 1 },
  });

  s.addText(bullets.join("\n"), {
    x: 1.25,
    y: 1.9,
    w: 10.9,
    h: 5.0,
    fontFace: FONT,
    fontSize: 16,
    color: COLORS.text,
    bullet: { indent: 22 },
    paraSpaceAfter: 10,
  });
}

titleSlide(
  "The Evidence-First Engineering Ops Control Plane",
  "Turn high-stakes engineering work into deterministic, replayable Runs with audit-ready proof."
);

bulletSlide("The Pain (what banks live with)", [
  "Manual orchestration across Jira, Git, CI, Postman/Newman, logs, and DB verification",
  "Slow cycle time: repeated restarts, reruns, and tribal runbooks",
  "Inconsistent verification and fragile environments",
  "Audit evidence is manual, incomplete, and non-standard",
]);

bulletSlide("Why it's hard", [
  "Many services, many repos, many dependencies, shared environments",
  "Controls, approvals, and incident pressure add friction",
  "Pipelines don't capture real operational workflows or proof",
]);

bulletSlide("The Insight", [
  "Banks don't just ship code - they must prove safety and correctness",
  "The missing primitive is a Run: inputs -> plan -> execution -> verification -> evidence -> publish",
  "When proof is automatic, speed and safety stop being a tradeoff",
]);

bulletSlide("The Product", [
  "Scenario-as-data: deterministic plans (serial + parallel) from a single workflow definition",
  "Plugin runtime: lifecycle | transport | verification | evidence collection",
  "Policy gates: required tests/checks/evidence before sign-off",
  "Publish: HTML report + JSON summary back to Jira/CI",
]);

bulletSlide("What a Run outputs (the receipt)", [
  "Evidence bundle: scenario snapshot, per-step inputs/outputs, logs, DB assertions, test reports",
  "Tamper-evident manifest (hashes) + structured summary (pass/fail + root cause)",
  "Trace correlation across tests/logs/data so verification is explainable",
]);

bulletSlide("Value to financial companies", [
  "Cycle-time compression: less orchestration, fewer reruns",
  "Lower risk: standardized verification and enforced gates",
  "Incident speed + proof: repeatable playbooks with automatic evidence capture",
  "Audit readiness by default: consistent receipts for changes and incidents",
]);

bulletSlide("Beachhead -> platform", [
  "Beachhead: payments-grade workflows (FedNow/RTP regressions, RoF, integration verification)",
  "Expand: fraud/risk, identity/KYC/AML, core banking integrations, regulated change control",
  "Anywhere you need repeatable execution + proof, Continuum fits",
]);

bulletSlide("Moat", [
  'Evidence format becomes the internal standard ("the receipt")',
  "Policy engine becomes the control point for what can ship",
  "Scenario library/playbook network effects across teams and systems",
]);

bulletSlide("Go-to-Market", [
  "Land bottom-up with engineering teams (productivity + receipts)",
  "Expand to platform/payments ops (governance + standard verification)",
  "Enterprise rollout with policies, approvals, and audit reporting",
]);

deck
  .writeFile({ fileName: "Continuum_Investor_Deck.pptx" })
  .then(() => console.log("Wrote Continuum_Investor_Deck.pptx"));
