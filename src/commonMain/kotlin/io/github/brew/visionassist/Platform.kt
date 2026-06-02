package io.github.brew.visionassist

import androidx.compose.runtime.Composable


/** The page the WebView always loads. */
internal const val TARGET_URL = "http://cuws.duckdns.org:8000"

/** Scheme + host + port of [TARGET_URL] (used for the desktop secure-origin flag). */
internal const val TARGET_ORIGIN = "http://cuws.duckdns.org:8000"


interface Platform {
    val name: String
}

expect fun getPlatform(): Platform

/**
 * Whether the platform's WebView backend is ready to render.
 *
 * Android returns `true` immediately. Desktop initializes KCEF (Chromium) on
 * first use and only returns `true` once that finishes.
 */
@Composable
expect fun rememberWebViewReady(): Boolean
