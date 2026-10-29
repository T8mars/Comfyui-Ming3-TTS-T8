"""Local native model picker; this helper never imports or runs inference."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys

KINDS={"model_file","bf16_dir","assets_dir","asr_dir"}


def choose_path(kind,initial=""):
    if not isinstance(kind,str) or kind not in KINDS:
        raise ValueError("不支持此路径选择方式")
    command=[sys.executable,"-X","utf8",str(Path(__file__).resolve()),kind,"--initial",str(initial)]
    try:
        result=subprocess.run(command,capture_output=True,text=True,encoding="utf-8",timeout=600,
                              creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        document=json.loads(result.stdout.strip())
    except subprocess.TimeoutExpired as error:
        raise ValueError("路径选择已超时，请重新选择或手动填写路径") from error
    except (OSError,ValueError) as error:
        raise ValueError("无法打开文件选择器，也可以手动填写路径") from error
    if result.returncode or document.get("error"):
        raise ValueError("文件选择器不可用，也可以手动填写路径")
    if not document.get("path"):
        return {"path":None,"cancelled":True}
    selected=Path(document["path"]).resolve(strict=True)
    if kind=="model_file":
        if not selected.is_file() or selected.suffix.lower()!=".safetensors":
            raise ValueError("请选择safetensors格式的单文件模型")
    elif not selected.is_dir():
        raise ValueError("请选择文件夹")
    required={"bf16_dir":("model.safetensors.index.json",),"assets_dir":("config.json","tokenizer.json","campplus.onnx")}.get(kind,())
    missing=[name for name in required if not (selected/name).is_file()]
    if missing:
        raise ValueError("所选目录缺少："+"、".join(missing))
    return {"path":str(selected),"cancelled":False}


def main():
    parser=argparse.ArgumentParser();parser.add_argument("kind",choices=sorted(KINDS));parser.add_argument("--initial",default="")
    args=parser.parse_args()
    import tkinter as tk
    from tkinter import filedialog
    initial=Path(args.initial).expanduser()
    if initial.is_file():initial=initial.parent
    if not initial.is_dir():initial=Path.home()
    root=tk.Tk()
    root.title("明 · 模型路径选择")
    root.configure(bg="#fff7fa")
    root.resizable(False,False)
    width,height=440,125
    root.geometry(f"{width}x{height}+{max(0,(root.winfo_screenwidth()-width)//2)}+{max(0,(root.winfo_screenheight()-height)//2)}")
    tk.Label(root,text="请在系统窗口中选择模型或文件夹",bg="#fff7fa",fg="#573d49",font=("Microsoft YaHei UI",12)).pack(pady=(27,8))
    tk.Label(root,text="取消会保留原路径，选择后仍需在工作台保存设置。",bg="#fff7fa",fg="#8d6e7d").pack()
    root.attributes("-topmost",True)
    # Keep a named owner in the taskbar so the system dialog can be found again
    # if the user switches back to their browser while choosing a path.
    root.update()
    try:
        titles={"model_file":"选择Ming单文件模型","bf16_dir":"选择Ming原始BF16模型目录","assets_dir":"选择Ming辅助文件目录","asr_dir":"选择Confucius项目或组件目录"}
        common={"parent":root,"title":titles[args.kind],"initialdir":str(initial)}
        selected=filedialog.askopenfilename(**common,filetypes=[("Ming模型","*.safetensors")]) if args.kind=="model_file" else filedialog.askdirectory(**common,mustexist=True)
        print(json.dumps({"path":selected or None},ensure_ascii=False),flush=True)
    finally:root.destroy()


if __name__=="__main__":
    try:main()
    except Exception as error:
        print(json.dumps({"error":str(error)},ensure_ascii=False),flush=True)
        raise SystemExit(1)
