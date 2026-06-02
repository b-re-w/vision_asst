package io.github.brew.visionassist

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.tooling.preview.Preview
import com.multiplatform.webview.web.WebView
import com.multiplatform.webview.web.rememberWebViewState


// Matches the web page background so system-bar insets / load flashes aren't white.
private val AppBackground = Color(0xFF06090F)


@Composable
@Preview
fun App() {
    MaterialTheme {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(AppBackground),
            contentAlignment = Alignment.Center,
        ) {
            // The page is served from a loopback server (http://127.0.0.1) so it runs in
            // a secure context and getUserMedia works. On desktop we also wait for the
            // WebView backend (KCEF) to finish initializing.
            val backendReady = rememberWebViewReady()
            val serverUrl = rememberLocalServerUrl()
            if (backendReady && serverUrl != null) {
                val state = rememberWebViewState(serverUrl)
                WebView(
                    state = state,
                    // Fill the window, but push content below the status bar only, so
                    // the clock doesn't overlap it. The inset region shows the dark root
                    // background (not white).
                    modifier = Modifier
                        .statusBarsPadding()
                        .fillMaxSize(),
                    onCreated = { nativeWebView -> installWebViewConsoleLogger(nativeWebView) },
                )
            } else {
                CircularProgressIndicator()
            }
        }
    }
}
