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
                        onDownloading { pct -> println("[KCEF] downloading Chromium bundle: $pct%") }
                        onExtracting { println("[KCEF] extracting bundle…") }
                        onInstall { println("[KCEF] installing bundle…") }
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
