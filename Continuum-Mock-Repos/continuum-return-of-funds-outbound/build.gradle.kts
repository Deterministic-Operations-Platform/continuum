plugins {
    application
}

repositories {
    mavenCentral()
}

java {
    toolchain {
        languageVersion.set(JavaLanguageVersion.of(17))
    }
}


dependencies {
    implementation("com.continuum.mock:continuum-common:1.0.0-mock")
    implementation("com.continuum.mock:continuum-config:1.0.0-mock")
    implementation("com.continuum.mock:continuum-integrations:1.0.0-mock")
    testImplementation("org.junit.jupiter:junit-jupiter:5.10.2")
}

application {
    mainClass.set("com.continuum.mock.Main")
}

tasks.test {
    useJUnitPlatform()
}
