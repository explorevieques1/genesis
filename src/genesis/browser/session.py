# Spec: Genesis Markdown/10-Architecture/Web Access.md §The presentation surface
"""One real Chromium, driven over CDP, painted into a Dockview panel.

[[Web Access]] already specifies this surface — *"a Dockview panel inside the
Genesis shell, not a separate browser window"* — and assigns its lifecycle to a
Tauri Rust host. **There is no Tauri host.** The shell is a page served by vite,
and a page cannot frame an arbitrary site: `X-Frame-Options` and
`frame-ancestors` mean the half of the web worth surfing renders as a blank box.

So the pixels come the other way round. Chromium runs headless beside the
daemon, the panel shows a JPEG stream of its viewport, and clicks and keys go
back over HTTP. It is a remote desktop of one browser window. That is worse
than a native WebView in exactly one way that survived measurement — text is
JPEG rather than subpixel — and better in every other way that matters here: it
works in the browser shell that exists today, and it keeps a profile, so the
subscription you pay for is logged in and stays logged in.

Frames come from `Page.startScreencast` on a **second** socket, not from
screenshots on this one. See `screencast.py`: that change took a TradingView
chart from 5 fps to 37 and took clicks out from behind the frame queue. The
first version did the obvious thing and it was the wrong thing.

**Nothing here is a tool.** [[Web Access]] §Wiring is explicit that presentation
is not one, and that an agent declaring `display.*` fails at boot. The defence
is structural rather than promised: there is no MCP server in this package, no
capability registered, and no orchestrator verb wired to it. The only caller is
the panel, and the only hand on the mouse is yours. That also settles the
question the TradingView CDP client had to answer with a deny-list
(`tradingview/cdp.py`): a browser you are clicking in yourself is not an
automation client that can reach a Buy button, because nothing but you is
clicking. Wire an agent to this and that stops being true — which is why the
route module says so too.

**The profile is persistent and that is a deliberate departure from the note.**
[[Web Access]] §Wiring configures `partition: ephemeral` and the acceptance
criteria say the display WebView holds no cookies across a close. That posture
suits a page summoned to be read once. It cannot deliver a logged-in charting
platform, which is the thing actually asked for. The note is updated to match.
"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from genesis.errors import DegradedError
from genesis.browser.screencast import Screencast
from genesis.tradingview.cdp import CDPSession, CDPUnavailable, targets, version

__all__ = [
    "BrowserUnavailable",
    "KEYS",
    "BrowserSession",
    "close",
    "resolve_url",
    "session",
]

#: Not 9222 — that is TradingView Desktop's, and two Chromiums on one port is a
#: coin flip over which one a tool reaches.
DEFAULT_PORT = int(os.environ.get("GENESIS_BROWSER_PORT", "9223"))

#: Its own profile, so logins survive a restart and nothing here touches the
#: daily-driver Chrome — which would refuse to start a second instance on a
#: profile it already holds.
PROFILE_DIR = Path(os.environ.get("GENESIS_BROWSER_PROFILE", "~/.genesis/browser"))

#: Headless by default: a stray Chromium window on the desktop is a window over
#: the trading layout, which [[Web Access]] names as the hazard panels exist to
#: avoid. `GENESIS_BROWSER_HEADLESS=0` shows the real window, which is worth
#: knowing about — a handful of sites still refuse headless outright.
HEADLESS = os.environ.get("GENESIS_BROWSER_HEADLESS", "1") != "0"

#: First one installed wins.
BINARIES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "brave", "microsoft-edge")

LAUNCH_TIMEOUT_SEC = 20.0

#: JPEG, not PNG. A 1600×900 viewport is ~2.5 MB of PNG and ~120 KB at this
#: quality, and the difference is the whole feasibility of streaming it.
QUALITY = 60

#: What the address bar does with something that is not a URL.
# ponytail: fixed engine; read `web.search.endpoint` from config if the
# self-hosted SearXNG in [[Web Access]] ever lands.
SEARCH = "https://duckduckgo.com/?q={}"

#: Keys that are an instruction rather than a character. Everything printable
#: goes through `Input.insertText`, which needs no table and gets dead keys,
#: IMEs and pasted emoji right for free — the reason this list is short.
KEYS: dict[str, tuple[int, str]] = {
    "Enter": (13, "Enter"),
    "Backspace": (8, "Backspace"),
    "Tab": (9, "Tab"),
    "Escape": (27, "Escape"),
    "Delete": (46, "Delete"),
    "ArrowUp": (38, "ArrowUp"),
    "ArrowDown": (40, "ArrowDown"),
    "ArrowLeft": (37, "ArrowLeft"),
    "ArrowRight": (39, "ArrowRight"),
    "Home": (36, "Home"),
    "End": (35, "End"),
    "PageUp": (33, "PageUp"),
    "PageDown": (34, "PageDown"),
}

_MOUSE = {"move": "mouseMoved", "down": "mousePressed", "up": "mouseReleased", "wheel": "mouseWheel"}

#: Schemes the address bar will follow. `javascript:` and `data:` are absent on
#: purpose: both turn a typed string into code running in whatever origin is
#: loaded, and an address bar is the one place a person pastes something a
#: stranger sent them.
SCHEMES = ("http://", "https://", "about:", "file://")


class BrowserUnavailable(DegradedError):
    """No Chromium, or it stopped answering.

    Degraded and not fatal for the same reason [[Web Access]] makes the whole
    plane optional: a panel that cannot paint is a panel that says so, and
    nothing else in Genesis depends on it.
    """


def resolve_url(raw: str) -> str:
    """What the address bar means. Deterministic — never a model.

    Three cases, and the third is why this is a function rather than a string
    concatenation: a scheme is followed as typed, something shaped like a host
    gets ``https://``, and anything else is a search. Guessing wrong between
    the last two is the difference between a 404 and an answer.
    """
    text = raw.strip()
    if not text:
        return "about:blank"
    lowered = text.lower()
    if lowered.startswith(SCHEMES):
        return text
    if ":" in text.split("/")[0] and not text.split(":")[1][:1].isdigit():
        # A scheme we do not follow — `javascript:`, `data:`, `chrome:`.
        return SEARCH.format(_quote(text))
    host = text.split("/")[0].split("?")[0]
    bare = host.split(":")[0]
    if bare in ("localhost", "127.0.0.1", "::1"):
        return f"http://{text}"
    if " " not in text and "." in bare and bare.rsplit(".", 1)[-1].isalpha() and len(bare.rsplit(".", 1)[-1]) >= 2:
        return f"https://{text}"
    return SEARCH.format(_quote(text))


def _quote(text: str) -> str:
    from urllib.parse import quote_plus

    return quote_plus(text)


def _binary() -> str:
    for name in BINARIES:
        found = shutil.which(name)
        if found:
            return found
    raise BrowserUnavailable(
        "no Chromium found on PATH. Install one of: " + ", ".join(BINARIES),
        spoken_summary="I have no browser installed to show that in.",
    )


class BrowserSession:
    """The browser, its process, and the one CDP socket into its page.

    Serialized by `CDPSession`'s own lock, which is what makes a frame capture
    and a click from two different HTTP requests safe without any locking here.
    The cost is that a click queues behind an in-flight screenshot — tens of
    milliseconds, and invisible next to the frame interval.
    """

    def __init__(self, *, port: int = DEFAULT_PORT, headless: bool = HEADLESS) -> None:
        self.port = port
        self.headless = headless
        self._process: subprocess.Popen[bytes] | None = None
        self._cdp: CDPSession | None = None
        self._cast: Screencast | None = None
        self._target_url = ""
        self.size = (1440, 900)

    # -- lifecycle ----------------------------------------------------

    def start(self) -> BrowserSession:
        """Attach to a browser on the port, or launch one.

        Attaching first is not an optimisation: with ``GENESIS_BROWSER_HEADLESS=0``
        the window is one the operator may be typing in, and relaunching it
        under them would be the surprise.
        """
        try:
            version(self.port)
        except CDPUnavailable:
            self._launch()
        self._target_url = self._page_target().websocket_url
        self._cdp = CDPSession(self._target_url).connect()
        self.resize(*self.size)
        return self

    def _launch(self) -> None:
        profile = PROFILE_DIR.expanduser()
        profile.mkdir(parents=True, exist_ok=True)
        width, height = self.size
        argv = [
            _binary(),
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={profile}",
            f"--window-size={width},{height}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=Translate",
            # Without this the page sees `navigator.webdriver` and a handful of
            # sites degrade themselves. This is the operator's own browser and
            # their own accounts; the flag makes it behave like one.
            "--disable-blink-features=AutomationControlled",
        ]
        if self.headless:
            argv.append("--headless=new")
        argv.append("about:blank")
        # `ELECTRON_RUN_AS_NODE` breaks an Electron child the same way it breaks
        # TradingView Desktop (see `tradingview/cdp.py`). Chromium ignores it,
        # but the profile may launch a helper that does not.
        env = {k: v for k, v in os.environ.items() if k != "ELECTRON_RUN_AS_NODE"}
        self._process = subprocess.Popen(  # noqa: S603 - resolved binary, no shell
            argv, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        deadline = time.monotonic() + LAUNCH_TIMEOUT_SEC
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                raise BrowserUnavailable(
                    f"the browser exited with code {self._process.returncode} before "
                    f"opening port {self.port}. Another instance may already hold "
                    f"{profile}."
                )
            try:
                version(self.port)
                return
            except CDPUnavailable:
                time.sleep(0.2)
        self.close()
        raise BrowserUnavailable(
            f"the browser started but never opened port {self.port} within "
            f"{LAUNCH_TIMEOUT_SEC:.0f}s"
        )

    def _page_target(self) -> Any:
        pages = [t for t in targets(self.port) if t.type == "page"]
        if not pages:
            raise BrowserUnavailable("the browser is running but has no page open")
        return pages[0]

    def close(self) -> None:
        if self._cast is not None:
            self._cast.stop()
            self._cast = None
        if self._cdp is not None:
            self._cdp.close()
            self._cdp = None
        if self._process is not None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

    @property
    def alive(self) -> bool:
        if self._cdp is None:
            return False
        if self._process is not None and self._process.poll() is not None:
            return False
        try:
            self.state()
            return True
        except (CDPUnavailable, BrowserUnavailable):
            return False

    # -- the socket ---------------------------------------------------

    def _send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._cdp is None:
            raise BrowserUnavailable("not connected")
        try:
            return self._cdp.send(method, params)
        except CDPUnavailable as exc:
            raise BrowserUnavailable(str(exc)) from exc

    # -- what the panel asks for --------------------------------------

    def resize(self, width: int, height: int) -> None:
        """Make the viewport the size of the panel, so a click maps 1:1.

        Without the override a headless viewport stays at its launch size and
        every coordinate the panel sends lands somewhere else on the page —
        which looks like a browser that ignores clicks rather than like a
        geometry bug, and costs an hour to see.
        """
        self.size = (max(320, int(width)), max(240, int(height)))
        self._send(
            "Emulation.setDeviceMetricsOverride",
            {"width": self.size[0], "height": self.size[1], "deviceScaleFactor": 1, "mobile": False},
        )
        if self._cast is not None and self._cast.alive:
            self._cast.resize(*self.size)

    def screencast(self) -> Screencast:
        """The live feed, started on first ask and shared by every reader.

        A second socket to the same page, so frames and clicks stop queueing
        behind each other — see `screencast.py` for the measurements that made
        this worth building.
        """
        if self._cast is None or not self._cast.alive:
            if self._cast is not None:
                self._cast.stop()
            self._cast = Screencast(self._target_url, quality=QUALITY).start(*self.size)
        return self._cast

    def frame(self) -> bytes:
        """One frame, synchronously. The fallback when the cast will not start.

        Costs a full compositor frame and a readback every call — 115 ms on a
        busy page — which is exactly why it is not the streaming path.
        """
        result = self._send("Page.captureScreenshot", {"format": "jpeg", "quality": QUALITY})
        data = result.get("data")
        if not data:
            raise BrowserUnavailable("the browser returned an empty frame")
        return base64.b64decode(data)

    def state(self) -> dict[str, Any]:
        """Where it is, and whether back and forward would do anything."""
        history = self._send("Page.getNavigationHistory")
        entries = history.get("entries", [])
        index = int(history.get("currentIndex", -1))
        current = entries[index] if 0 <= index < len(entries) else {}
        return {
            "url": current.get("url", "about:blank"),
            "title": current.get("title", ""),
            "can_back": index > 0,
            "can_forward": 0 <= index < len(entries) - 1,
            "headless": self.headless,
            "width": self.size[0],
            "height": self.size[1],
        }

    def navigate(self, raw: str) -> str:
        url = resolve_url(raw)
        self._send("Page.navigate", {"url": url})
        return url

    def history(self, step: int) -> None:
        """Back or forward one entry. A no-op at either end, not an error."""
        history = self._send("Page.getNavigationHistory")
        entries = history.get("entries", [])
        target = int(history.get("currentIndex", 0)) + step
        if 0 <= target < len(entries):
            self._send("Page.navigateToHistoryEntry", {"entryId": entries[target]["id"]})

    def reload(self) -> None:
        self._send("Page.reload")

    def mouse(
        self,
        kind: str,
        x: float,
        y: float,
        *,
        button: str = "left",
        clicks: int = 1,
        dx: float = 0.0,
        dy: float = 0.0,
        modifiers: int = 0,
    ) -> None:
        if kind not in _MOUSE:
            raise ValueError(f"unknown mouse event {kind!r}")
        params: dict[str, Any] = {
            "type": _MOUSE[kind],
            "x": float(x),
            "y": float(y),
            "modifiers": int(modifiers),
        }
        if kind == "wheel":
            params |= {"deltaX": float(dx), "deltaY": float(dy)}
        else:
            params |= {"button": button if kind != "move" else "none", "clickCount": int(clicks)}
        self._send("Input.dispatchMouseEvent", params)

    def text(self, value: str) -> None:
        self._send("Input.insertText", {"text": value})

    def key(self, name: str, *, modifiers: int = 0) -> None:
        if name not in KEYS:
            raise ValueError(f"{name!r} is not a navigation key; send printable text as text")
        code, key_code = KEYS[name]
        for kind in ("keyDown", "keyUp"):
            params: dict[str, Any] = {
                "type": kind,
                "key": name,
                "code": key_code,
                "windowsVirtualKeyCode": code,
                "nativeVirtualKeyCode": code,
                "modifiers": int(modifiers),
            }
            # Enter without `text` reaches a `keydown` handler but never a form
            # submit, which is most of what Enter is for.
            if name == "Enter" and kind == "keyDown":
                params["text"] = "\r"
            self._send("Input.dispatchKeyEvent", params)


# --------------------------------------------------------------------------
# One per daemon
# --------------------------------------------------------------------------

_LOCK = threading.Lock()
_SESSION: BrowserSession | None = None


def session() -> BrowserSession:
    """The browser, launched on first use and reused after.

    One, not one per panel: a second Chromium on the same profile fails, and
    two profiles means logging in twice.
    """
    global _SESSION
    with _LOCK:
        if _SESSION is not None and _SESSION.alive:
            return _SESSION
        if _SESSION is not None:
            _SESSION.close()
        _SESSION = BrowserSession().start()
        return _SESSION


def close() -> None:
    """Shut it down. Called by the panel's close button and at daemon exit."""
    global _SESSION
    with _LOCK:
        if _SESSION is not None:
            _SESSION.close()
            _SESSION = None


def _demo() -> None:
    """The address bar's rules, which are the only branch here worth a check."""
    assert resolve_url("tradingview.com") == "https://tradingview.com"
    assert resolve_url("  https://x.com/home ") == "https://x.com/home"
    assert resolve_url("example.co.uk/a/b") == "https://example.co.uk/a/b"
    assert resolve_url("localhost:5273") == "http://localhost:5273"
    assert resolve_url("127.0.0.1:8765/v1/health") == "http://127.0.0.1:8765/v1/health"
    assert resolve_url("about:blank") == "about:blank"
    assert resolve_url("") == "about:blank"
    # Not a host: a search, not a navigation.
    assert resolve_url("what is gann theory") == SEARCH.format("what+is+gann+theory")
    assert resolve_url("NVDA earnings") == SEARCH.format("NVDA+earnings")
    assert resolve_url("gann") == SEARCH.format("gann")
    # A scheme we do not follow must not survive as one.
    assert not resolve_url("javascript:alert(1)").startswith("javascript:")
    assert not resolve_url("data:text/html,<b>x").startswith("data:")
    # Keys: printable text never goes through the table.
    assert "Enter" in KEYS and "a" not in KEYS
    print("browser: address bar and key table ok")


if __name__ == "__main__":
    _demo()
