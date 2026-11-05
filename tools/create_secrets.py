"""Read tokens without echoing; pass a Secret manifest to kubectl on stdin."""
import argparse
import getpass
import json
import os
import secrets
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("--namespace", default="llm-cpu")
args = parser.parse_args()
hf = os.environ.get("HF_TOKEN")
if hf is None:
    hf = getpass.getpass("HF token (Enter для открытой модели Qwen): ")
api = os.environ.get("API_TOKEN")
if api is None:
    api = getpass.getpass("API token (Enter, чтобы создать случайный): ") or secrets.token_urlsafe(32)
if len(api) < 16:
    raise SystemExit("API token должен содержать хотя бы 16 символов")
manifest = {"apiVersion": "v1", "kind": "List", "items": [
    {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": name, "namespace": args.namespace},
     "type": "Opaque", "stringData": {"token": value}}
    for name, value in (("hf-token", hf), ("api-token", api))
]}
subprocess.run(["kubectl", "apply", "-f", "-"], input=json.dumps(manifest), text=True, check=True)
print("Секреты созданы. Команда для чтения API token есть в README.")
