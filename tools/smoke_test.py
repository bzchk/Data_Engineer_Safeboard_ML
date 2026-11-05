"""Check authentication, inference, validation errors, and the live audit log."""
import argparse
import json
import os
import subprocess
import urllib.error
import urllib.request
import uuid

parser = argparse.ArgumentParser()
parser.add_argument("--base-url", default="http://127.0.0.1:18001")
parser.add_argument("--check-logs", action="store_true")
args = parser.parse_args()
token = os.environ.get("API_TOKEN")
if not token:
    parser.error("Set API_TOKEN before running the test (see README)")
marker = "PROMPT_CANARY_" + uuid.uuid4().hex

def call(path, body=None, authenticated=True):
    headers = {"Content-Type": "application/json"}
    if authenticated:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(args.base_url.rstrip("/") + path,
                                     data=None if body is None else json.dumps(body).encode(), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, None

print("[1/4] Checking that unauthenticated access is rejected...", flush=True)
status, _ = call("/v1/models", authenticated=False)
assert status in (401, 403), f"Expected HTTP 401/403 without a token, got {status}. Check --base-url."
print("[2/4] Checking authenticated access...", flush=True)
status, _ = call("/v1/models")
assert status == 200, "Authenticated model listing failed"
print("[3/4] Generating a short answer (first CPU request can be slow)...", flush=True)
status, answer = call("/v1/chat/completions", {"model": "qwen-cpu", "messages": [
    {"role": "user", "content": "Reply with exactly this marker: " + marker}], "max_tokens": 16, "temperature": 0})
assert status == 200 and answer.get("choices"), f"Inference failed: HTTP {status}"
completion = answer["choices"][0]["message"]["content"]
print("[4/4] Checking malformed payload and audit privacy...", flush=True)
status, _ = call("/v1/chat/completions", {"model": "qwen-cpu", "messages": marker})
assert status in (400, 422), "Malformed payload was not rejected"
if args.check_logs:
    logs = subprocess.check_output(["kubectl", "-n", "llm-cpu", "logs", "deployment/vllm-cpu", "-c", "server"], text=True)
    assert marker not in logs and token not in logs, "Sensitive input in log"
    if len(completion.strip()) >= 12:
        assert completion not in logs, "Completion in log"
    events = [json.loads(line) for line in logs.splitlines() if line.strip()]
    statuses = {event.get("status") for event in events if event.get("event") == "request_completed"}
    assert 200 in statuses and statuses.intersection({401, 403}) and statuses.intersection({400, 422}), "Missing access audits"
print("PASS: authentication, inference, malformed payload" + (", live log privacy" if args.check_logs else ""))
