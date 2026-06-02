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
            KCEF.init(
                builder = {
                    installDir(bundleDir)
                    settings {
                        cachePath = File(bundleDir, "cache").absolutePath
                    }
                    // Only render the WebView once CefApp is fully INITIALIZED —
                    // creating it earlier makes createContext() return null (NPE).
                    progress {
                        onInitialized { ready = true }
                    }
                    // The page is served over plain http, but getUserMedia (camera/mic)
                    // only works in a "secure context". The secure-context decision is
                    // made in the *renderer* subprocess, so the switch must be injected
                    // via onBeforeCommandLineProcessing (called for every process) — a
                    // browser-process-only arg does not reach the renderer.
                    appHandler(object : KCEF.AppHandler() {
                        override fun onBeforeCommandLineProcessing(
                            processType: String?,
                            commandLine: CefCommandLine?,
                        ) {
                            super.onBeforeCommandLineProcessing(processType, commandLine)
                            commandLine?.appendSwitchWithValue(
                                "unsafely-treat-insecure-origin-as-secure",
                                TARGET_ORIGIN,
                            )
                            // Auto-accept the media prompt (JCEF has no "Allow" UI).
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
