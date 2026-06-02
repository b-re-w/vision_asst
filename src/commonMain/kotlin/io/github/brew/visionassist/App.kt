package io.github.brew.visionassist

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.safeContentPadding
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import com.multiplatform.webview.web.WebView
import com.multiplatform.webview.web.rememberWebViewState


@Composable
@Preview
fun App() {
    MaterialTheme {
        // The page is served from a loopback server (http://127.0.0.1) so it runs in a
        // secure context and getUserMedia works. On desktop we also wait for the WebView
        // backend (KCEF) to finish initializing.
        val backendReady = rememberWebViewReady()
        val serverUrl = rememberLocalServerUrl()
        if (backendReady && serverUrl != null) {
            val state = rememberWebViewState(serverUrl)
            WebView(
                state = state,
                modifier = Modifier
                    .safeContentPadding()
                    .fillMaxSize(),
                onCreated = { nativeWebView -> installWebViewConsoleLogger(nativeWebView) },
            )
        } else {
            Box(
                modifier = Modifier.fillMaxSize(),
                contentAlignment = Alignment.Center,
            ) {
                CircularProgressIndicator()
            }
        }
    }
}
