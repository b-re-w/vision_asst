package io.github.brew.visionassist

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.hoverable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsHoveredAsState
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.window.WindowDraggableArea
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.PointerEventType
import androidx.compose.ui.input.pointer.onPointerEvent
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.FrameWindowScope
import androidx.compose.ui.window.Window
import androidx.compose.ui.window.WindowPlacement
import androidx.compose.ui.window.WindowPosition
import androidx.compose.ui.window.WindowState
import androidx.compose.ui.window.application
import androidx.compose.ui.window.rememberWindowState
import com.sun.jna.CallbackReference
import com.sun.jna.Library
import com.sun.jna.Native
import com.sun.jna.NativeLibrary
import com.sun.jna.Pointer
import com.sun.jna.Structure
import com.sun.jna.platform.win32.User32
import com.sun.jna.platform.win32.WinDef
import com.sun.jna.platform.win32.WinUser
import com.sun.jna.ptr.IntByReference
import dev.datlag.kcef.KCEF
import kotlin.system.exitProcess


/** Shut CEF down cleanly, then kill the JVM directly (see onCloseRequest note). */
private fun closeApp(): Nothing {
    KCEF.disposeBlocking()
    exitProcess(0)
}

private fun toggleMaximize(windowState: WindowState) {
    windowState.placement =
        if (windowState.placement == WindowPlacement.Maximized) {
            WindowPlacement.Floating
        } else {
            WindowPlacement.Maximized
        }
}


fun main() = application {
    val windowState = rememberWindowState(
        size = DpSize(560.dp, 800.dp),
        position = WindowPosition(Alignment.Center),
    )
    Window(
        state = windowState,
        onCloseRequest = {
            // We deliberately do NOT call exitApplication(): letting Compose dispose
            // the window removes JCEF's heavyweight AWT canvas (CefBrowserWr), which
            // invalidates an already-disposed SkiaLayer and throws "SkiaLayer is
            // disposed". Exiting the JVM here skips that teardown path entirely.
            closeApp()
        },
        undecorated = true,
        title = "VisionAssist",
    ) {
        // Round the window corners (and add a native shadow on macOS) — the
        // undecorated window is square by default, so we ask the OS to reshape the
        // actual native window (Compose-level clipping can't touch the heavyweight
        // WebView canvas).
        LaunchedEffect(Unit) { applyNativeWindowChrome(window) }

        Column(Modifier.fillMaxSize()) {
            AppTitleBar(windowState)
            Box(Modifier.weight(1f).fillMaxWidth()) {
                App()
            }
        }
    }
}


private val TitleBarColor = Color(0xFF15151A)
private val TitleTextColor = Color(0xFFE8E8EC)

/** Custom in-app title bar (the window is undecorated). Drag to move; buttons on the right. */
@Composable
private fun FrameWindowScope.AppTitleBar(windowState: WindowState) {
    // Only allow drag-to-move while floating — dragging a maximized window should not
    // slide the maximized frame around.
    if (windowState.placement == WindowPlacement.Floating) {
        WindowDraggableArea { TitleBarRow(windowState) }
    } else {
        TitleBarRow(windowState)
    }
}

@OptIn(ExperimentalComposeUiApi::class)
@Composable
private fun TitleBarRow(windowState: WindowState) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(40.dp)
            .background(TitleBarColor),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        // Title region. Detect double-click WITHOUT consuming the event, so the
        // parent WindowDraggableArea still gets the drag (combinedClickable would
        // swallow the press and break drag-to-move).
        var lastPress by remember { mutableStateOf(0L) }
        Box(
            modifier = Modifier
                .weight(1f)
                .fillMaxHeight()
                .onPointerEvent(PointerEventType.Press) { event ->
                    val now = event.changes.first().uptimeMillis
                    if (now - lastPress in 1..300) {
                        toggleMaximize(windowState)
                        lastPress = 0L
                        // Consume so WindowDraggableArea doesn't also treat this
                        // press as a drag start (which would immediately move/
                        // restore the just-maximized window).
                        event.changes.forEach { it.consume() }
                    } else {
                        lastPress = now
                    }
                }
                .padding(start = 14.dp),
            contentAlignment = Alignment.CenterStart,
        ) {
            Text(
                text = "✦  Vision Assistant",
                color = TitleTextColor,
                fontSize = 13.sp,
                fontWeight = FontWeight.Medium,
            )
        }
        TitleBarButton(glyph = "—", onClick = { windowState.isMinimized = true })
        TitleBarButton(
            glyph = if (windowState.placement == WindowPlacement.Maximized) "❐" else "▢",
            onClick = { toggleMaximize(windowState) },
        )
        TitleBarButton(glyph = "✕", hoverColor = Color(0xFFE53935), onClick = { closeApp() })
    }
}

