# 双评任务包 B（包编号：B）· W-08

**本包编号: B**（留痕时 record_review.py --package B）

**独立判定声明**: 本包由独立会话独立判定，不得参考另一份包的结论；同一会话内跑两遍不构成双评。判定不一致将升级人工裁决。

## 提示词（来自 w-prompts.md）

```text
你是 Agent Skill 安全评审员。以下是正文中涉及破坏性操作的段落（脚本已定位）与对应脚本：
<定位段落> <相关脚本>
判定：每个破坏性操作的防护措施（确认标志/备份提示/作用域限制/dry-run）是否与风险相称。
过轻（高危无防护）或过重（低危操作要求多步确认拖累效率）均指出。
输出：逐操作 PASS/FAIL + 风险评级（高/中/低）+ 建议。
```

## 待评审材料

### 输入: SKILL.md

```
---
name: agent-skill-llm-review
description: 对 Agent Skill 执行 LLM 语义评审（L 类）：按 D/W/E/R 生命周期阶段选择提示词、组织关键判定双评、记录 V12 留痕并汇总判定与人工裁决点。当用户要求评审技能、跑 W 组语义检查、对断言评分、做盲评、诊断轨迹、归纳 Gotchas，或需按《Agent-Skill 生命周期验证方案》执行 LLM 评审时使用。本技能不替代机械检查（check_skill.py）、人工终审与门禁裁决。
compatibility: 需要 Python 3.10+（scripts 仅用标准库）；运行于支持 Agent Skill 的宿主。
---

# Agent Skill LLM 评审执行助手

> 版本：v1.2（2026-10-01；v1.1 采纳技能自查评审：双评缺口须 ≥2 条记录、留痕带包编号、detect_stage 退出码区分误用。v1.2 含第二轮评审修复：detect_stage 补 M 键修 KeyError、SKILL.md §7 退出码描述同步、盲评标签改为"版本 A/B"与 E-06 对齐、留痕转义半角竖线、模板补双评记录示例；及第三轮起历轮同步修复：dual-review-rules/docstring 盲评标签对齐、detect_stage M 行 pid 改"（无）"、evals.json 版本同步、plan_dual_review 加 --skill-dir 校验与盲评同文件判重（realpath）、record_review HEADER 冒号对齐与换行防护、prompt-id 格式校验）

## 1. 定位与边界

- **能做**：阶段产物检测（仅建议）、提示词调度、双评任务包生成、V12 留痕、评审结果汇总与人工裁决点提示。
- **不能做（硬边界，违反即本技能自身评审 FAIL）**：
  1. 不替代 S 类机械检查（`check_skill.py`）、H 类人工终审（内容门 B / M1 审计）、K 类动态实测；
  2. 不在同一会话内完成双评（单会话跑两遍无效，见 §5）；
  3. 不自动放行任何 [M] 级失败（安全门 E4、V8、V13 仍须人工/隔日复审）；
  4. 阶段判定只是建议，不得作为"阶段已完成"的依据；
  5. 不写回/修改被评审技能的任何文件（description 写回归主流程并受 V28 约束）。

## 2. 工作流

1. 确定目标技能目录（应含 `.verification/` 留痕目录）。
2. 运行 `python scripts/detect_stage.py <skill_dir>` 获取阶段产物状态与应跑提示词组**建议**。
3. 按下表读取对应 references 文件，逐条投喂执行，PASS/FAIL 必须附证据引用。
4. ⚑ 提示词先运行 `python scripts/plan_dual_review.py` 生成双评任务包（规则见 §5 与 references/dual-review-rules.md）。
5. 每条评审完成**立即**运行 `python scripts/record_review.py` 留痕（勿攒批；双评记录分别带 `--package A` / `--package B`）。
6. 收尾运行 `python scripts/summarize_reviews.py` 汇总，向用户输出"人工裁决点"清单。

## 3. 阶段 → 提示词映射（权威口径，与清单 v1.2 一致）

| 阶段 | 必跑 | 双评 ⚑ |
| --- | --- | --- |
| D 设计期 | D-01（**可选辅助**：仅提炼材料；V1/V2 由人工设计评审与脚本预检完成，不属 L 类） | — |
| W 编写期 | W-01~W-16（全跑） | W-02、W-04、W-05、W-08、W-15 |
| E 测试期 | E-01~E-10（按实际测试项） | E-04、E-06 |
| R 运行期 | R-01、R-02 | R-02 |

## 4. 提示词加载时机

- 当需要提炼设计期取材材料时，读取 references/d-prompts.md（D-01）。
- 当进入编写期语义评审时，读取 references/w-prompts.md（W-01~W-16），按目标条目选用。
- 当测试期需要查询集评审、断言评分、盲评、模式归因或轨迹诊断时，读取 references/e-prompts.md（E-01~E-10）。
- 当运行期做纠错归纳或增长性内容隔离判定时，读取 references/r-prompts.md（R-01/R-02）。
- 当组织双评或盲评时，读取 references/dual-review-rules.md。

Read references/d-prompts.md when distilling design-stage source material. Read references/w-prompts.md when running writing-phase semantic review. Read references/e-prompts.md when scoring assertions, blind-reviewing, or diagnosing trajectories. Read references/r-prompts.md when consolidating corrections or judging growth content isolation. Read references/dual-review-rules.md when organizing dual review or blind evaluation.

## 5. 双评硬性规则（V12）

1. ⚑ 八项**必须双评**：W-02、W-04、W-05、W-08、W-15、E-04、E-06、R-02。
2. 双评 = **两个独立会话或两个不同模型**分别判定；本技能所在会话至多承担其中一份。
3. 同一会话内跑两遍**不构成双评**，留痕时不得标"双评=是"。
4. 任务包由 `plan_dual_review.py` 生成后，由**人工**分别开两个会话投喂；结果分别留痕。
5. 双评分歧 → 升级人工裁决并记录理由；不得自动取其一，不得只留胜出方。

## 6. 留痕（V12）

每条评审一行，字段：日期 | 提示词编号 | 模型名+版本 | 输出证据（结论摘要/引用） | 判定 | 是否双评。模板见 assets/llm-review-log-template.md；`record_review.py` 缺日志文件时自动按模板初始化。

## 7. Scripts 用法

```
python scripts/detect_stage.py <skill_dir>            # 阶段产物检测 + 提示词建议（advisory；退出 0=检测完成，1=用法错误/目录不存在，供编排器区分误用）
python scripts/record_review.py --skill-dir <dir> --prompt-id W-02 \
    --model "glm-4.7" --verdict FAIL --evidence "引用摘要" --dual 是 --package A
