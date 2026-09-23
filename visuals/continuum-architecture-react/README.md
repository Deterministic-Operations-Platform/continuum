# Continuum Architecture Experience — React

Portfolio-grade interactive visualization of Continuum's deterministic workflow path:

YAML/JSON → dependency DAG → deterministic execution → validation gates → evidence → logs/output snapshots → tamper-evident SHA-256 hash chain → run bundle → replay.

## Stack

- React + TypeScript
- Vite
- Tailwind CSS
- Framer Motion
- React Flow

## Run locally

npm install
npm run dev

## Product guardrails

- Vendor-neutral: no employer, bank, Jira, FedNow, MongoDB, or Postman coupling.
- Integrity is described as **tamper-evident**, not tamper-proof.
- Replay is represented as re-running the captured workflow snapshot and comparing output snapshots for drift.
- Demo data is local and deterministic.
- The illustrated workflow uses the real Continuum v0.1 workflow fields and supported mock action pattern.

## Vercel

The app includes a Vercel configuration and builds to Vite's dist directory. Set the Vercel project root directory to:

visuals/continuum-architecture-react
