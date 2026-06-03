package io.github.brew.visionassist

import com.multiplatform.webview.web.NativeWebView

actual fun onWebViewCreated(webView: NativeWebView) {
    // Opaque dark background: stops the camera video overlay from flashing its default
    // (blue/black) color during repaints. Console: use chrome://inspect.
    webView.setBackgroundColor(0xFF06090F.toInt())
}
