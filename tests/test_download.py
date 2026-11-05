import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("download_model", Path(__file__).parents[1] / "tools/cache_model.py")
downloader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(downloader)
REVISION = "a" * 40

class DownloadTest(unittest.TestCase):
    def snapshot(self, root):
        target = root / "model"
        target.mkdir()
        (target / "config.json").write_bytes(b"{}")
        (target / "model.safetensors").write_bytes(b"weights")
        (target / ".complete.json").write_text(json.dumps({
            "repo": "org/model", "revision": REVISION,
            "files": {"config.json": hashlib.sha256(b"{}").hexdigest(),
                      "model.safetensors": hashlib.sha256(b"weights").hexdigest()}}))
        return target

    def test_restart_never_opens_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.snapshot(root)
            with patch("urllib.request.build_opener", side_effect=AssertionError("Network forbidden")):
                downloader.download("org/model", REVISION, root)

    def test_corrupt_cache_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = self.snapshot(root)
            (target / "config.json").write_text("corrupt")
            with patch("urllib.request.build_opener", side_effect=AssertionError("Network forbidden")):
                with self.assertRaises(ValueError):
                    downloader.download("org/model", REVISION, root)

    def test_mutable_revision_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                downloader.download("org/model", "main", Path(directory))

    def test_no_token_on_cross_origin_redirect(self):
        import urllib.request
        request = urllib.request.Request("https://huggingface.co/weights", headers={"Authorization": "Bearer SECRET"})
        redirected = downloader.SafeRedirect().redirect_request(request, None, 302, "", {}, "https://cdn.example/weights")
        self.assertIsNone(redirected.get_header("Authorization"))

    def test_download_publishes_complete_snapshot_and_verifies_weight(self):
        weights = b"synthetic weights"
        metadata = {"sha": REVISION, "siblings": [
            {"rfilename": "config.json"},
            {"rfilename": "model.safetensors", "lfs": {"sha256": hashlib.sha256(weights).hexdigest()}}]}

        class Opener:
            def open(self, request, timeout):
                if "/api/" in request.full_url:
                    return io.BytesIO(json.dumps(metadata).encode())
                return io.BytesIO(b"{}" if request.full_url.endswith("config.json") else weights)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("urllib.request.build_opener", return_value=Opener()):
                downloader.download("org/model", REVISION, root)
            self.assertTrue(downloader.valid_snapshot(root / "model", "org/model", REVISION))
            self.assertFalse((root / ".staging").exists())

    def test_wrong_weight_checksum_never_publishes(self):
        metadata = {"sha": REVISION, "siblings": [
            {"rfilename": "model.safetensors", "lfs": {"sha256": "0" * 64}}]}

        class Opener:
            def open(self, request, timeout):
                return io.BytesIO(json.dumps(metadata).encode() if "/api/" in request.full_url else b"corrupt")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("urllib.request.build_opener", return_value=Opener()):
                with self.assertRaises(ValueError):
                    downloader.download("org/model", REVISION, root)
            self.assertFalse((root / "model").exists())

if __name__ == "__main__":
    unittest.main()
