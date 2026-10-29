"""Download pinned model assets directly, with resume and SHA256 verification."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import threading
import urllib.request
from filelock import FileLock

REPOSITORIES = {
    "comfy": ("Comfy-Org/Ming-3.0-TTS", "bfabd8d02bf0410ebb6cff1444d1d7b7b26212e1"),
    "official": ("inclusionAI/Ming-3.0-tts-tiny", "7bd9446a8d47e462362261a0150258da6d458318"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch_json(url: str):
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def parallel_download(partial: Path, url: str, size: int, workers: int):
    """Persist completed byte ranges; a retry never trusts preallocated file size."""
    checkpoint = partial.with_name(partial.name + ".ranges.json")
    if checkpoint.is_file():
        state = json.loads(checkpoint.read_text(encoding="utf-8"))
        if state["size"] != size or state["url"] != url:
            raise RuntimeError("Resume manifest does not match requested model")
    else:
        prefix = partial.stat().st_size if partial.exists() else 0
        state = {"url": url, "size": size, "prefix": prefix, "done": []}
        with partial.open("ab") as destination:
            destination.truncate(size)
    lock = threading.Lock()
    chunk = 8 * 1024 * 1024
    previous_chunk = state.get("chunk_size", 64 * 1024 * 1024)
    if previous_chunk != chunk:
        if previous_chunk % chunk:
            raise RuntimeError("Unsupported resume range granularity")
        state["done"] = [part for start in state["done"] for part in range(start, min(start + previous_chunk, size), chunk)]
    state["chunk_size"] = chunk
    starts = list(range(state["prefix"], size, chunk))
    done = set(state["done"])
    initial_received = state["prefix"] + sum(min(chunk,size-item) for item in done)
    started = time.monotonic()

    def save():
        state["done"] = sorted(done)
        temporary = checkpoint.with_name(checkpoint.name + ".tmp")
        temporary.write_text(json.dumps(state), encoding="utf-8")
        os.replace(temporary, checkpoint)

    def transfer(start):
        end = min(start + chunk, size) - 1
        for attempt in range(12):
            try:
                request = urllib.request.Request(
                    url + f"?download=true&range={start}&attempt={int(time.time())}",
                    headers={"Range": f"bytes={start}-{end}", "User-Agent": "T8-Ming-TTS/0.1"},
                )
                attempt_started = time.monotonic()
                with urllib.request.urlopen(request, timeout=25) as response:
                    content_range = response.headers.get("Content-Range", "")
                    if response.status != 206 or not content_range.startswith(f"bytes {start}-{end}/"):
                        raise RuntimeError(f"Server did not honor range {start}-{end}: {content_range}")
                    offset = start
                    with partial.open("r+b", buffering=0) as destination:
                        destination.seek(start)
                        while offset <= end:
                            if time.monotonic() - attempt_started > 600:
                                raise TimeoutError("Range transfer exceeded 600 seconds; retrying this small range")
                            block = response.read1(min(1024 * 1024, end + 1 - offset))
                            if not block:
                                raise IOError("Unexpected end of range")
                            destination.write(block)
                            offset += len(block)
                with lock:
                    done.add(start)
                    save()
                    received = state["prefix"] + sum(min(chunk, size - item) for item in done)
                    speed = (received - initial_received) / max(time.monotonic() - started, .001) / 1024**2
                    print(f"RANGES {partial.name} {received}/{size} {100*received/size:.1f}% {speed:.1f} MiB/s", flush=True)
                return
            except Exception as error:
                print(f"RANGE_RETRY {start} {attempt+1}/12 {error}", flush=True)
                time.sleep(min(attempt + 1, 10))
        raise RuntimeError(f"Range download exhausted retries: {start}-{end}")

    with lock:
        save()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(transfer, start) for start in starts if start not in done]
        for future in as_completed(futures):
            future.result()


def download(root: Path, repo: str, revision: str, entry: dict, workers: int = 8) -> dict:
    target = root / entry["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    expected = entry.get("lfs", {}).get("oid")
    expected_size = entry["size"]
    if target.is_file() and target.stat().st_size == expected_size:
        actual = sha256(target)
        if expected is None or actual == expected:
            print(f"VERIFIED {entry['path']} {actual}", flush=True)
            return {"path": entry["path"], "size": expected_size, "sha256": actual}
        raise RuntimeError(f"Existing asset has incorrect SHA256: {target}")
    partial = target.with_name(target.name + ".part")
    free = shutil.disk_usage(root).free
    remaining = expected_size - (partial.stat().st_size if partial.exists() else 0)
    if free < remaining + 512 * 1024 * 1024:
        raise RuntimeError(f"Insufficient space for {target}: need {remaining:,}, free {free:,}")
    if expected_size > 128 * 1024 * 1024 and workers > 1:
        parallel_download(partial, f"https://huggingface.co/{repo}/resolve/{revision}/{entry['path']}", expected_size, workers)
        actual = sha256(partial)
        if expected and actual != expected:
            raise RuntimeError(f"SHA256 mismatch for {partial}")
        os.replace(partial, target)
        partial.with_name(partial.name + ".ranges.json").unlink(missing_ok=True)
        print(f"VERIFIED {entry['path']} {actual}", flush=True)
        return {"path": entry["path"], "size": expected_size, "sha256": actual}
    last_error = None
    for attempt in range(12):
        offset = partial.stat().st_size if partial.exists() else 0
        url = f"https://huggingface.co/{repo}/resolve/{revision}/{entry['path']}?download=true&attempt={int(time.time())}"
        headers = {"User-Agent": "T8-Ming-TTS-model-manager/0.1"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=90) as response:
                if offset and response.status != 206:
                    offset = 0
                if response.status == 206:
                    content_range = response.headers.get("Content-Range", "")
                    if not content_range.startswith(f"bytes {offset}-"):
                        raise RuntimeError(f"Invalid resume response: {content_range}")
                mode = "ab" if offset else "wb"
                started, last_report, initial = time.monotonic(), 0.0, offset
                with partial.open(mode) as destination:
                    while block := response.read(4 * 1024 * 1024):
                        destination.write(block)
                        offset += len(block)
                        now = time.monotonic()
                        if now - last_report >= 10:
                            rate = (offset - initial) / max(now - started, .001) / 1024**2
                            print(f"DOWNLOAD {entry['path']} {offset}/{expected_size} {100*offset/max(expected_size,1):.1f}% {rate:.1f} MiB/s", flush=True)
                            destination.flush()
                            last_report = now
            if partial.stat().st_size != expected_size:
                raise RuntimeError(f"Incomplete asset: {partial.stat().st_size}/{expected_size}")
            actual = sha256(partial)
            if expected is not None and actual != expected:
                raise RuntimeError(f"SHA256 mismatch for {partial}; preserved for inspection")
            os.replace(partial, target)
            print(f"VERIFIED {entry['path']} {actual}", flush=True)
            return {"path": entry["path"], "size": expected_size, "sha256": actual}
        except Exception as error:
            last_error = error
            print(f"RETRY {attempt+1}/12 {entry['path']}: {error}", flush=True)
            if "SHA256 mismatch" in str(error):
                raise
            time.sleep(min(attempt + 1, 10))
    raise RuntimeError(f"Unable to download {entry['path']}: {last_error}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=REPOSITORIES)
    parser.add_argument("--root", type=Path, default=Path("D:/Ming3-TTS-data/models"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--assets-only", action="store_true")
    parser.add_argument("--file-workers", type=int, default=1)
    args = parser.parse_args()
    repo, revision = REPOSITORIES[args.kind]
    root = args.root / ("Ming-Comfy-INT8" if args.kind == "comfy" else "Ming-3.0-tts-tiny")
    root.mkdir(parents=True, exist_ok=True)
    with FileLock(str(root / ".download.lock"), timeout=0.5, poll_interval=0.025):
        download_repository(root, repo, revision, args)


def download_repository(root, repo, revision, args):
    entries = fetch_json(f"https://huggingface.co/api/models/{repo}/tree/{revision}?recursive=true")
    assets = []
    manifest_lock = threading.Lock()
    selected = [entry for entry in entries if entry["type"] == "file"
                and not (args.assets_only and entry["size"] > 64 * 1024 * 1024)]

    def process(entry):
        asset = download(root, repo, revision, entry, args.workers)
        with manifest_lock:
            assets.append(asset)
            manifest = {"repo": repo, "revision": revision, "assets": assets}
            temporary = root / "download-manifest.json.tmp"
            temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(root / "download-manifest.json")
    with ThreadPoolExecutor(max_workers=args.file_workers) as executor:
        futures = [executor.submit(process, entry) for entry in selected]
        for future in as_completed(futures):
            future.result()
    print(f"COMPLETE {root}", flush=True)


if __name__ == "__main__":
    main()