python scripts/plan_dual_review.py --skill-dir <dir> --prompt-id W-15 \
    --inputs SKILL.md scripts/foo.py                   # 生成 .verification/dual-review/<id>-<ts>/{A,B}-task.md
python scripts/plan_dual_review.py --skill-dir <dir> --prompt-id E-06 \
    --blind out_new.md out_old.md                      # 盲评：随机匿名化两份输出
python scripts/summarize_reviews.py <skill_dir>       # 汇总判定、双评缺口、分歧项
```

## 8. Gotchas

- **detect_stage 的建议 ≠ 阶段完成**：产物存在只说明"到过该阶段"，出口判据 + 人工签认才算完成。勿据脚本建议跳过人工终审或门禁。
- **双评分歧高发于 W-02**（触发质量主观性强）：把两个会话的原始输出都贴进留痕证据列，人工裁决必须写明采纳哪份及理由。
- **盲评映射文件**（plan_dual_review 生成的 mapping.json）只在汇总还原时打开，投喂评委前勿让其接触。
- **数据安全**：评审对象全文与脚本先过 `check_skill.py` 的 secret 扫描（V8）再投喂外部 LLM；命中敏感信息即停止投喂并上报。
- **本技能自身的修改**也须走 D/W/E/M/R 验证：description 改动过 W-02 双评、结构改动过 W-04 双评、全文改动过 W-15 双评。

```

### 输入: detect_stage.py

