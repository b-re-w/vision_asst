package io.github.brew.visionassist

import android.Manifest
import android.graphics.Color
import android.os.Bundle
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

    override fun onCreate(savedInstanceState: Bundle?) {
        // Dark system bars → light (white) icons, so the clock is visible against the
        // app's dark background.
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
        )
        super.onCreate(savedInstanceState)

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
