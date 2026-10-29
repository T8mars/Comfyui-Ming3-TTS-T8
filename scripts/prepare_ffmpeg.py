"""Fetch the official-download-page-listed BtbN LGPL shared Windows build.

GitHub's release asset SHA256 is checked before extraction. Record the immutable
asset id, release metadata, and original license/build documents alongside it.
"""
from pathlib import Path
import hashlib
import json
import sys
import urllib.request
import zipfile

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from ming_t8.config import data_directory

folder=data_directory("components/ffmpeg")
folder.mkdir(parents=True,exist_ok=True)
request=urllib.request.Request("https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/tags/latest",headers={"User-Agent":"Ming3-T8-native-build"})
with urllib.request.urlopen(request,timeout=30) as response:release=json.load(response)
asset=next(item for item in release["assets"] if item["name"]=="ffmpeg-n8.1-latest-win64-lgpl-shared-8.1.zip")
expected=asset.get("digest","").removeprefix("sha256:")
if len(expected)!=64:raise RuntimeError("Release does not publish SHA256; refusing an unverified binary")
archive=folder/asset["name"]
if not archive.is_file():
    temporary=archive.with_suffix(".zip.part")
    from download_models import parallel_download
    parallel_download(temporary,asset["browser_download_url"],asset["size"],4)
    if hashlib.sha256(temporary.read_bytes()).hexdigest()!=expected:raise RuntimeError("FFmpeg SHA256 mismatch")
    temporary.replace(archive)
    temporary.with_name(temporary.name+".ranges.json").unlink(missing_ok=True)
if hashlib.sha256(archive.read_bytes()).hexdigest()!=expected:raise RuntimeError("Existing FFmpeg archive SHA256 mismatch")
with zipfile.ZipFile(archive) as source:
    for item in source.infolist():
        parts=Path(item.filename).parts
        if item.is_dir() or ".." in parts:continue
        relative=Path(*parts[1:])
        if relative.parts[0] in ("include","lib"):continue
        target=folder/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        with source.open(item) as stream,target.open("wb") as output:
            while block:=stream.read(1024**2):output.write(block)
manifest={"provider":"BtbN/FFmpeg-Builds","official_listing":"https://ffmpeg.org/download.html",
          "release_id":release["id"],"published_at":release["published_at"],"asset_id":asset["id"],
          "source":asset["browser_download_url"],"sha256":expected,"size":asset["size"],
          "variant":"LGPL shared; unmodified executable and replaceable shared libraries"}
(folder/"source-manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
print(json.dumps(manifest,indent=2))
