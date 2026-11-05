"""Настройки инференса, которые можно менять без пересборки образа."""
from pathlib import Path
import sys

INTEGER_OPTIONS = {"max-model-len", "max-num-seqs", "max-num-batched-tokens"}
BOOLEAN_OPTIONS = {"enable-prefix-caching", "enable-chunked-prefill"}
DTYPES = {"auto", "float32", "bfloat16", "float16"}


def validate_config(config):
    allowed = INTEGER_OPTIONS | BOOLEAN_OPTIONS | {"dtype"}
    if not isinstance(config, dict) or set(config) - allowed:
        raise ValueError("Unsupported inference options")
    for key, value in config.items():
        if key in INTEGER_OPTIONS and (type(value) is not int or value < 1):
            raise ValueError("Token and sequence limits must be positive integers")
        if key in BOOLEAN_OPTIONS and type(value) is not bool:
            raise ValueError("Caching and prefill options must be booleans")
        if key == "dtype" and (not isinstance(value, str) or value not in DTYPES):
            raise ValueError("Unsupported dtype")
    if config.get("enable-chunked-prefill") is False:
        context = config.get("max-model-len")
        budget = config.get("max-num-batched-tokens")
        if context is None or budget is None or budget < context:
            raise ValueError("Without chunked prefill, set a budget covering the context")
    return config


def server_command(model: Path, config):
    validate_config(config)
    command = [sys.executable, "-m", "vllm.entrypoints.openai.api_server",
               "--model", str(model), "--served-model-name", "qwen-cpu",
               "--host", "0.0.0.0", "--port", "8000", "--enforce-eager",
               "--load-format", "safetensors", "--no-enable-log-requests",
               "--no-enable-log-outputs", "--disable-uvicorn-access-log",
               "--middleware", "inference.audit.AuditMiddleware", "--disable-fastapi-docs"]
    for key, value in config.items():
        if isinstance(value, bool):
            command.append("--" + ("" if value else "no-") + key)
        else:
            command.extend(["--" + key, str(value)])
    return command
