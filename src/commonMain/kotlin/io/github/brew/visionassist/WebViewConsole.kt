package io.github.brew.visionassist

import com.multiplatform.webview.web.NativeWebView

/**
 * Forward the page's `console.*` output to the app's stdout/log.
 *
 * Desktop (JCEF) attaches a CefDisplayHandler. Android is a no-op — use Chrome's
 * chrome://inspect instead (WebView debugging is enabled in MainActivity).
 */
expect fun installWebViewConsoleLogger(webView: NativeWebView)
