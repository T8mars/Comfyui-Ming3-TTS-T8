"""Explicit installation of checksum-pinned Windows components; never installs pip packages."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request

ROOT=Path(__file__).resolve().parent


def safe_target(root,relative):
    path=PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative:
        raise ValueError("Invalid component path")
    target=(Path(root)/relative).resolve()
    if not target.is_relative_to(Path(root).resolve()):raise ValueError("Component path escapes installation")
    if not relative.startswith(("components/","licenses/")):raise ValueError("Unexpected component destination")
    return target


def file_hash(path):
    checksum=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda:stream.read(8*1024**2),b""):checksum.update(block)
    return checksum.hexdigest()


def download_component(target,url,size,checksum,opener=urllib.request.urlopen):
    target=Path(target)
    if target.is_file() and target.stat().st_size==size and file_hash(target)==checksum:return False
    target.parent.mkdir(parents=True,exist_ok=True)
    partial=target.with_name(target.name+".part")
    try:
        digest=hashlib.sha256();count=0
        with opener(url,timeout=90) as response,partial.open("wb") as output:
            while block:=response.read(1024**2):
                output.write(block);digest.update(block);count+=len(block)
        if count!=size or digest.hexdigest()!=checksum:raise ValueError(f"Component integrity check failed: {target.name}")
        partial.replace(target)
    finally:partial.unlink(missing_ok=True)
    return True


def install_components(root=ROOT):
    root=Path(root)
    manifest=json.loads((root/"components/component-manifest.json").read_text(encoding="utf-8"))
    assert manifest["repo_id"]=="t8star/Ming3-TTS-Comfy" and re.fullmatch(r"[0-9a-f]{40}",manifest["revision"])
    for index,item in enumerate(manifest["files"],1):
        target=safe_target(root,item["path"])
        url=f"https://huggingface.co/{manifest['repo_id']}/resolve/{manifest['revision']}/{urllib.parse.quote(item['path'],safe='/')}"
        updated=download_component(target,url,item["size"],item["sha256"])
        print(f"[{index}/{len(manifest['files'])}] {'Installed' if updated else 'Verified'} {item['path']}",flush=True)


if __name__=="__main__":
    if os.name!="nt":
        print("Prebuilt native components target Windows x64; skipped on this platform.")
    else:
        try:install_components()
        except Exception as error:
            print(f"Component installation failed: {error}. Run this install.py again to retry.",file=sys.stderr)
            raise SystemExit(1)
