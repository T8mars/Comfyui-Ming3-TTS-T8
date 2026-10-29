"""Download the exact cp312/Torch2.8/CUDA12.8 candidate, verify, then install without deps."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import urllib.request

source = "https://github.com/Rogala/AI_Attention/blob/main/python-3.12/2.8.0%2Bcu128/flash_attn-2.8.3-cp312-cp312-win_amd64.whl"
url = "https://media.githubusercontent.com/media/Rogala/AI_Attention/main/python-3.12/2.8.0%2Bcu128/flash_attn-2.8.3-cp312-cp312-win_amd64.whl"
expected = "04d5f29e3a96a3acac7152f45170c9ed079a1f3708b6ed178967dc6818011f8b"
import torch
if sys.version_info[:2] != (3,12) or not torch.__version__.startswith("2.8.") or torch.version.cuda != "12.8":
    raise SystemExit("This candidate is only for standalone cp312/Torch2.8/CUDA12.8")
folder = Path("D:/Ming3-TTS-data/wheels")
folder.mkdir(parents=True, exist_ok=True)
target = folder / "flash_attn-2.8.3-cp312-cp312-win_amd64.whl"
if not target.is_file():
    temporary = target.with_suffix(".whl.part")
    with urllib.request.urlopen(url, timeout=30) as response, temporary.open("wb") as destination:
        while block := response.read(1024**2):
            destination.write(block)
    if hashlib.sha256(temporary.read_bytes()).hexdigest() != expected:
        raise RuntimeError("FlashAttention wheel SHA256 mismatch")
    temporary.replace(target)
if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
    raise RuntimeError("Existing FlashAttention wheel SHA256 mismatch")
manifest = {"source":source,"sha256":expected,"size":target.stat().st_size,"validated_inference":False}
(folder / "flash-attention-source.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
subprocess.run([sys.executable,"-m","pip","install","--no-deps",str(target)],check=True)
print(json.dumps(manifest,indent=2))
