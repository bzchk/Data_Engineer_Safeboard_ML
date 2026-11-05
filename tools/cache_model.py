"""Загрузка фиксированной ревизии модели с проверкой локального кэша."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request


@contextmanager
def cache_lock(path):
    # На сервере используется flock. Ветка Windows нужна для локальных unit-тестов.
    with path.open("a+b") as lock:
        if os.name == "nt":
            import msvcrt
            lock.seek(0, 2)
            if lock.tell() == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


def safe_path(name):
    if not isinstance(name, str) or not name:
        raise ValueError("Empty snapshot path")
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
        raise ValueError("Unsafe snapshot path")
    return relative


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        result = super().redirect_request(req, fp, code, msg, headers, newurl)
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise ValueError("HTTPS redirect required")
        if urllib.parse.urlsplit(req.full_url).netloc != urllib.parse.urlsplit(newurl).netloc:
            result.remove_header("Authorization")
        return result

def digest(path):
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()

def valid_snapshot(target, repo, revision):
    try:
        marker = json.loads((target / ".complete.json").read_text())
        return (marker["repo"] == repo and marker["revision"] == revision and bool(marker["files"])
                and "config.json" in marker["files"]
                and any(name.endswith(".safetensors") for name in marker["files"])
                and all((target / safe_path(name)).is_file() and digest(target / name) == sha
                        for name, sha in marker["files"].items()))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False

def download(repo, revision, root):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("MODEL_REVISION must be an immutable commit SHA")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("Invalid repository name")
    root.mkdir(parents=True, exist_ok=True)
    with cache_lock(root / ".download.lock"):
        target = root / "model"
        if valid_snapshot(target, repo, revision):
            print('{"event":"model_cache_hit"}', flush=True)
            return
        # Чужую ревизию или повреждённый кэш не заменяю незаметно.
        if target.exists():
            raise ValueError("Snapshot is corrupt or differs from configuration; use a new PVC")
        staging = root / ".staging"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir()
        opener = urllib.request.build_opener(SafeRedirect())
        token = os.environ.get("HF_TOKEN", "")

        def fetch(url, path=None):
            for attempt in range(4):
                try:
                    headers = {"User-Agent": "cpu-inference-assignment/1.0"}
                    if token:
                        headers["Authorization"] = "Bearer " + token
                    with opener.open(urllib.request.Request(url, headers=headers), timeout=120) as response:
                        if path is None:
                            return json.load(response)
                        with path.open("wb") as output:
                            shutil.copyfileobj(response, output, 1024 * 1024)
                    return
                except Exception:
                    if attempt == 3:
                        raise
                    time.sleep(2 ** attempt)

        metadata = fetch(f"https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true")
        if metadata["sha"] != revision:
            raise ValueError("Unexpected model revision")
        files = {}
        for item in metadata["siblings"]:
            name = item["rfilename"]
            relative = safe_path(name)
            if relative.suffix not in {".json", ".safetensors", ".model", ".tiktoken", ".txt", ".jinja"}:
                continue
            path = staging / name
            path.parent.mkdir(parents=True, exist_ok=True)
            fetch(f"https://huggingface.co/{repo}/resolve/{revision}/{urllib.parse.quote(name, safe='/')}", path)
            sha = digest(path)
            expected = item.get("lfs", {}).get("sha256")
            if expected and sha != expected:
                raise ValueError("Weight checksum mismatch")
            files[name] = sha
        if "config.json" not in files or not any(name.endswith(".safetensors") for name in files):
            raise ValueError("Missing model files")
        (staging / ".complete.json").write_text(json.dumps({"repo": repo, "revision": revision, "files": files}))
        staging.rename(target)
        print('{"event":"model_download_complete"}', flush=True)

if __name__ == "__main__":
    try:
        download(os.environ["MODEL_ID"], os.environ["MODEL_REVISION"], Path(os.environ.get("MODEL_ROOT", "/models")))
    except Exception:
        # В ошибку не включаю URL, токен или тело ответа Hugging Face.
        print('{"event":"model_download_failed"}', file=sys.stderr)
        sys.exit(1)
