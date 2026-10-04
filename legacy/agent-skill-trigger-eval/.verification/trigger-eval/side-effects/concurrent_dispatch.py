#!/usr/bin/env python3
"""并发调度脚本：把 100 个子任务派给子进程跑，收集每个的退出码并汇总。"""
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

TOTAL = 100        # 子任务总数
MAX_WORKERS = 10   # 最大并发数（同时最多 10 个子进程）


def run_task(task_id: int) -> tuple[int, int]:
    """运行一个子任务，返回 (任务ID, 退出码)。"""
    cmd = [sys.executable, "-c", f"""
import random, sys, time
time.sleep(random.uniform(0.1, 0.5))   # 模拟真实工作负载
sys.exit(random.choice([0, 0, 0, 1, 2]))  # 模拟成功/失败
"""]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return task_id, proc.returncode


def main() -> None:
    print(f"开始并发调度 {TOTAL} 个子任务，最大并发 {MAX_WORKERS} ...")

    # 线程池只负责并发发起 subprocess（子进程才是真正的并行执行体）
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        results = list(pool.map(run_task, range(1, TOTAL + 1)))

    # ---- 汇总 ----
    success = [tid for tid, code in results if code == 0]
    failed = [(tid, code) for tid, code in results if code != 0]

    print("\n========== 汇总 ==========")
    print(f"总任务数 : {len(results)}")
    print(f"成功     : {len(success)} (退出码 0)")
    print(f"失败     : {len(failed)}")

    if failed:
        print("\n失败明细（任务ID -> 退出码）:")
        for tid, code in failed:
            print(f"  任务 {tid:>3} -> 退出码 {code}")

    # 整体退出码：全部成功为 0，否则为 1
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
