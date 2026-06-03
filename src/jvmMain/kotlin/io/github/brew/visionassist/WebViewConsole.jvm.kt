package io.github.brew.visionassist

import com.multiplatform.webview.web.NativeWebView
import org.cef.CefSettings
import org.cef.browser.CefBrowser
import org.cef.handler.CefDisplayHandlerAdapter

actual fun onWebViewCreated(webView: NativeWebView) {
    // IMPORTANT: JCEF's CefClient.addDisplayHandler only keeps the *first* handler
    // registered. This runs from onCreated — i.e. BEFORE the library registers its
    // own (no-op) display handler — so ours wins. Do NOT defer it.
    webView.client.addDisplayHandler(object : CefDisplayHandlerAdapter() {
        override fun onConsoleMessage(
            browser: CefBrowser?,
            level: CefSettings.LogSeverity?,
            message: String?,
            source: String?,
            line: Int,
        ): Boolean {
            val tag = level?.name?.removePrefix("LOGSEVERITY_") ?: "LOG"
            val src = source?.substringAfterLast('/').orEmpty()
            println("[web $tag] $src:$line  $message")
            return false // let default handling proceed too
        }
    })
}
