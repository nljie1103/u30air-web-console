"""Fast release preflight; run before Windows packaging."""
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, encoding="utf-8").strip()


def metadata(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def main():
    version = metadata("web-console/version.json")["version"]
    assert re.fullmatch(r"(?:0|[1-9]\d*)\.[0-9]\.[0-9]", version), "Invalid release version"
    assert git("log", "-1", "--format=%s").startswith(version + "："), "Commit version mismatch"
    previous = git("describe", "--tags", "--abbrev=0", "HEAD^")
    assert git("rev-list", "--count", previous + "..HEAD") == "1", "One commit per release required"
    old = tuple(map(int, previous.removeprefix("v").split(".")))
    new = tuple(map(int, version.split(".")))
    assert new > old, "Release must advance"
    assert f'APP_VERSION = "{version}"' in (ROOT / "installer/version.py").read_text(encoding="utf-8")
    for folder in ("installer/frontend", "web-console/tests"):
        lock = metadata(folder + "/package-lock.json")
        assert metadata(folder + "/package.json")["version"] == lock["version"] == lock["packages"][""]["version"] == version
    icon = (ROOT / "installer/assets/app-icon.svg").read_bytes()
    for path in ("installer/frontend/public/app-icon.svg", "web-console/web/app-icon.svg"):
        assert (ROOT / path).read_bytes() == icon, f"Inconsistent logo: {path}"
    print(f"Release {version}: one commit, versions and logos verified")


if __name__ == "__main__":
    main()
