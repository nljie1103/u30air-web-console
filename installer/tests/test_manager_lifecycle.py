"""The Edge bootstrap may exit before its app window: keep localhost alive."""
import sys
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_lifecycle import wait_for_app_window, keep_server_until_window_closed
from app import _startup_event


class FakeEdgeBootstrap:
    def __init__(self, result=0):
        self.result = result
    def poll(self):
        return self.result


class TestBrowserLifecycle(TestCase):
    def test_early_launcher_exit_does_not_close_http_service(self):
        """A short-lived msedge.exe launcher must not kill the backend."""
        clock = [0.0]
        windows = [set(), {101, 222}, {101, 222}, {101, 222},
                   {101}, {101}, {101}, {101}, {101}]
        def enumerate_windows():
            return windows.pop(0) if windows else {101}
        def sleep(n):
            clock[0] += n
        hwnd = wait_for_app_window(
            FakeEdgeBootstrap(result=0), {101},
            enumerate_windows=enumerate_windows,
            sleep=sleep, clock=lambda: clock[0],
        )
        self.assertEqual(hwnd, 222)
        self.assertGreater(clock[0], 0)
        loop = [{222}, {222}, {222}, set(), set(), set(), set()]
        keep_server_until_window_closed(
            hwnd,
            enumerate_windows=lambda: loop.pop(0),
            sleep=lambda n: None,
        )
        self.assertEqual(loop, [])
        # No process.wait() ever involved: the front-end remains available
        # until the actual app window has disappeared.

    def test_launch_without_window_times_out_even_if_parent_running(self):
        clock = [0.0]
        def sleep(n):
            clock[0] += n
        with self.assertRaisesRegex(RuntimeError, "启动超时"):
            wait_for_app_window(
                FakeEdgeBootstrap(result=None), set(),
                enumerate_windows=set,
                sleep=sleep, clock=lambda: clock[0],
                startup_timeout=2,
            )

    def test_exit_without_window_reports_edge_failure(self):
        clock = [0.0]
        def sleep(n):
            clock[0] += n
        with self.assertRaisesRegex(RuntimeError, "启动进程已经结束"):
            wait_for_app_window(
                FakeEdgeBootstrap(result=0), set(),
                enumerate_windows=set,
                sleep=sleep, clock=lambda: clock[0],
                startup_timeout=1,
            )

    def test_diagnostic_log_never_needs_admin_rights(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            _startup_event(path, "Startup test")
            self.assertIn("Startup test", (path / "manager-startup.log").read_text(encoding="utf-8"))
            with patch("pathlib.Path.open", side_effect=OSError("write denied")):
                _startup_event(path, "ignored")
