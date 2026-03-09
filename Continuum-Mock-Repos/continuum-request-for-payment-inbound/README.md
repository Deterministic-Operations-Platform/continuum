# continuum-request-for-payment-inbound

Standalone mock repository in the Continuum company-style multi-repo workspace.

## Repository intent
- Domain: `request-for-payment`
- Direction: `inbound`
- Owned and built independently from sibling repos.

## Local structure
- `settings.gradle.kts`
- `build.gradle.kts`
- `src/main/java/com/continuum/mock/Main.java`
- `src/main/java/com/continuum/mock/handler/*`
- `src/main/resources/application.yaml`
- `src/main/resources/mock-scenarios.json`
- `.repo-engine.yaml`

## Git setup (independent repo)
```bash
git init
git add .
git commit -m "Initialize continuum-request-for-payment-inbound"
```

## Build/run (inside this repo only)
```bash
gradle run
```
