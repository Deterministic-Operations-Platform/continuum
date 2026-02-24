# Canonical scenario schema (v0.1)

```yaml
name: string
rail: string
vars: {}               # optional
services: {}           # optional
governance: {}         # optional
steps:                 # required, non-empty
  - name: string
    type: string
    key: string        # optional (or id)
    id: string         # optional (alias for key)
    with: {}           # optional input payload
    always: false      # optional
    dependsOn: []      # optional array of step keys
    retry:             # optional
      on: [exception]
      maxAttempts: 1
      backoff: fixed
      baseDelayMs: 0
      maxDelayMs: 0
      jitter: 0.0
    publish:           # optional map of vars from $.details.*
      outputVar: $.details.some.field
cleanup_steps:         # optional
  - name: string
    type: string
    with: {}
```
