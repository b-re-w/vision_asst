package io.github.brew.visionassist

import android.Manifest
import android.graphics.Color
import android.media.AudioManager
import android.os.Bundle
import android.view.KeyEvent
import android.webkit.WebView
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.ui.tooling.preview.Preview


class MainActivity : ComponentActivity() {

    // The WebView only grants the page's camera/mic request if the matching OS
    // permission is already held, so ask for them up front.
    private val permissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { }

    private val audioManager by lazy { getSystemService(AUDIO_SERVICE) as AudioManager }

    // getUserMedia (with AEC) puts the system in communication mode, where Android
    // forces the hardware volume keys to the call stream — overriding volumeControlStream.
    // The actual playback is on the MEDIA stream, so intercept the volume keys ourselves,
    // adjust MEDIA volume, and consume the event so the call-volume UI never shows.
    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        when (event.keyCode) {
            KeyEvent.KEYCODE_VOLUME_UP, KeyEvent.KEYCODE_VOLUME_DOWN -> {
                if (event.action == KeyEvent.ACTION_DOWN) {
                    val direction =
                        if (event.keyCode == KeyEvent.KEYCODE_VOLUME_UP) AudioManager.ADJUST_RAISE
                        else AudioManager.ADJUST_LOWER
                    audioManager.adjustStreamVolume(
                        AudioManager.STREAM_MUSIC, direction, AudioManager.FLAG_SHOW_UI,
                    )
                }
                return true // consume so the system doesn't route to the call stream
            }
        }
        return super.dispatchKeyEvent(event)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        // Dark system bars → light (white) icons, so the clock is visible against the
        // app's dark background.
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
        )
        super.onCreate(savedInstanceState)

        // Audio output is on the MEDIA stream, but getUserMedia puts Chromium into
        // communication audio mode, which makes the hardware volume keys control the
        // call stream. Force the keys to always adjust media volume.
        volumeControlStream = AudioManager.STREAM_MUSIC

        // Allow inspecting the WebView from desktop Chrome via chrome://inspect, so we
        // can read the page's console (e.g. whether getUserMedia / mediaDevices works).
        WebView.setWebContentsDebuggingEnabled(true)

        permissionLauncher.launch(
            arrayOf(Manifest.permission.CAMERA, Manifest.permission.RECORD_AUDIO),
        )

        setContent {
            App()
        }
    }
}


@Preview
@Composable
fun AppAndroidPreview() {
    App()
}
