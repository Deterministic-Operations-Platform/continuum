plugins {
    kotlin("jvm") version "1.9.25"
    application
}

group = "com.continuum"
version = "0.1.0"

repositories {
    mavenCentral()
}

dependencies {
    implementation(kotlin("stdlib"))
}

kotlin {
    jvmToolchain(17)
}

application {
    mainClass.set("com.continuum.app.ApplicationKt")
}
