"""Streaming benchmark. Standard library only; does not save prompt/output text."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
import statistics
import time
import urllib.request

def request(base, token, prompt, output_tokens, timeout):
    body = json.dumps({"model": "qwen-cpu", "messages": [{"role": "user", "content": prompt}],
                       "max_tokens": output_tokens, "temperature": 0, "stream": True,
                       "stream_options": {"include_usage": True}, "ignore_eos": True}).encode()
    req = urllib.request.Request(base.rstrip("/") + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
    started = time.perf_counter()
    first = None
    usage = None
    with urllib.request.urlopen(req, timeout=timeout) as response:
        for raw in response:
            if not raw.startswith(b"data: "):
                continue
            data = raw[6:].strip()
            if data == b"[DONE]":
                break
            chunk = json.loads(data)
            if chunk.get("error"):
                raise RuntimeError("Stream returned an error")
            for choice in chunk.get("choices", []):
                delta = choice.get("delta", {})
                if first is None and (delta.get("content") or delta.get("reasoning_content")):
                    first = time.perf_counter()
            if chunk.get("usage"):
                usage = chunk["usage"]
    finished = time.perf_counter()
    if first is None or usage is None:
        raise RuntimeError("Missing content or stream usage")
    return {"ttft_s": first - started, "latency_s": finished - started,
            "prompt_tokens": usage["prompt_tokens"], "completion_tokens": usage["completion_tokens"]}

def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]

def summarize(label, results, wall_seconds, concurrency):
    successful = [result for result in results if result is not None]
    if not successful:
        raise RuntimeError("All requests failed; no benchmark metrics produced")

    first_token_times = [result["ttft_s"] for result in successful]
    latencies = [result["latency_s"] for result in successful]
    output_tokens = sum(result["completion_tokens"] for result in successful)
    return {
        "scenario": label,
        "requests": len(results),
        "success": len(successful),
        "failed": len(results) - len(successful),
        "concurrency": concurrency,
        "prompt_tokens_mean": statistics.mean(result["prompt_tokens"] for result in successful),
        "ttft_p50_s": statistics.median(first_token_times),
        "ttft_p95_s": percentile(first_token_times, .95),
        "latency_p50_s": statistics.median(latencies),
        "latency_p95_s": percentile(latencies, .95),
        "throughput_tokens_s": output_tokens / wall_seconds,
        "throughput_requests_s": len(successful) / wall_seconds,
        "wall_s": wall_seconds,
    }

def save_results(output, settings, rows, samples):
    output.mkdir(parents=True, exist_ok=True)
    data = {"settings": settings, "results": rows, "samples": samples}
    (output / "results.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    table = ["| Prompt | Tokens in | Success | TTFT p50 / p95 s | Latency p50 / p95 s | Output tok/s | Req/s |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for row in rows:
        table.append(
            f"| {row['scenario']} | {row['prompt_tokens_mean']:.0f} | {row['success']}/{row['requests']} | "
            f"{row['ttft_p50_s']:.3f} / {row['ttft_p95_s']:.3f} | "
            f"{row['latency_p50_s']:.3f} / {row['latency_p95_s']:.3f} | "
            f"{row['throughput_tokens_s']:.3f} | {row['throughput_requests_s']:.3f} |"
        )
    (output / "results.md").write_text("\n".join(table) + "\n", encoding="utf-8")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18001")
    parser.add_argument("--requests", type=int, default=12)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--output-tokens", type=int, default=32)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--output", default="reports/local")
    args = parser.parse_args()
    if min(args.requests, args.concurrency, args.output_tokens) < 1:
        parser.error("Counts must be positive")
    token = os.environ.get("API_TOKEN")
    if not token:
        parser.error("Set API_TOKEN")
    prompts = {"short": "Explain what a database index does in one sentence.",
               "long": ("A database stores records and an index accelerates lookup. " * 80)
                       + "Summarize this text in one sentence."}
    rows, samples = [], []
    for label, prompt in prompts.items():
        request(args.base_url, token, prompt, 4, args.timeout)  # excluded warm-up
        def measured(_):
            try:
                return request(args.base_url, token, prompt, args.output_tokens, args.timeout)
            except Exception:
                return None
        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            results = list(pool.map(measured, range(args.requests)))
        wall = time.perf_counter() - start
        try:
            row = summarize(label, results, wall, args.concurrency)
        except RuntimeError as error:
            raise SystemExit(str(error)) from None
        rows.append(row)
        samples.append({"scenario": label, "samples": [result for result in results if result is not None]})
        print(json.dumps(row), flush=True)
    save_results(Path(args.output), vars(args), rows, samples)
    if any(row["failed"] for row in rows):
        raise SystemExit("Some requests failed; inspect the failure counts")

if __name__ == "__main__":
    main()
