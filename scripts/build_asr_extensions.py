"""Build just the namespaced Confucius Python adapter against pinned local libraries."""
from pathlib import Path
import subprocess

root=Path(__file__).resolve().parents[1]
cmake=Path("E:/comfyui-t8-onekey-5x/python/Lib/site-packages/cmake/data/bin/cmake.exe")
interpreters={"cp310":"E:/comfyui-t8-onekey-5x/python/python.exe","cp312":"D:/Ming3-TTS-data/runtime/Scripts/python.exe"}
for abi,python in interpreters.items():
    build=Path(f"D:/Ming3-TTS-data/build/confucius-{abi}")
    subprocess.run([str(cmake),"-S",str(root/"native/confucius"),"-B",str(build),"-G","Visual Studio 17 2022","-A","x64",
        f"-DPython_EXECUTABLE={python}","-Dpybind11_DIR=E:/Confucius4-R2T2/.runtime/worker/Lib/site-packages/pybind11/share/cmake/pybind11",
        "-DLLAMA_CPP_DIR=E:/Confucius4-R2T2/.reference/llama.cpp","-DLLAMA_BUILD_DIR=E:/Confucius4-R2T2/.runtime/build-native-cu128"],check=True)
    subprocess.run([str(cmake),"--build",str(build),"--config","Release","--parallel","4"],check=True)
