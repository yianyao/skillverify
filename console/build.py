"""console/build.py —— 构建脚本（用法与产物见 console/README.md）。

步骤：
1. 子进程跑 build_nodes.py 生成 console/nodes.json（机械层 + 语义层合并与自检）；
2. 把 nodes.json 内联进 app/index.html 的
   `<script type="application/json" id="nodes-data">…</script>` 数据块；
3. 产出可分发单目录（index.html + app.js + style.css，双击即用，file:// 零网络依赖）。

幂等：重复运行产出字节一致（generated_at 时间戳除外）。
所有写入 UTF-8 + LF。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
CONSOLE = HERE.parent
APP = CONSOLE / "app"

NODES_BLOCK = re.compile(
    r'(<script type="application/json" id="nodes-data">)(.*?)(</script>)',
    re.DOTALL,
)


def run_generate(python_exe: str) -> None:
    proc = subprocess.run(
        [python_exe, str(CONSOLE / "build_nodes.py")],
        capture_output=True, text=True, encoding="utf-8", timeout=300,
    )
    sys.stdout.write(proc.stdout or "")
    sys.stderr.write(proc.stderr or "")
    if proc.returncode != 0:
        raise SystemExit(f"build: nodes.json 生成失败（exit {proc.returncode}）")


def inline_into_index(nodes_payload: dict) -> None:
    index_path = APP / "index.html"
    html = index_path.read_text(encoding="utf-8")
    payload_text = json.dumps(nodes_payload, ensure_ascii=False, indent=2)
    m = NODES_BLOCK.search(html)
    if not m:
        raise SystemExit("build: index.html 缺少 nodes-data 数据块，无法内联")
    html = NODES_BLOCK.sub(lambda mm: mm.group(1) + "\n" + payload_text + "\n  " + mm.group(3),
                           html, count=1)
    with open(index_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(html)


def main() -> int:
    python_exe = sys.executable
    run_generate(python_exe)
    nodes_path = CONSOLE / "nodes.json"
    payload = json.loads(nodes_path.read_text(encoding="utf-8"))
    inline_into_index(payload)
    print(f"build: 已内联 nodes.json（{len(payload['nodes'])} 个节点，"
          f"{payload['tool_version']}）→ app/index.html 双击可用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
