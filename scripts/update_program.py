"""Update the program without changing its Python environment, models or user data."""
from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--apply-pending", action="store_true")
    group.add_argument("--update", action="store_true")
    args = parser.parse_args()
    from ming_t8.updates import Updates, UpdateRolledBack, apply_pending, studio_lock
    if args.update:
        with studio_lock(ROOT):
            manager = Updates(ROOT)
            manager.start(download=True)
            manager.worker.join()
            state = manager.status()
            print(state["message"], flush=True)
            if state["status"] not in {"up_to_date", "ready"}:
                return 1
    try:
        changed = apply_pending(ROOT)
    except UpdateRolledBack as error:
        print(str(error), flush=True)
        if args.apply_pending:
            print("继续启动已恢复的原工作台。", flush=True)
            return 0
        return 1
    print("程序更新已安装，Python、模型和用户数据已保留。" if changed else "程序已就绪。", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"程序更新未能完成：{error}", file=sys.stderr, flush=True)
        raise SystemExit(1)