```
#!/usr/bin/env python3
"""detect_stage.py — 检测目标技能的生命周期产物，推荐应跑的 LLM 评审提示词组。

定位：advisory（仅建议）。产物存在只说明"到过该阶段"，阶段完成以《验证 SOP》
出口判据 + 人工签认为准；本脚本输出不得作为门禁依据。

用法:
    python detect_stage.py <skill_dir>
退出码: 0=检测完成（无论检出哪些阶段，advisory 不阻断）; 1=用法错误/目录不存在。
"""
import os
import sys

RECOMMEND = {
    "D": ("D-01", "设计期：取材材料提炼辅助（d-prompts.md）"),
    "W": ("W-01~W-16", "编写期语义评审全跑；⚑ 双评：W-02/W-04/W-05/W-08/W-15（w-prompts.md）"),
    "E": ("E-01~E-10", "测试期：按实际测试项选跑；⚑ 双评：E-04/E-06（e-prompts.md）"),
    "M": ("（无）", "M 阶段产物已存在；M0 复核与 M1 审计属 H 类人工终审，无专属 L 类提示词（如需辅助可重跑 W 组）"),
    "R": ("R-01/R-02", "运行期：纠错归纳与增长性内容隔离；⚑ 双评：R-02（r-prompts.md）"),
}


def show_help() -> None:
    print(
        "detect_stage.py — 检测目标技能的生命周期产物，推荐应跑的 LLM 评审提示词组（advisory，不阻断）。\n"
        "\n"
        "用法: python detect_stage.py <skill_dir>\n"
        "标志: 无（仅一个位置参数 skill_dir）\n"
        "示例: python detect_stage.py /path/to/my-skill\n"
        "退出码: 0=检测完成（advisory 不阻断）; 1=用法错误/目录不存在。"
    )


def main() -> int:
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        show_help()
        return 0
    if len(sys.argv) != 2:
        print("错误: 缺少参数。\n用法: detect_stage.py <skill_dir>\n下一步: 传入目标技能目录后重试。", file=sys.stderr)
        return 1  # 用法错误须与"正常完成"可区分，供编排器识别
    skill_dir = os.path.abspath(sys.argv[1])
    if not os.path.isdir(skill_dir):
        print(f"错误: 目录不存在: {skill_dir}\n下一步: 确认技能目录路径后重试。", file=sys.stderr)
        return 1
    vdir = os.path.join(skill_dir, ".verification")

    def exists(*names: str) -> bool:
        return all(os.path.exists(os.path.join(vdir, n)) for n in names)

    def any_iteration() -> bool:
        return os.path.isdir(vdir) and any(
            n.startswith("iteration-") and os.path.isdir(os.path.join(vdir, n))
            for n in os.listdir(vdir)
        )

    print(f"目标技能: {skill_dir}")
    print(f".verification 目录: {'存在' if os.path.isdir(vdir) else '不存在（可能尚未立项或未留痕）'}")
    print()
    print("阶段产物检测（存在=到过该阶段，不等于阶段完成）:")
    rows = [
        ("D", "design.md + name-precheck.md", exists("design.md", "name-precheck.md")),
        ("W", "llm-review-log.md", exists("llm-review-log.md")),
        ("E", "iteration-N/ 目录", any_iteration()),
        ("M", ".iteration-baseline + acceptance-report.md",
         exists(".iteration-baseline") or exists("acceptance-report.md")),
        ("R", "run-log.md", exists("run-log.md")),
    ]
    for stage, marker, hit in rows:
        print(f"  [{'x' if hit else ' '}] {stage}  {marker}")
    print()
    print("提示词建议（仅建议，非门禁）:")
    for stage, marker, hit in rows:
        if hit:
            pid, desc = RECOMMEND[stage]
            print(f"  {stage}: {pid} — {desc}")
    if not any(hit for _, _, hit in rows):
        print("  未检测到任何阶段产物。若为全新技能，先走 D 阶段：填写设计说明后再运行本脚本。")
    print()
    print("提醒: ⚑ 提示词须双评（两个独立会话/不同模型），用 plan_dual_review.py 生成任务包。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

```

### 输入: plan_dual_review.py

