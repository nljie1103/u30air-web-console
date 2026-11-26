import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile
from unittest.mock import Mock, patch
import io

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import apk


class TestAPK(unittest.TestCase):
    def test_local_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.apk"
            with ZipFile(path, "w") as z:
                z.writestr("AndroidManifest.xml", b"manifest")
            adb = Mock()
            adb.selected.return_value = "Success"
            self.assertEqual(apk.install_apk(adb, "device", str(path), False, lambda _: None), "Success")
            adb.selected.assert_called_once_with("device", "install", "-r", str(path), timeout=180)
            adb.selected.return_value = "Failure"
            with self.assertRaises(ValueError):
                apk.install_apk(adb, "device", str(path), False, lambda _: None)

    def test_download_and_cleanup(self):
        payload = io.BytesIO()
        with ZipFile(payload, "w") as z:
            z.writestr("AndroidManifest.xml", b"manifest")
        response = io.BytesIO(payload.getvalue())
        response.headers = {"Content-Length": str(len(payload.getvalue()))}
        adb = Mock()
        paths = []
        def selected(serial, command, replace, path, timeout):
            self.assertTrue(Path(path).exists())
            self.assertEqual((serial, command, replace), ("device", "install", "-r"))
            paths.append(Path(path))
            return "Success"
        adb.selected.side_effect = selected
        with patch("apk.build_opener") as opener:
            opener.return_value.open.return_value = response
            apk.install_apk(adb, "device", "https://example.com/a.apk", True, lambda _: None)
        self.assertFalse(paths[0].exists())
        for invalid in ("http://example.com/a.apk", "https://user:pw@example.com/a.apk", "file:///tmp/a.apk"):
            with self.assertRaises(ValueError):
                apk.validate_url(invalid)
