package io.github.brew.visionassist

import androidx.compose.runtime.Composable


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