```
#!/usr/bin/env python3
"""plan_dual_review.py — 生成双评/盲评任务包。

双评: 为 ⚑ 提示词生成 A/B 两份独立任务包，人工分别开两个会话投喂。
盲评: 对两份输出文件随机匿名化为"版本 A/B"，供 E-06 评委使用；
      真实来源映射写入同目录 mapping.json，投喂评委前勿让其接触。

用法:
    双评:  python plan_dual_review.py --skill-dir <dir> --prompt-id W-15 \
               --inputs SKILL.md scripts/foo.py
    盲评:  python plan_dual_review.py --skill-dir <dir> --prompt-id E-06 \
               --blind out_new.md out_old.md

退出码: 0=成功; 1=参数错误。
"""
import argparse
import datetime
import json
import os
import random
import re
import sys

DUAL_REQUIRED = {"W-02", "W-04", "W-05", "W-08", "W-15", "E-04", "E-06", "R-02"}
SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF_DIR = os.path.join(SKILL_ROOT, "references")


def extract_prompt(prompt_id: str) -> tuple[str, str]:
    """从 references/*.md 提取提示词正文，返回 (提示词文本, 来源文件名)。"""
    group = prompt_id.split("-")[0]
    ref = os.path.join(REF_DIR, {"D": "d", "W": "w", "E": "e", "R": "r"}[group] + "-prompts.md")
    if not os.path.exists(ref):
        raise FileNotFoundError(f"错误: 找不到提示词库 {ref}\n下一步: 确认技能安装完整。")
    with open(ref, encoding="utf-8") as f:
        text = f.read()
    m = re.search(
        r"^##\s+" + re.escape(prompt_id) + r"(?!\d).*?\n```text\n(.*?)```",
        text, re.S | re.M,
    )
    if not m:
        raise ValueError(f"错误: 在 {os.path.basename(ref)} 中未找到 {prompt_id} 的提示词块。\n下一步: 核对提示词编号。")
    return m.group(1).strip(), os.path.basename(ref)


def read_inputs(paths: list[str]) -> list[tuple[str, str]]:
    out = []
    for p in paths:
        if not os.path.exists(p):
            raise FileNotFoundError(f"错误: 输入文件不存在: {p}\n下一步: 确认路径后重试。")
        with open(p, encoding="utf-8", errors="replace") as f:
            out.append((os.path.basename(p), f.read()))
    return out


def write_pkg(path: str, title: str, body: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    print(f"已生成: {path}  ({title})")


def main() -> int:
    p = argparse.ArgumentParser(description="生成双评/盲评任务包")
    p.add_argument("--skill-dir", required=True, help="目标技能目录（任务包写入其 .verification/）")
    p.add_argument("--prompt-id", required=True, help="提示词编号，如 W-15 / E-06")
    p.add_argument("--inputs", nargs="*", default=[], help="待评审文件路径（内嵌进任务包）")
    p.add_argument("--blind", nargs=2, metavar=("FILE_A", "FILE_B"),
                   help="盲评模式：两份输出文件随机匿名化")
    a = p.parse_args()

    if not os.path.isdir(a.skill_dir):
        print(f"错误: 目标技能目录不存在: {a.skill_dir}\n下一步: 确认路径后重试；本脚本不代为创建目标技能目录。", file=sys.stderr)
        return 1
    if not a.blind and not a.inputs:
        print("错误: 双评模式需 --inputs，盲评模式需 --blind（二选一）。\n下一步: 补齐参数后重试。", file=sys.stderr)
        return 1
    if a.blind and os.path.realpath(a.blind[0]) == os.path.realpath(a.blind[1]):
        print(f"错误: 盲评两份输入指向同一文件: {a.blind[0]}\n下一步: 盲评需同一任务的两份不同输出，核对路径后重试。", file=sys.stderr)
        return 1
    try:
        prompt_text, source = extract_prompt(a.prompt_id)
    except (FileNotFoundError, ValueError) as e:
        print(e, file=sys.stderr)
        return 1

    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir = os.path.join(os.path.abspath(a.skill_dir), ".verification", "dual-review", f"{a.prompt_id}-{ts}")
    os.makedirs(outdir, exist_ok=True)

    if a.blind:
        files = read_inputs(a.blind)
        random.shuffle(files)
        # 标签用 "版本 A/B"：与 e-prompts.md E-06 提示词（"版本 A / 版本 B"，
        # 输出 JSON 键 "A"/"B"）逐字对齐，避免评委在两套命名间困惑。
        labels = ("A", "B")
        for (name, content), lab in zip(files, labels):
            body = (
                f"# 盲评任务包 · 版本 {lab}\n\n"
                f"来源信息禁止接触。按提示词独立评分并给证据引用。\n\n"
                f"## 提示词（{a.prompt_id}，来自 {source}）\n\n```text\n{prompt_text}\n```\n\n"
                f"## 待评输出（版本 {lab}）\n\n```\n{content}\n```\n"
            )
            write_pkg(os.path.join(outdir, f"blind-{lab}.md"), f"版本 {lab}", body)
        mapping = {f"版本 {lab}": name for (name, _), lab in zip(files, labels)}
        with open(os.path.join(outdir, "mapping.json"), "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
        print(f"已生成映射（投喂评委前勿展示）: {os.path.join(outdir, 'mapping.json')}")
    else:
        if a.prompt_id not in DUAL_REQUIRED:
            print(f"提示: {a.prompt_id} 非 ⚑ 双评范围，通常单评即可；仍按双评生成任务包。")
        materials = "\n\n".join(f"### 输入: {name}\n\n```\n{content}\n```" for name, content in read_inputs(a.inputs))
        for pkg in ("A", "B"):
            body = (
                f"# 双评任务包 {pkg}（包编号：{pkg}）· {a.prompt_id}\n\n"
                f"**本包编号: {pkg}**（留痕时 record_review.py --package {pkg}）\n\n"
                f"**独立判定声明**: 本包由独立会话独立判定，不得参考另一份包的结论；"
                f"同一会话内跑两遍不构成双评。判定不一致将升级人工裁决。\n\n"
                f"## 提示词（来自 {source}）\n\n```text\n{prompt_text}\n```\n\n"
                f"## 待评审材料\n\n{materials}\n"
            )
            write_pkg(os.path.join(outdir, f"{pkg}-task.md"), f"任务包 {pkg}", body)
    print(f"\n下一步: A/B 两包分别开两个独立会话投喂；结果用 record_review.py 分别留痕"
          f"（--package A / --package B，双评=是）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

```

