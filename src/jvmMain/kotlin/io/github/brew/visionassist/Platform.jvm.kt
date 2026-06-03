package io.github.brew.visionassist

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import dev.datlag.kcef.KCEF
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.cef.callback.CefCommandLine
import java.io.File

class JVMPlatform: Platform {
    override val name: String = "Java ${System.getProperty("java.version")}"
}

actual fun getPlatform(): Platform = JVMPlatform()

@Composable
actual fun rememberWebViewReady(): Boolean {
    var ready by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        withContext(Dispatchers.IO) {
            // Downloads/extracts the Chromium bundle on first run. Keep it under
            // build/ (gitignored, cleaned by `gradlew clean`) instead of the repo root.
            val bundleDir = File("build/kcef-bundle")
            // A bundle installed before this fix (or by a crashed run) may already have
            // install.lock written with the framework misplaced — KCEF then skips
            // install entirely, so repair here too, before init.
            repairMacBundle(bundleDir)
            KCEF.init(
                builder = {
                    installDir(bundleDir)
                    settings {
                        cachePath = File(bundleDir, "cache").absolutePath
                    }
                    // Only render the WebView once CefApp is fully INITIALIZED —
                    // creating it earlier makes createContext() return null (NPE).
                    progress {
                        onDownloading { pct -> println("[KCEF] downloading Chromium bundle: $pct%") }
                        onExtracting { println("[KCEF] extracting bundle…") }
                        onInstall {
                            println("[KCEF] installing bundle…")
                            // Fires after extract+move but before CefInitializer runs,
                            // so fixing the layout here makes a fresh install succeed
                            // on the first run.
                            repairMacBundle(bundleDir)
                        }
                        onInitialized {
                            println("[KCEF] initialized")
                            ready = true
                        }
                    }
                    // The page loads from http://127.0.0.1 (a secure context), so no
                    // origin hack is needed. We still auto-accept the media prompt
                    // because JCEF has no UI to click "Allow".
                    appHandler(object : KCEF.AppHandler() {
                        override fun onBeforeCommandLineProcessing(
                            processType: String?,
                            commandLine: CefCommandLine?,
                        ) {
                            super.onBeforeCommandLineProcessing(processType, commandLine)
                            commandLine?.appendSwitch("use-fake-ui-for-media-stream")
                        }
                    })
                },
                onError = { it?.printStackTrace() },
            )
        }
    }

    // NOTE: KCEF is disposed in main()'s onCloseRequest (before the window tears
    // down) rather than here — disposing during composition teardown races with
    // JCEF's AWT canvas removal and throws "SkiaLayer is disposed" on exit.

    return ready
}

/**
 * Work around a KCEF macOS extraction bug. KCEF's archive flattening (`TarGzExtractor`)
 * leaves the CEF framework and JCEF helper apps buried in
 * `Frameworks/cef_server.app/Contents/Frameworks/` instead of directly under
 * `Frameworks/`, where JCEF's CefInitializer looks for them. dlopen then fails with
 * "Chromium Embedded Framework (no such file)" and the JVM dies with SIGSEGV.
 *
 * This hoists the nested entries up to `Frameworks/`. The framework and the helper apps
 * are moved together, so the helpers' relative @rpath references stay valid. Idempotent:
 * once the framework sits at the top level it returns immediately.
 *
 * No-op on non-macOS platforms (Windows/Linux extract correctly).
 */
private fun repairMacBundle(bundleDir: File) {
    if (!System.getProperty("os.name").orEmpty().startsWith("Mac")) return

    val frameworks = File(bundleDir, "Frameworks")
    // Already correct? (also covers the case where a previous run/manual fix moved it)
    if (File(frameworks, "Chromium Embedded Framework.framework").exists()) return

    val nested = File(frameworks, "cef_server.app/Contents/Frameworks")
    if (!File(nested, "Chromium Embedded Framework.framework").exists()) return // nothing to fix

    nested.listFiles()?.forEach { entry ->
        val target = File(frameworks, entry.name)
        if (target.exists()) return@forEach
        // Same volume (both under Frameworks/), so this is an instant move that keeps
        // the exec bits the helper executables need. A copy would drop them and produce
        // a subtly-broken bundle, so surface the failure instead of degrading silently.
        if (!entry.renameTo(target)) {
            println("[KCEF] WARNING: failed to move ${entry.name} into Frameworks/ — CEF may not start")
        }
    }
    println("[KCEF] repaired macOS bundle: hoisted framework + helpers into Frameworks/")
}
