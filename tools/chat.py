"""Small terminal client. Server logs remain private; answers appear only here."""
import argparse
import base64
import json
import os
import subprocess
import urllib.error
import urllib.request

def main():
    parser = argparse.ArgumentParser(description="Клиент локальной модели")
    parser.add_argument("--base-url", default="http://127.0.0.1:18001")
    args = parser.parse_args()
    token = os.environ.get("API_TOKEN")
    if not token:
        encoded = subprocess.check_output([
            "kubectl", "-n", "llm-cpu", "get", "secret", "api-token", "-o", "jsonpath={.data.token}"
        ])
        token = base64.b64decode(encoded).decode()
    print("Введите вопрос. Для выхода: /exit.")
    print("Каждый вопрос отправляется отдельно. Окно port-forward должно оставаться открытым.")
    while True:
        try:
            question = input("\nВы: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if question.lower() == "/exit":
            return
        if not question:
            continue
        data = json.dumps({
            "model": "qwen-cpu", "messages": [{"role": "user", "content": question}],
            "max_tokens": 128,
        }).encode("utf-8")
        request = urllib.request.Request(
            args.base_url.rstrip("/") + "/v1/chat/completions", data=data,
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        )
        print("Жду ответ модели на CPU...", flush=True)
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                result = json.load(response)
            print("\nМодель:", result["choices"][0]["message"]["content"])
        except urllib.error.HTTPError as error:
            print("API error:", error.code, "(check model readiness and question length)")
        except (urllib.error.URLError, TimeoutError, OSError):
            print("Нет соединения. Проверьте port-forward и готовность модели.")
        except (ValueError, KeyError, IndexError):
            print("API вернул неожиданный формат ответа.")
        except KeyboardInterrupt:
            print("\nОстановлено.")
            return

if __name__ == "__main__":
    main()
