package io.github.brew.visionassist

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import io.ktor.http.ContentType
import io.ktor.http.HttpStatusCode
import io.ktor.http.withCharset
import io.ktor.server.application.ApplicationCall
import io.ktor.server.cio.CIO
import io.ktor.server.engine.embeddedServer
import io.ktor.server.response.respond
import io.ktor.server.response.respondBytes
import io.ktor.server.routing.get
import io.ktor.server.routing.routing
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.jetbrains.compose.resources.ExperimentalResourceApi
import visionassist.generated.resources.Res

/**
 * Serves the bundled web client (mirrored from `res/` into `composeResources/files/web`)
 * from a loopback HTTP server. Loading the page over `http://127.0.0.1` makes it a
 * secure context, so `getUserMedia` (camera/mic) works without any origin hacks — on
 * both Android and desktop. Static files only; the page talks to Gemini Live directly.
 */
private const val WEB_ROOT = "files/web"

// Process-global singleton so recompositions / config changes don't spawn servers.
private val startLock = Mutex()
private var baseUrl: String? = null

/** Starts the loopback server once and returns its base URL (e.g. http://127.0.0.1:54123). */
suspend fun ensureLocalWebServer(): String = startLock.withLock {
    baseUrl?.let { return it }
    val server = embeddedServer(CIO, port = 0, host = "127.0.0.1") {
        routing {
            get("/") { respondAsset(call, "index.html") }
            get("/res/{path...}") {
                respondAsset(call, call.parameters.getAll("path")?.joinToString("/").orEmpty())
            }
        }
    }
    server.start(wait = false)
    val port = server.engine.resolvedConnectors().first().port
    "http://127.0.0.1:$port".also { baseUrl = it }
}

@OptIn(ExperimentalResourceApi::class)
private suspend fun respondAsset(call: ApplicationCall, relativePath: String) {
    val name = relativePath.ifEmpty { "index.html" }
    val bytes = runCatching { Res.readBytes("$WEB_ROOT/$name") }.getOrNull()
    if (bytes == null) {
        call.respond(HttpStatusCode.NotFound)
        return
    }
    call.respondBytes(bytes, contentTypeFor(name))
}

private fun contentTypeFor(path: String): ContentType {
    val mime = when (path.substringAfterLast('.', "").lowercase()) {
        "html", "htm" -> "text/html"
        "js", "mjs" -> "text/javascript"
        "css" -> "text/css"
        "json" -> "application/json"
        "webmanifest" -> "application/manifest+json"
        "png" -> "image/png"
        "jpg", "jpeg" -> "image/jpeg"
        "svg" -> "image/svg+xml"
        "ico" -> "image/x-icon"
        else -> "application/octet-stream"
    }
    val type = ContentType.parse(mime)
    return if (mime.startsWith("text/") || mime.endsWith("json")) {
        type.withCharset(Charsets.UTF_8)
    } else {
        type
    }
}

/** Composable wrapper: returns the local server base URL once it's ready, else null. */
@Composable
fun rememberLocalServerUrl(): String? {
    var url by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(Unit) {
        url = withContext(Dispatchers.Default) { ensureLocalWebServer() }
    }
    return url
}
