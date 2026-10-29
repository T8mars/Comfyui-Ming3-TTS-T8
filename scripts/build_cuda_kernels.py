"""Build our small ABI-independent CUDA DLL using the installed CUDA/VS toolchain."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import time

root = Path(__file__).resolve().parents[1]
nvcc = shutil.which("nvcc")
if not nvcc:
    raise SystemExit("CUDA Toolkit nvcc not found")
env = dict(os.environ)
if not shutil.which("cl"):
    vswhere = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft Visual Studio/Installer/vswhere.exe"
    install = subprocess.check_output([str(vswhere), "-latest", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"], text=True).strip()
    setup = Path(install) / "Common7/Tools/VsDevCmd.bat"
    output = subprocess.check_output([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", f'""{setup}" -arch=x64 >nul && set"'], text=True)
    for line in output.splitlines():
        if "=" in line and not line.startswith("="):
            key, value = line.split("=", 1)
            env[key] = value
build = Path("D:/Ming3-TTS-data/build/cuda-kernels")
build.mkdir(parents=True, exist_ok=True)
target = build / "ming_cuda.dll"
command = [nvcc, "--shared", "-O3", "--fmad=false", "-Xcompiler", "/MD", str(root / "native/kernels/ming_cuda.cu"), "-o", str(target)]
for arch in (80, 86, 89, 90, 100, 120):
    command += ["-gencode", f"arch=compute_{arch},code=sm_{arch}"]
command += ["-gencode", "arch=compute_120,code=compute_120"]
started = time.time()
subprocess.run(command, cwd=build, env=env, check=True)
destination = root / "components/cuda"
destination.mkdir(parents=True, exist_ok=True)
shutil.copy2(target, destination / target.name)
manifest = {"version": 1, "cuda": "12.8", "architectures": [80,86,89,90,100,120],
            "source_sha256": hashlib.sha256((root / "native/kernels/ming_cuda.cu").read_bytes()).hexdigest(),
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "build_seconds": time.time()-started}
(destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print(json.dumps(manifest, indent=2))
