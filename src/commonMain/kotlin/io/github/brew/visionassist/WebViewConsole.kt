package io.github.brew.visionassist

import com.multiplatform.webview.web.NativeWebView

/**
 * Platform hook invoked once the native WebView is created.
 *
 * Desktop (JCEF): attach a CefDisplayHandler that forwards `console.*` to stdout.
 * Android: paint an opaque dark background so the camera video overlay doesn't flash
 * (use chrome://inspect for the console; WebView debugging is enabled in MainActivity).
 */
expect fun onWebViewCreated(webView: NativeWebView)
