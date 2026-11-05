import asyncio
import json
import os
import unittest
from unittest.mock import patch
from inference.audit import AuditMiddleware
from inference.server import validate_event


class PrivacyTest(unittest.TestCase):
    def run_request(self, failure=False):
        async def application(scope, receive, send):
            await receive()
            if failure:
                raise ValueError("SECRET_PROMPT")
            await send({"type": "http.response.start", "status": 200})
            await send({"type": "http.response.body", "body": b"SECRET_COMPLETION", "more_body": True})
            await send({"type": "http.response.body", "body": b"final"})

        async def receive():
            return {"type": "http.request", "body": b"SECRET_PROMPT"}

        sent = []

        async def send(message):
            sent.append(message)

        scope = {"type": "http", "path": "/v1/chat/completions", "query_string": b"SECRET_PROMPT",
                 "headers": [(b"authorization", b"SECRET_TOKEN")], "method": "POST"}
        # Проверяю байты, передаваемые в аудит. Реальный pipe используется в Linux-контейнере.
        with patch.dict(os.environ, {"AUDIT_FD": "123"}), patch("inference.audit.os.write") as write:
            if failure:
                with self.assertRaises(ValueError):
                    asyncio.run(AuditMiddleware(application)(scope, receive, send))
            else:
                asyncio.run(AuditMiddleware(application)(scope, receive, send))
        write.assert_called_once()
        descriptor, payload = write.call_args.args
        self.assertEqual(descriptor, 123)
        output = payload.decode()
        self.assertNotIn("SECRET", output)
        self.assertEqual(len(output.splitlines()), 1)
        event = validate_event(output)
        self.assertIsNotNone(event)
        self.assertEqual(event["status"], 500 if failure else 200)
        if not failure:
            self.assertEqual(sent[1]["body"], b"SECRET_COMPLETION")

    def test_streaming_privacy(self):
        self.run_request()

    def test_exception_privacy(self):
        self.run_request(failure=True)

    def test_relay_rejects_untrusted_output(self):
        for text in ("SECRET_PROMPT", '{"event":"SECRET_PROMPT"}',
                     json.dumps({"event": "request_completed", "request_id": "a" * 32,
                                 "route": "SECRET", "status": 200, "duration_ms": 1})):
            self.assertIsNone(validate_event(text))
