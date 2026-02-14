# Architecture (starter)

**Core loop**
1. Ingest work (Jira issue / incident / change request)
2. Plan actions (policy + templates + guardrails)
3. Execute actions (repo changes, tests, DB verification, evidence capture)
4. Review gates (quality, security, approvals)
5. Ship (PR/merge/deploy) and log outcomes

**Core components**
- Orchestrator API (workflow engine)
- Connector runtime (Jira/GitHub/Postman/DB/CI)
- Evidence store (logs, screenshots, test reports)
- Policy engine (what’s allowed per team/environment)
