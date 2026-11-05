from pathlib import Path
import unittest
from inference.config import validate_config, server_command


class ConfigTest(unittest.TestCase):
    def test_cannot_disable_auth_or_change_logging_from_config(self):
        for key in ("api-key", "enable-log-requests", "middleware", "model"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_config({key: "unsafe"})

    def test_rejects_invalid_limits_and_yaml_types(self):
        for value in (True, 0, -1, "256", 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_config({"max-num-batched-tokens": value})
        with self.assertRaises(ValueError):
            validate_config({"enable-prefix-caching": "false"})

    def test_prefill_budget_covers_full_context_when_chunking_off(self):
        with self.assertRaises(ValueError):
            validate_config({"enable-chunked-prefill": False, "max-model-len": 1024,
                             "max-num-batched-tokens": 256})

    def test_safe_flags_remain_in_command(self):
        command = server_command(Path("/models/model"), {"max-num-seqs": 2})
        self.assertIn("--no-enable-log-requests", command)
        self.assertIn("--no-enable-log-outputs", command)
        self.assertIn("inference.audit.AuditMiddleware", command)
        self.assertNotIn("--api-key", command)
