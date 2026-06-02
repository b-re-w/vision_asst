import org.jetbrains.compose.desktop.application.dsl.TargetFormat
import org.jetbrains.kotlin.gradle.dsl.JvmTarget


plugins {
    alias(libs.plugins.androidApplication)
    alias(libs.plugins.kotlinMultiplatform)
    alias(libs.plugins.composeMultiplatform)
    alias(libs.plugins.composeCompiler)
}


kotlin {
    jvm()

    androidTarget {
        compilerOptions {
            jvmTarget = JvmTarget.JVM_11
        }
    }

    sourceSets {
        androidMain.dependencies {
            implementation(libs.compose.uiToolingPreview)
            implementation(libs.androidx.activity.compose)

            // ui-tooling renders Compose previews at runtime; Android-only, off the compile classpath.
            runtimeOnly(libs.compose.uiTooling)
        }
        jvmMain.dependencies {
            implementation(compose.desktop.currentOs)
            implementation(libs.kotlinx.coroutinesSwing)

            implementation(libs.compose.uiToolingPreview)

            // KCEF: desktop WebView backend (downloads a Chromium bundle on first run).
            implementation(libs.kcef)

            // JNA: call Windows DWM APIs for rounded window corners.
            implementation(libs.jna)
            implementation(libs.jna.platform)
        }
        commonMain.dependencies {
            implementation(libs.compose.runtime)
            implementation(libs.compose.foundation)
            implementation(libs.compose.material3)
            implementation(libs.compose.ui)
            implementation(libs.compose.components.resources)
            implementation(libs.compose.uiToolingPreview)
            implementation(libs.androidx.lifecycle.viewmodelCompose)
            implementation(libs.androidx.lifecycle.runtimeCompose)

            // Cross-platform WebView (Android + Desktop).
            implementation(libs.compose.webview.multiplatform)

            // Embedded HTTP server to serve the bundled web client from localhost
            // (a secure context, so getUserMedia works without origin hacks).
            implementation(libs.ktor.server.core)
            implementation(libs.ktor.server.cio)
        }
        commonTest.dependencies {
            implementation(libs.kotlin.test)
        }
    }
}


android {
    namespace = "io.github.brew.visionassist"
    compileSdk = libs.versions.android.compileSdk.get().toInt()

    defaultConfig {
        applicationId = "io.github.brew.visionassist"
        minSdk = libs.versions.android.minSdk.get().toInt()
        targetSdk = libs.versions.android.targetSdk.get().toInt()
        versionCode = 1
        versionName = "1.0"
    }
    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
    buildTypes {
        getByName("release") {
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
}


// ─── Bundle the web client into the app ──────────────────────────────────────────
// `res/` is the single source of truth (also served by the Python server). Mirror it
// into Compose resources (files/web) so the in-app Ktor server can serve it via
// Res.readBytes on both Android and desktop. Large demo videos are excluded.
val syncWebAssets by tasks.registering(Sync::class) {
    from(layout.projectDirectory.dir("res")) {
        exclude("**/*.mp4")
    }
    into(layout.projectDirectory.dir("src/commonMain/composeResources/files/web"))
}

// Ensure the mirror exists before Compose collects/packages/indexes resources
// (covers prepareComposeResources*, copyNonXmlValueResources*, convertXmlValueResources*,
// generateResourceAccessors* across all source sets).
tasks.matching { t ->
    t.name != "syncWebAssets" && (
        t.name.contains("ComposeResources", ignoreCase = true) ||
            t.name.contains("ValueResources", ignoreCase = true) ||
            t.name.contains("ResourceAccessors", ignoreCase = true)
    )
}.configureEach { dependsOn(syncWebAssets) }


compose.desktop {
    application {
        mainClass = "io.github.brew.visionassist.MainKt"

        // KCEF / JCEF needs these module openings to launch the Chromium process.
        jvmArgs += listOf(
            "--add-opens", "java.desktop/sun.awt=ALL-UNNAMED",
            "--add-opens", "java.desktop/java.awt.peer=ALL-UNNAMED",
        )

        // macOS: CEF's message loop must run on the AppKit main thread (thread 0).
        // Without this, JCEF initializes CefApp on a background thread and crashes
        // with SIGSEGV in libjcef. (No-op / unneeded on Windows and Linux.)
        if (System.getProperty("os.name").startsWith("Mac")) {
            jvmArgs += "-XstartOnFirstThread"
        }

        nativeDistributions {
            targetFormats(TargetFormat.Dmg, TargetFormat.Msi, TargetFormat.Deb)
            packageName = "io.github.brew.visionassist"
            packageVersion = "1.0.0"
        }

        application {
            buildTypes.release.proguard {
                isEnabled = false
            }
        }
    }
}
