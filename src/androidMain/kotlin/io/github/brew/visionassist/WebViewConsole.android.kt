package io.github.brew.visionassist

import com.multiplatform.webview.web.NativeWebView

// Console forwarding on Android would require replacing the library's WebChromeClient
// (which handles camera/mic permission grants), so instead use chrome://inspect.
actual fun installWebViewConsoleLogger(webView: NativeWebView) {
    // no-op
}
