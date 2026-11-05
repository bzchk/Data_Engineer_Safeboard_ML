import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import urllib.request

spec = importlib.util.spec_from_file_location("cache_model", Path(__file__).parents[1] / "tools/cache_model.py")
cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache)


class CachePathTest(unittest.TestCase):
    def test_rejects_snapshot_paths_outside_volume(self):
        for name in ("../secret", "/secret", "dir/../../secret", "C:/secret", "dir\\secret"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                cache.safe_path(name)

    def test_corrupt_manifest_cannot_escape_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / ".complete.json").write_text(json.dumps({
                "repo": "org/model", "revision": "a" * 40,
                "files": {"config.json": "x", "../model.safetensors": "y"}}))
            self.assertFalse(cache.valid_snapshot(target, "org/model", "a" * 40))

    def test_redirect_cannot_downgrade_to_http(self):
        request = urllib.request.Request("https://huggingface.co/weights")
        with self.assertRaises(ValueError):
            cache.SafeRedirect().redirect_request(request, None, 302, "", {}, "http://cdn.example/weights")
