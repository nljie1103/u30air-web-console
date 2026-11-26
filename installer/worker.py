"""Private JSON-lines RPC worker for the Windows desktop host."""
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from bridge import DesktopBridge

METHODS = frozenset({
    "environment", "list_devices", "device_info", "list_apps", "get_logs",
    "clear_logs", "connect", "set_adb_path", "install_official_adb",
    "check_release", "install_latest", "install_local", "read_auth",
    "configure_auth", "uninstall", "install_application", "uninstall_app",
    "set_system_app", "reboot", "poweroff", "open_web",
})


def serve(source, target, bridge):
    lock = threading.Lock()

    def reply(request):
        ident = request.get("id")
        try:
            method, args = request["method"], request["args"]
            if method not in METHODS or not isinstance(args, list) or len(args) > 6:
                raise ValueError("不允许的管理接口或参数")
            response = {"id": ident, "ok": True, "result": getattr(bridge, method)(*args)}
        except Exception as exc:
            response = {"id": ident, "ok": False, "error": str(exc)}
        with lock:
            target.write(json.dumps(response, ensure_ascii=True) + "\n")
            target.flush()

    with ThreadPoolExecutor(max_workers=5) as pool:
        for line in source:
            if len(line) > 65536:
                continue
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    continue
            except ValueError:
                continue
            pool.submit(reply, request)


if __name__ == "__main__":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    serve(sys.stdin, sys.stdout, DesktopBridge())