@Composable
private fun TitleBarButton(
    glyph: String,
    onClick: () -> Unit,
    hoverColor: Color = Color(0x33FFFFFF),
) {
    val interaction = remember { MutableInteractionSource() }
    val hovered by interaction.collectIsHoveredAsState()
    Box(
        modifier = Modifier
            .size(46.dp, 40.dp)
            .hoverable(interaction)
            .background(if (hovered) hoverColor else Color.Transparent)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(text = glyph, color = TitleTextColor, fontSize = 13.sp)
    }
}


// ─── Native window chrome (rounded corners + shadow) ────────────────────────────

private const val WINDOW_CORNER_RADIUS = 10.0

/** Reshape the native window per-OS. Best-effort; silently no-ops on failure. */
private fun applyNativeWindowChrome(window: java.awt.Window) {
    val os = System.getProperty("os.name").orEmpty()
    when {
        os.startsWith("Windows") -> applyWindowsChrome(window)
        os.startsWith("Mac") -> applyMacChrome(window)
        // Linux: corner rounding/shadow is compositor-dependent — left native-square.
    }
}

// --- Windows (DWM) ---

private const val DWMWA_WINDOW_CORNER_PREFERENCE = 33
private const val DWMWCP_ROUND = 2

private const val GWL_STYLE = -16
private const val GWLP_WNDPROC = -4
private const val WS_THICKFRAME = 0x00040000
private const val WM_NCCALCSIZE = 0x0083
private const val WM_WINDOWPOSCHANGED = 0x0047
private const val WM_DPICHANGED = 0x02E0
private const val WM_GETMINMAXINFO = 0x0024
private const val MONITOR_DEFAULTTONEAREST = 2
private const val SWP_NOSIZE = 0x0001
private const val SWP_NOMOVE = 0x0002
private const val SWP_NOZORDER = 0x0004
private const val SWP_FRAMECHANGED = 0x0020

// Strong references so JNA never garbage-collects the live window procedure / its
// original (collecting either would crash the native message pump).
private var subclassProc: WinUser.WindowProc? = null
private var originalWndProc: Pointer? = null

@Structure.FieldOrder("cxLeftWidth", "cxRightWidth", "cyTopHeight", "cyBottomHeight")
internal class MARGINS : Structure() {
    @JvmField var cxLeftWidth: Int = 0
    @JvmField var cxRightWidth: Int = 0
    @JvmField var cyTopHeight: Int = 0
    @JvmField var cyBottomHeight: Int = 0
}

private interface Dwmapi : Library {
    fun DwmSetWindowAttribute(
        hwnd: WinDef.HWND,
        dwAttribute: Int,
        pvAttribute: IntByReference,
        cbAttribute: Int,
    ): Int

    fun DwmExtendFrameIntoClientArea(hwnd: WinDef.HWND, margins: MARGINS): Int

    companion object {
        val INSTANCE: Dwmapi by lazy { Native.load("dwmapi", Dwmapi::class.java) }
    }
}

/**
 * Windows 11: round the window corners (DWM) and give the borderless window a native,
 * focus-aware drop shadow.
 *
 * The shadow needs the window to look "framed" to DWM, so we add WS_THICKFRAME and
 * extend the DWM frame across the whole client area (a "sheet of glass"). WS_THICKFRAME
 * also re-enables native edge resizing, which is fine here.
 */
