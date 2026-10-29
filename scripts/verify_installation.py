"""Offline package integrity/runtime check, without fetching or upgrading anything."""
from pathlib import Path
import argparse
import hashlib
import json
import sys

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
parser=argparse.ArgumentParser()
parser.add_argument("--full-hash",action="store_true")
args=parser.parse_args()
from ming_t8.config import configuration
from ming_t8.asr import ASR
import torch
import torchaudio
import transformers
from ming_t8.cuda_kernels import status
report={"python":sys.version,"executable":sys.executable,"prefix":sys.prefix,"torch":torch.__version__,"torchaudio":torchaudio.__version__,"transformers":transformers.__version__,
        "cuda_available":torch.cuda.is_available(),"settings":configuration(),"asr":ASR.available(),"native_kernels":status(),"integrity":[]}
manifest=root/"bundle-manifest.json"
if manifest.is_file():
    document=json.loads(manifest.read_text(encoding="utf-8"))
    for asset in document["assets"]:
        path=root/asset["path"]
        valid=path.is_file() and path.stat().st_size==asset["size"]
        if valid and args.full_hash:
            digest=hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda:stream.read(8*1024**2),b""):digest.update(block)
            valid=digest.hexdigest()==asset["sha256"]
        report["integrity"].append({"path":asset["path"],"valid":valid})
    if not all(item["valid"] for item in report["integrity"]):
        print(json.dumps(report,ensure_ascii=False,indent=2));raise SystemExit("整合包校验失败")
print(json.dumps(report,ensure_ascii=False,indent=2))
