"""Запуск vLLM с отдельным каналом для безопасных событий аудита."""
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys

def validate_event(line):
    try:
        event = json.loads(line)
        if set(event) != {"event", "request_id", "route", "status", "duration_ms"}:
            return None
        if event["event"] != "request_completed" or not re.fullmatch(r"[0-9a-f]{32}", event["request_id"]):
            return None
        if event["route"] not in {"/v1/chat/completions", "/v1/completions", "/v1/models", "other"}:
            return None
        if type(event["status"]) is not int or not 100 <= event["status"] <= 599:
            return None
        duration = event["duration_ms"]
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0:
            return None
        return event
    except (ValueError, TypeError, KeyError):
        return None

def emit(event, **fields):
    print(json.dumps({"event": event, **fields}), flush=True)

def main():
    import yaml  # Входит в закреплённое окружение vLLM.
    config = yaml.safe_load(Path(os.getenv("VLLM_CONFIG", "/config/serve.yaml")).read_text())
    from inference.config import server_command
    if not os.environ.get("VLLM_API_KEY", "").strip():
        raise ValueError("API token is required")
    model = Path(os.environ.get("MODEL_PATH", "/models/model"))
    if not (model / ".complete.json").is_file():
        raise ValueError("Model download is incomplete")
    env = os.environ.copy()
    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", VLLM_NO_USAGE_STATS="1",
               DO_NOT_TRACK="1", VLLM_DEBUG_LOG_API_SERVER_RESPONSE="0",
               VLLM_LOGGING_CONFIG_PATH="/app/inference/logging.json", VLLM_TARGET_DEVICE="cpu")
    env.pop("HF_TOKEN", None)
    command = server_command(model, config)
    read_fd, write_fd = os.pipe()
    env["AUDIT_FD"] = str(write_fd)
    # Сырой вывод дочернего процесса может содержать текст запроса даже в traceback.
    # Наружу передаю только проверенные события из отдельного канала аудита.
    child = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, pass_fds=(write_fd,))
    os.close(write_fd)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda number, frame: child.send_signal(number))
    emit("server_starting")
    with os.fdopen(read_fd) as stream:
        for line in stream:
            event = validate_event(line)
            if event is not None:
                print(json.dumps(event), flush=True)
    code = child.wait()
    emit("server_stopped", exit_code=code)
    return code if code >= 0 else 128 - code

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        emit("startup_failed")
        sys.exit(1)