### 输入: record_review.py

```
#!/usr/bin/env python3
"""record_review.py — 向 llm-review-log.md 追加一条 V12 留痕记录。

用法:
    python record_review.py --skill-dir <dir> --prompt-id W-02 \
        --model "glm-4.7" --verdict FAIL --evidence "证据摘要/引用" --dual 是 --package A
退出码: 0=成功; 1=参数错误; 2=⚑ 提示词未双评——警告级（记录已写入，需人工复核后补录）。
双评记录请分别带 --package A / --package B，写入证据列前缀以便区分两个独立会话。
"""
import argparse
import datetime
import os
import re
import sys

DUAL_REQUIRED = {"W-02", "W-04", "W-05", "W-08", "W-15", "E-04", "E-06", "R-02"}

HEADER = """# LLM 评审日志（V12 留痕）

> 双评 ⚑ 权威范围：W-02、W-04、W-05、W-08、W-15、E-04、E-06、R-02。
> 同一会话内跑两遍不构成双评，不得标"是"。

| 日期 | 提示词编号 | 模型名+版本 | 输出证据（结论摘要/引用） | 判定 | 是否双评 |
| --- | --- | --- | --- | --- | --- |
"""


def main() -> int:
    p = argparse.ArgumentParser(description="追加 LLM 评审留痕")
    p.add_argument("--skill-dir", required=True, help="目标技能目录")
    p.add_argument("--prompt-id", required=True, help="提示词编号，如 W-02 / E-04")
    p.add_argument("--model", required=True, help="模型名+版本")
    p.add_argument("--verdict", required=True, choices=["PASS", "FAIL"], help="判定")
    p.add_argument("--evidence", required=True, help="输出证据（结论摘要/引用）")
    p.add_argument("--dual", default="不适用", choices=["是", "否", "不适用"], help="是否双评")
    p.add_argument("--package", default="", choices=["", "A", "B"],
                   help="双评包编号（可选）：双评时分别以 A/B 各留一条记录")
    a = p.parse_args()

    if not all(field.strip() for field in (a.prompt_id, a.model, a.evidence)):
        print("错误: prompt-id/model/evidence 均不得为空。\n下一步: 补齐参数后重试。", file=sys.stderr)
        return 1
    if not re.fullmatch(r"[DWER]-\d{2}", a.prompt_id):
        print(f"错误: prompt-id 格式不合法: {a.prompt_id}。\n下一步: 使用两位数编号，如 D-01、W-02、E-06、R-02。", file=sys.stderr)
        return 1
    evidence = f"[包{a.package}] {a.evidence}" if a.package else a.evidence
    # markdown 表格防护：半角 | 破坏列结构（不用 \|——summarize 按裸 | 切列，
    # \| 仍会断列）；换行破坏单行记录格式。均替换后写入。
    evidence = (evidence.replace("|", "｜")
                        .replace("\r\n", " ").replace("\r", " ").replace("\n", " "))
    model = (a.model.replace("|", "｜")
                    .replace("\r\n", " ").replace("\r", " ").replace("\n", " "))

    vdir = os.path.join(os.path.abspath(a.skill_dir), ".verification")
    log_path = os.path.join(vdir, "llm-review-log.md")
    os.makedirs(vdir, exist_ok=True)
    if not os.path.exists(log_path):
        with open(log_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(HEADER)
        print(f"已按模板初始化日志: {log_path}")

    today = datetime.date.today().isoformat()
    row = f"| {today} | {a.prompt_id} | {model} | {evidence} | {a.verdict} | {a.dual} |\n"
    with open(log_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(row)
    print(f"已写入: {log_path}\n  {row.strip()}")

    if a.prompt_id in DUAL_REQUIRED and a.dual != "是":
        print(
            f"警告: {a.prompt_id} 属 ⚑ 双评范围，本次记录 dual={a.dual}。"
            "\n下一步: 用 plan_dual_review.py 生成任务包，由两个独立会话分别判定后"
            "以 --package A / --package B 各补录一条。",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

```

