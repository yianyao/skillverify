#!/usr/bin/env python3
"""并发调度脚本：把 100 个子任务派给子进程跑，收集每个的退出码并汇总。

每个子任务 = 一个真实子进程（python -c），用 ThreadPoolExecutor 并发派发
（线程只负责等待子进程，实际工作都在子进程中完成）。
"""

import concurrent.futures
import subprocess
import sys

# 子任务执行的代码：模拟工作后按传入比例决定退出码
TASK_CODE = """
import random, sys, time
time.sleep(random.uniform(0.05, 0.3))  # 模拟耗时
sys.exit(0 if random.random() > 0.1 else random.choice([1, 2, 3]))
"""


def run_task(task_id: int) -> tuple[int, int]:
    """派发一个子任务，返回 (task_id, 退出码)。"""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", TASK_CODE],
            capture_output=True,
            timeout=60,
        )
        return task_id, proc.returncode
    except Exception as exc:
        print(f"任务 {task_id} 异常: {exc}", file=sys.stderr)
        return task_id, -1


def main() -> int:
    total = 100
    results = {}  # task_id -> exit_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(run_task, i) for i in range(total)]
        for fut in concurrent.futures.as_completed(futures):
            task_id, code = fut.result()
            results[task_id] = code

    # 汇总
    by_code = {}
    for code in results.values():
        by_code[code] = by_code.get(code, 0) + 1

    print("=" * 40)
    print(f"总任务数: {total}")
    print(f"已收集退出码: {len(results)}")
    print("退出码分布:")
    for code in sorted(by_code):
        print(f"  退出码 {code}: {by_code[code]} 个任务")
    failed = total - by_code.get(0, 0)
    print(f"成功: {by_code.get(0, 0)}，失败: {failed}")
    print("=" * 40)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
