package io.github.brew.visionassist

import androidx.compose.ui.Alignment
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Window
import androidx.compose.ui.window.WindowPosition
import androidx.compose.ui.window.application
import androidx.compose.ui.window.rememberWindowState
import dev.datlag.kcef.KCEF
import kotlin.system.exitProcess


fun main() = application {
    val windowState = rememberWindowState(
        size = DpSize(560.dp, 800.dp),
        position = WindowPosition(Alignment.Center),
    )
    Window(
        state = windowState,
        onCloseRequest = {
            // Shut down CEF cleanly, then terminate the process directly.
            //
            // We deliberately do NOT call exitApplication(): letting Compose dispose
            // the window removes JCEF's heavyweight AWT canvas (CefBrowserWr), which
            // invalidates an already-disposed SkiaLayer and throws "SkiaLayer is
            // disposed". Exiting the JVM here skips that teardown path entirely.
            KCEF.disposeBlocking()
            exitProcess(0)
        },
        title = "VisionAssist",
    ) {
        App()
    }
}
