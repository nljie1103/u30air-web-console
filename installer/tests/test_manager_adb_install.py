"""Google Platform Tools one-click install tests without network access."""
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import deployment


class MockHTTPResponse(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *_): self.close()


def tool_archive(valid=True):
    output = io.BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as z:
        for name in ("adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll"):
            header = b"MZ" if valid or name != "adb.exe" else b"NO"
            z.writestr("platform-tools/" + name, header + (b"0" * 512))
    return output.getvalue()


class TestADBInstaller(unittest.TestCase):
    def test_one_click_download_uses_per_user_path_and_google_source(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"LOCALAPPDATA":root}):
            payload = tool_archive()
            def fetch(request, timeout):
                self.assertEqual(request.full_url,
                    "https://dl.google.com/android/repository/platform-tools-latest-windows.zip")
                return MockHTTPResponse(payload)
            messages=[]
            with patch.object(deployment,"urlopen",side_effect=fetch):
                path=deployment.official_adb_download(messages.append)
            self.assertEqual(path,Path(root)/"AndroidWebDesktop"/"platform-tools"/"adb.exe")
            self.assertEqual(path.read_bytes()[:2],b"MZ")
            self.assertTrue((path.parent/"AdbWinApi.dll").exists())
            self.assertTrue((path.parent/"AdbWinUsbApi.dll").exists())
            self.assertTrue(any("无需配置环境变量" in text for text in messages))
            self.assertEqual(os.environ["LOCALAPPDATA"],root)

    def test_bad_pe_does_not_overwrite_existing_adb(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"LOCALAPPDATA":root}):
            existing=Path(root)/"AndroidWebDesktop"/"platform-tools"
            existing.mkdir(parents=True)
            exe=existing/"adb.exe"
            exe.write_bytes(b"MZ-old")
            with patch.object(deployment,"urlopen",return_value=MockHTTPResponse(tool_archive(False))):
                with self.assertRaisesRegex(ValueError,"签名"):
                    deployment.official_adb_download()
            self.assertEqual(exe.read_bytes(),b"MZ-old")

    def test_upgrade_keeps_previous_distribution_on_publish_failure(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"LOCALAPPDATA":root}):
            target=Path(root)/"AndroidWebDesktop"/"platform-tools"
            target.mkdir(parents=True)
            names=("adb.exe","AdbWinApi.dll","AdbWinUsbApi.dll")
            for name in names:
                (target/name).write_bytes(b"old"+name.encode())
            with patch.object(deployment,"urlopen",return_value=MockHTTPResponse(tool_archive())):
                with patch("os.replace",side_effect=PermissionError("locked")):
                    with self.assertRaises(PermissionError):
                        deployment.official_adb_download()
            for name in names:
                self.assertEqual((target/name).read_bytes(),b"old"+name.encode())
            self.assertEqual(list(target.parent.iterdir()),[target])

    def test_portable_adb_discovery_uses_manager_directory(self):
        import adb_client
        with tempfile.TemporaryDirectory(prefix="中文 directory ") as root:
            exe=Path(root)/"adb.exe"
            exe.touch()
            with patch.object(sys,"frozen",True,create=True), patch.dict(os.environ,{"AWD_MANAGER_DIR":root,"PATH":""}):
                self.assertEqual(adb_client.locate_adb(),exe)
