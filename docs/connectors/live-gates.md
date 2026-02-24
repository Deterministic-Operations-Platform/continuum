# Live connector gates (Jira and Mongo)

Jira and Mongo plugins default to safe/stub mode. To execute live calls:

- Set `with.live: true` on the step.
- Set runtime gate env var: `CONTINUUM_ENABLE_LIVE_CONNECTORS=1`
  - Or connector-specific: `CONTINUUM_ENABLE_LIVE_JIRA=1`, `CONTINUUM_ENABLE_LIVE_MONGO=1`
- For Jira live mode, also set:
  - `JIRA_BASE_URL`
  - `JIRA_EMAIL`
  - `JIRA_API_TOKEN`
