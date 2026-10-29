"""Optional Windows input adapter. No hooks, automatic activation, or process termination."""

import argparse
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import time
from datetime import datetime


def latch_stop(state_path, reason):
    """Persist a stop between CLI calls; never invent a chat notification."""
    try:
        path = Path(state_path)
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if data.get("phase") != "desktop" or data.get("control") != "desktop":
            return
        data.update(phase="paused", control="paused")
        data.setdefault("input_stops", []).append({
            "at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "reason": str(reason), "chat_notice_recorded": False})
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    except (OSError, ValueError, TypeError):
        # An unreadable state already causes every subsequent guarded input to stop.
        return


class InputStopped(RuntimeError):
    pass


class WindowsBackend:
    def __init__(self):
        if os.name != "nt":
            raise InputStopped("Windows is required")
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user.SetProcessDPIAware()
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        self.user.GetAncestor.restype = wintypes.HWND
        self.user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user.IsWindow.argtypes = [wintypes.HWND]
        self.user.IsWindowEnabled.argtypes = [wintypes.HWND]
        self.user.IsIconic.argtypes = [wintypes.HWND]
        self.user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user.WindowFromPoint.argtypes = [wintypes.POINT]
        self.user.WindowFromPoint.restype = wintypes.HWND
        self.user.SetForegroundWindow.argtypes = [wintypes.HWND]
        self.user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]

    def start_ticks(self, pid):
        handle = self.kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            raise InputStopped("Target process is absent or inaccessible")
        values = [wintypes.FILETIME() for _ in range(4)]
        try:
            if not self.kernel.GetProcessTimes(handle, *(ctypes.byref(v) for v in values)):
                raise InputStopped("Cannot verify target creation time")
            # Match .NET DateTime UTC ticks used by existing PowerShell drivers.
            return (values[0].dwHighDateTime << 32) + values[0].dwLowDateTime + 504911232000000000
        finally:
            self.kernel.CloseHandle(handle)

    def window_pid(self, hwnd):
        pid = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value

    def foreground(self):
        return int(self.user.GetForegroundWindow() or 0)

    def root(self, hwnd):
        return int(self.user.GetAncestor(hwnd, 2) or 0)

    def title(self, hwnd):
        buf = ctypes.create_unicode_buffer(2048)
        self.user.GetWindowTextW(hwnd, buf, len(buf))
        return buf.value

    def is_window(self, hwnd):
        return bool(self.user.IsWindow(hwnd))

    def enabled(self, hwnd):
        return bool(self.user.IsWindowEnabled(hwnd))

    def minimized(self, hwnd):
        return bool(self.user.IsIconic(hwnd))

    def window_at(self, x, y):
        return int(self.user.WindowFromPoint(wintypes.POINT(x, y)) or 0)

    def activate(self, hwnd):
        if self.minimized(hwnd):
            self.user.ShowWindow(hwnd, 9)
        return bool(self.user.SetForegroundWindow(hwnd))

    def send_key(self, key, up=False, unicode=False):
        class Keyboard(ctypes.Structure):
            _fields_ = [("vk", wintypes.WORD), ("scan", wintypes.WORD), ("flags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("extra", ctypes.c_size_t)]
        class Mouse(ctypes.Structure):
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("data", wintypes.DWORD),
                        ("flags", wintypes.DWORD), ("time", wintypes.DWORD), ("extra", ctypes.c_size_t)]
        class Union(ctypes.Union):
            _fields_ = [("keyboard", Keyboard), ("mouse", Mouse)]
        class Input(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("value", Union)]
        item = Input(type=1, value=Union(keyboard=Keyboard(
            vk=0 if unicode else key, scan=key if unicode else 0,
            flags=(4 if unicode else 0) | (2 if up else 0))))
        self.user.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
        if self.user.SendInput(1, ctypes.byref(item), ctypes.sizeof(item)) != 1:
            raise InputStopped("SendInput failed")

    def mouse(self, x, y, up=False):
        if not up and not self.user.SetPhysicalCursorPos(x, y):
            raise InputStopped("Cannot position pointer")
        self.user.mouse_event(4 if up else 2, 0, 0, 0, 0)


class DesktopGuard:
    def __init__(self, manifest, state_path, backend=None):
        self.manifest = manifest
        self.state_path = Path(state_path)
        self.backend = backend or WindowsBackend()

    def check(self, require_focus=True, allow_minimized=False):
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as error:
            raise InputStopped("Run state unavailable; input stopped") from error
        if state.get("phase") != "desktop" or state.get("control") != "desktop":
            raise InputStopped("Desktop is paused or released")
        m, b = self.manifest, self.backend
        if b.start_ticks(m["pid"]) != m["start_ticks"]:
            raise InputStopped("Target process identity changed")
        root = m["root_hwnd"]
        if not b.is_window(root) or b.window_pid(root) != m["pid"]:
            raise InputStopped("Target window is absent or belongs to another process")
        if not b.enabled(root):
            raise InputStopped("Unapproved modal window; input stopped")
        if not allow_minimized and b.minimized(root):
            raise InputStopped("Target is minimized; input stopped")
        if m.get("title_contains") and m["title_contains"] not in b.title(root):
            raise InputStopped("Target document/title changed")
        if require_focus:
            foreground = b.foreground()
            allowed = m.get("allowed_hwnds", [root])
            if b.window_pid(foreground) != m["pid"] or b.root(foreground) not in allowed:
                raise InputStopped(f"Focus changed (pid={b.window_pid(foreground)}, hwnd={foreground}, "
                                   f"root={b.root(foreground)}); input stopped without reactivation")

    def acquire(self):
        # Only called after a specific chat notice; never used as an automatic retry.
        self.check(require_focus=False, allow_minimized=True)
        self.backend.activate(self.manifest["root_hwnd"])
        time.sleep(.15)
        self.check()

    def key(self, key, modifiers=()):
        held = []
        try:
            for code in (*modifiers, key):
                self.check()
                held.append(code)
                self.backend.send_key(code)
        finally:
            for code in reversed(held):
                self.backend.send_key(code, up=True)

    def text(self, value, delay=.01):
        # UTF-16 code units also handle non-BMP text; newline is a real Enter.
        encoded = value.encode("utf-16-le")
        for pos in range(0, len(encoded), 2):
            unit = int.from_bytes(encoded[pos:pos + 2], "little")
            if unit == 13:
                continue
            if unit == 10:
                self.key(13)
            else:
                self.check()
                try:
                    self.backend.send_key(unit, unicode=True)
                finally:
                    self.backend.send_key(unit, up=True, unicode=True)
            time.sleep(delay)

    def click(self, x, y):
        self.check()
        window = self.backend.window_at(x, y)
        allowed = self.manifest.get("allowed_hwnds", [self.manifest["root_hwnd"]])
        if self.backend.window_pid(window) != self.manifest["pid"] or self.backend.root(window) not in allowed:
            raise InputStopped(f"Click target is outside the approved windows (x={x}, y={y}, "
                               f"pid={self.backend.window_pid(window)}, root={self.backend.root(window)})")
        try:
            self.backend.mouse(x, y)
        finally:
            self.backend.mouse(x, y, up=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("state", type=Path)
    parser.add_argument("action", choices=["check", "acquire", "text", "key", "select-all", "click"])
    parser.add_argument("value", nargs="?", default="")
    parser.add_argument("--value-base64", help="UTF-8 payload, preserving quotes across Windows PowerShell native arguments")
    args = parser.parse_args(argv)
    try:
        value = base64.b64decode(args.value_base64, validate=True).decode("utf-8") if args.value_base64 is not None else args.value
        guard = DesktopGuard(json.loads(args.manifest.read_text(encoding="utf-8-sig")), args.state)
        if args.action == "check":
            guard.check()
        elif args.action == "acquire":
            guard.acquire()
        elif args.action == "text":
            guard.text(value)
        elif args.action == "key":
            guard.key(int(value))
        elif args.action == "select-all":
            guard.key(65, (17,))
        else:
            guard.click(*(int(v) for v in value.split(",")))
        print(json.dumps({"status": "completed", "action": args.action}))
        return 0
    except (InputStopped, OSError, ValueError, KeyError) as error:
        latch_stop(args.state, error)
        print(json.dumps({"status": "stopped", "reason": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
