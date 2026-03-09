# continuum-config

Lightweight standalone scaffold for the **continuum-config** service.

## Run

```bash
./gradlew run
```

## Structure

- `src/main/kotlin` : application entrypoint + handler/service.
- `src/main/resources/application.yml` : local configuration.
- `build.gradle.kts` + `settings.gradle.kts` : standalone Gradle build.
