"""Explicit download of pinned published model assets and local path configuration."""
from pathlib import Path
import argparse
import hashlib
import json

ROOT=Path(__file__).resolve().parents[1]


def configure_paths(project,destination):
    project=Path(project);destination=Path(destination).resolve()
    paths={"model_path":destination/"Ming-Comfy-INT8/checkpoints/ming_tts_tiny_int8_convrot.safetensors",
           "assets_path":destination/"Ming-3.0-tts-tiny","asr_root":destination/"Confucius4-R2T2"}
    if not paths["model_path"].is_file() or not (paths["assets_path"]/"campplus.onnx").is_file() or not (paths["asr_root"]/"models/Confucius4-R2T2-GGUF/Confucius4-R2T2-Q8_0.gguf").is_file():
        raise ValueError("Downloaded model layout is incomplete")
    config=project/"settings.local.json"
    settings=json.loads(config.read_text(encoding="utf-8-sig")) if config.is_file() else {}
    settings.update({name:str(path) for name,path in paths.items()})
    temporary=config.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(settings,ensure_ascii=False,indent=2),encoding="utf-8")
    temporary.replace(config)
    return settings


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination",type=Path,default=ROOT/"data/models")
    args=parser.parse_args()
    from huggingface_hub import hf_hub_download,snapshot_download
    source=json.loads((ROOT/"components/component-manifest.json").read_text(encoding="utf-8"))
    repo,revision=source["repo_id"],source["revision"]
    path=hf_hub_download(repo_id=repo,filename="manifest.json",revision=revision)
    manifest=json.loads(Path(path).read_text(encoding="utf-8"))
    wanted=[item for item in manifest["files"] if item["path"].startswith(("Ming-Comfy-INT8/","Ming-3.0-tts-tiny/","Confucius4-R2T2/","licenses/"))]
    destination=args.destination.expanduser().resolve();destination.mkdir(parents=True,exist_ok=True)
    print(f"Download/cache check: {sum(item['size'] for item in wanted):,} bytes in {len(wanted)} files",flush=True)
    snapshot_download(repo_id=repo,revision=revision,allow_patterns=[item["path"] for item in wanted],local_dir=destination,max_workers=4)
    for item in wanted:
        target=(destination/item["path"]).resolve(strict=True)
        if not target.is_relative_to(destination):raise ValueError("Invalid model manifest path")
        checksum=hashlib.sha256()
        with target.open("rb") as stream:
            for block in iter(lambda:stream.read(8*1024**2),b""):checksum.update(block)
        if target.stat().st_size!=item["size"] or checksum.hexdigest()!=item["sha256"]:raise ValueError(f"Model integrity check failed: {item['path']}")
    configure_paths(ROOT,destination)
    print("Models verified; settings.local.json configured. Restart ComfyUI.",flush=True)


if __name__=="__main__":main()
