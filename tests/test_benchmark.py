import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("load_test", Path(__file__).parents[1] / "tools/benchmark/run.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)

class BenchmarkTest(unittest.TestCase):
    def test_role_only_chunk_is_not_first_token(self):
        chunks = [{"choices": [{"delta": {"role": "assistant", "content": ""}}]},
                  {"choices": [{"delta": {"content": "hello"}}]},
                  {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 2}}]
        wire = b"".join(b"data: " + json.dumps(chunk).encode() + b"\n\n" for chunk in chunks) + b"data: [DONE]\n\n"
        with patch("urllib.request.urlopen", return_value=io.BytesIO(wire)), \
                patch("time.perf_counter", side_effect=[100, 102, 105]):
            result = benchmark.request("http://localhost", "token", "synthetic", 2, 10)
        self.assertEqual(result["ttft_s"], 2)
        self.assertEqual(result["latency_s"], 5)
        self.assertEqual(result["completion_tokens"], 2)

    def test_missing_usage_fails_measurement(self):
        wire = b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\ndata: [DONE]\n\n'
        with patch("urllib.request.urlopen", return_value=io.BytesIO(wire)):
            with self.assertRaises(RuntimeError):
                benchmark.request("http://localhost", "token", "synthetic", 2, 10)

if __name__ == "__main__":
    unittest.main()