### 输入: summarize_reviews.py

```
#!/usr/bin/env python3
"""summarize_reviews.py — 汇总 llm-review-log.md：判定统计、双评缺口、分歧项。

用法:
    python summarize_reviews.py <skill_dir>
退出码: 0=成功; 1=日志不存在或格式无法解析。
输出仅为汇总建议，最终放行由人工裁决。
"""
import os
import re
import sys

DUAL_REQUIRED = ["W-02", "W-04", "W-05", "W-08", "W-15", "E-04", "E-06", "R-02"]
ROW_RE = re.compile(r"^\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*(PASS|FAIL)\s*\|\s*(是|否|不适用)\s*\|")


def show_help() -> None:
    print(
        "summarize_reviews.py — 汇总 llm-review-log.md：判定统计、双评缺口、分歧项。\n"
        "\n"
        "用法: python summarize_reviews.py <skill_dir>\n"
        "标志: 无（仅一个位置参数 skill_dir）\n"
        "示例: python summarize_reviews.py /path/to/my-skill\n"
        "退出码: 0=成功; 1=日志不存在或格式无法解析。输出仅为汇总建议，最终放行由人工裁决。"
    )


def main() -> int:
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        show_help()
        return 0
    if len(sys.argv) != 2:
        print("错误: 缺少参数。\n用法: summarize_reviews.py <skill_dir>\n下一步: 传入目标技能目录后重试。", file=sys.stderr)
        return 1
    log = os.path.join(os.path.abspath(sys.argv[1]), ".verification", "llm-review-log.md")
    if not os.path.exists(log):
        print(f"错误: 日志不存在: {log}\n下一步: 先用 record_review.py 留痕。", file=sys.stderr)
        return 1

    entries = []  # (prompt_id, verdict, dual, evidence, model)
    with open(log, encoding="utf-8") as f:
        for line in f:
            m = ROW_RE.match(line.strip())
            if m:
                entries.append((m.group(2).strip(), m.group(5), m.group(6),
                                m.group(4).strip(), m.group(3).strip()))
    if not entries:
        print("错误: 日志中未解析到有效记录行（列数/判定/双评字段须符合模板）。\n下一步: 检查日志表格式。", file=sys.stderr)
        return 1

    print(f"日志: {log}")
    print(f"总记录数: {len(entries)}")
    fails = [e for e in entries if e[1] == "FAIL"]
    print(f"FAIL 数: {len(fails)}")
    for pid, verdict, dual, evidence, model in fails:
        print(f"  FAIL {pid} (dual={dual}, {model}): {evidence[:80]}")

    print("\n双评缺口（⚑ 项须 ≥2 条记录且全部 dual=是，对应两个独立会话）:")
    gaps = []
    for pid in DUAL_REQUIRED:
        recs = [e for e in entries if e[0] == pid]
        if not recs:
            gaps.append(f"  缺记录: {pid}")
        elif len(recs) < 2:
            gaps.append(f"  记录不足: {pid}（双评须 ≥2 条独立会话记录，现 {len(recs)} 条；补齐第二条后才能判定是否分歧）")
        elif not all(e[2] == "是" for e in recs):
            gaps.append(f"  未双评: {pid}（存在 dual≠是 的记录: {'/'.join(sorted({e[2] for e in recs if e[2] != '是'}))}）")
    print("\n".join(gaps) if gaps else "  无")

    print("\n双评分歧（同编号判定不一致，须人工裁决）:")
    conflicts = []
    for pid in DUAL_REQUIRED:
        verdicts = {e[1] for e in entries if e[0] == pid}
        if len(verdicts) > 1:
            conflicts.append(f"  {pid}: {' vs '.join(sorted(verdicts))} → 升级人工裁决")
    print("\n".join(conflicts) if conflicts else "  无")

    print("\n提醒: 本汇总为建议输出；PASS/FAIL 最终放行由人工签认，[M] 级 FAIL 不得自动放行。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

```
