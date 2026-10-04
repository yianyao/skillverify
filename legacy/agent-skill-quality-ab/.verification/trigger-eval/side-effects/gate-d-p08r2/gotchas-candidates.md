# gotchas 候选池（gate-d 双跑过程发现）

1. **setup-html-to-docx.sh Windows 路径 bug**（来源：Arm-A Stage 3）：脚本硬编码 `PY="$VENV_DIR/bin/python"`，Windows Git Bash 下 uv venv 生成 `Scripts/python.exe`，导致依赖检查全部误判、`uv pip install` 静默失败（stderr 被 >/dev/null 吞掉）、冒烟测试前的步骤全部空转。修法：按平台选 `Scripts/python.exe` / `bin/python`，并给 uv 安装步骤加失败即退。
2. **python-docx 裸写中文文档不设 eastAsia 字体**（来源：Arm-B）：无技能约束时高频翻车点，建议作为"裸执行 vs 技能"演示的标准对照项。
3. **grade_ab.py --cost 口径**：按报告 md 字符数÷4 粗估，只覆盖报告文本，不覆盖中间产物与技能加载上下文，演示时须注明"实际执行成本差异远大于此"。
