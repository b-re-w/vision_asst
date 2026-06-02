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
        // On desktop the WebView backend (KCEF/Chromium) must finish initializing
        // before the WebView can render; on Android this is always ready.
        if (rememberWebViewReady()) {
            val state = rememberWebViewState(TARGET_URL)
            WebView(
                state = state,
                modifier = Modifier
                    .safeContentPadding()
                    .fillMaxSize(),
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
