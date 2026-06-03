package io.github.brew.visionassist

import com.multiplatform.webview.web.NativeWebView

actual fun onWebViewCreated(webView: NativeWebView) {
    // Opaque dark background so any unpainted region is dark, not garbage.
    webView.setBackgroundColor(0xFF06090F.toInt())
}
