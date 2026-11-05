"""Событие обращения без тел запросов, ответов, заголовков и текста ошибок."""
import json
import os
import time
import uuid

AUDITED_ROUTES = {"/v1/chat/completions", "/v1/completions", "/v1/models", "/health"}

class AuditMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = time.monotonic()
        status = 500
        route = scope.get("path", "")
        if route not in AUDITED_ROUTES:
            route = "other"

        async def audited_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, audited_send)
        finally:
            if route != "/health":
                event = {
                    "event": "request_completed",
                    "request_id": uuid.uuid4().hex,
                    "route": route,
                    "status": status,
                    "duration_ms": round((time.monotonic() - started) * 1000, 3),
                }
                # Отдельный канал нужен, чтобы не смешивать аудит с обычным выводом vLLM.
                os.write(int(os.environ["AUDIT_FD"]), (json.dumps(event) + "\n").encode())