private fun applyWindowsChrome(window: java.awt.Window) {
    runCatching {
        val hwnd = WinDef.HWND(Native.getWindowPointer(window))

        Dwmapi.INSTANCE.DwmSetWindowAttribute(
            hwnd,
            DWMWA_WINDOW_CORNER_PREFERENCE,
            IntByReference(DWMWCP_ROUND),
            4,
        )

        val style = User32.INSTANCE.GetWindowLong(hwnd, GWL_STYLE)
        User32.INSTANCE.SetWindowLong(hwnd, GWL_STYLE, style or WS_THICKFRAME)

        // "Sheet of glass" — extend the DWM frame across the whole client so DWM
        // draws the shadow but no visible frame remains.
        val margins = MARGINS().apply {
            cxLeftWidth = -1; cxRightWidth = -1; cyTopHeight = -1; cyBottomHeight = -1
        }
        fun extendFrame() = Dwmapi.INSTANCE.DwmExtendFrameIntoClientArea(hwnd, margins)

        // Subclass the window procedure to swallow WM_NCCALCSIZE — returning 0 makes
        // the client area span the whole window, removing the non-client border/title
        // strip that WS_THICKFRAME would otherwise paint (the white line). The DWM
        // shadow stays because the window still *has* the thick-frame style.
        //
        // Moving across monitors (especially with a DPI change) resets the DWM frame,
        // which makes the non-client strip reappear as white — so re-extend the frame
        // on WM_WINDOWPOSCHANGED / WM_DPICHANGED. (extendFrame() doesn't itself emit
        // WM_WINDOWPOSCHANGED, so there's no recursion.)
        val oldProc = Pointer(User32.INSTANCE.GetWindowLongPtr(hwnd, GWLP_WNDPROC).toLong())
        originalWndProc = oldProc
        val proc = object : WinUser.WindowProc {
            override fun callback(
                hWnd: WinDef.HWND,
                uMsg: Int,
                wParam: WinDef.WPARAM,
                lParam: WinDef.LPARAM,
            ): WinDef.LRESULT {
                if (uMsg == WM_NCCALCSIZE && wParam.toInt() != 0) {
                    // Client area spans the whole window (no non-client border). The
                    // maximized overhang is handled separately via WM_GETMINMAXINFO,
                    // which sizes the maximized window to the monitor work area.
                    return WinDef.LRESULT(0L)
                }
                val result = User32.INSTANCE.CallWindowProc(oldProc, hWnd, uMsg, wParam, lParam)
                when (uMsg) {
                    WM_WINDOWPOSCHANGED -> extendFrame()
                    WM_DPICHANGED -> {
                        extendFrame()
                        User32.INSTANCE.SetWindowPos(
                            hWnd, null, 0, 0, 0, 0,
                            SWP_NOMOVE or SWP_NOSIZE or SWP_NOZORDER or SWP_FRAMECHANGED,
                        )
                    }
                    WM_GETMINMAXINFO -> constrainMaximizeToWorkArea(hWnd, lParam)
                }
                return result
            }
        }
        subclassProc = proc
        User32.INSTANCE.SetWindowLongPtr(hwnd, GWLP_WNDPROC, CallbackReference.getFunctionPointer(proc))

        extendFrame()
        User32.INSTANCE.SetWindowPos(
            hwnd, null, 0, 0, 0, 0,
            SWP_NOMOVE or SWP_NOSIZE or SWP_NOZORDER or SWP_FRAMECHANGED,
        )
    }
}

/**
 * Clamp the maximized size to the current monitor's work area. A borderless window
 * otherwise maximizes to the full monitor *plus* the resize-frame overhang, pushing the
 * title bar off-screen. Writes ptMaxSize / ptMaxPosition in the MINMAXINFO at [lParam].
 */
private fun constrainMaximizeToWorkArea(hWnd: WinDef.HWND, lParam: WinDef.LPARAM) {
    runCatching {
        val monitor = User32.INSTANCE.MonitorFromWindow(hWnd, MONITOR_DEFAULTTONEAREST)
        val info = WinUser.MONITORINFO()
        info.cbSize = info.size()
        if (!User32.INSTANCE.GetMonitorInfo(monitor, info).booleanValue()) return
        val work = info.rcWork
        val mon = info.rcMonitor
        val p = Pointer(lParam.toLong()) // MINMAXINFO
        p.setInt(8, work.right - work.left)   // ptMaxSize.x
        p.setInt(12, work.bottom - work.top)  // ptMaxSize.y
        p.setInt(16, work.left - mon.left)    // ptMaxPosition.x
        p.setInt(20, work.top - mon.top)      // ptMaxPosition.y
    }
}

// --- macOS (NSWindow via the Objective-C runtime) ---

private val objc: NativeLibrary by lazy { NativeLibrary.getInstance("objc") }
private fun sel(name: String): Pointer = objc.getFunction("sel_registerName").invokePointer(arrayOf(name))
private fun cls(name: String): Pointer = objc.getFunction("objc_getClass").invokePointer(arrayOf(name))
private fun send(receiver: Pointer, selector: String): Pointer =
    objc.getFunction("objc_msgSend").invokePointer(arrayOf(receiver, sel(selector)))
private fun sendVoid(receiver: Pointer, selector: String, arg: Any) {
    objc.getFunction("objc_msgSend").invokeVoid(arrayOf(receiver, sel(selector), arg))
}

/**
 * macOS: give the borderless NSWindow a native shadow and round the content layer.
 *
 * NOTE: untested on macOS hardware. If corners/shadow don't appear, the likely cause
 * is [Native.getWindowPointer] returning the NSView rather than the NSWindow — in that
 * case fetch the window with `send(handle, "window")` first.
 */
private fun applyMacChrome(window: java.awt.Window) {
    runCatching {
        val nsWindow = Native.getWindowPointer(window) ?: return
        // Native drop shadow (focus-aware, drawn by the OS).
        sendVoid(nsWindow, "setHasShadow:", 1)
        // Make the window non-opaque with a clear background so the rounded corners
        // aren't filled in by the square window backdrop.
        sendVoid(nsWindow, "setOpaque:", 0)
        sendVoid(nsWindow, "setBackgroundColor:", send(cls("NSColor"), "clearColor"))
        // Round the content view's layer.
        val contentView = send(nsWindow, "contentView")
        sendVoid(contentView, "setWantsLayer:", 1)
        val layer = send(contentView, "layer")
        sendVoid(layer, "setCornerRadius:", WINDOW_CORNER_RADIUS)
        sendVoid(layer, "setMasksToBounds:", 1)
    }
}
