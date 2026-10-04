#!/usr/bin/env python3
"""host_compat.py — K 类在环试点的跨宿主兼容性检查入口。

用途：在任何宿主（WorkBuddy / Claude Code / Cursor / DeepSeek Harness / Qwen Code /
智谱 / 豆包 / 通用终端）上启动 K 类在环试点前，先运行本脚本做兼容性检查，
输出当前宿主能力结论与提示，决定在环试点走哪条路径：
  A. 宿主提供 agent CLI      → 可脚本化逐条新会话（全自动）
  B. 宿主内置子代理编排       → 由会话内派发子代理（半自动，WorkBuddy 当前路径）
  C. 均不可用                → 降级 runbook（人工逐条新会话投喂）

宿主识别为**启发式**：环境变量名 / 家目录约定按各宿主实际发行调整（见 HOSTS 表）；
识别失败不代表宿主不支持试点，只影响路径裁决精度，可用 --host 显式覆盖。

用法:
    python host_compat.py [--skill-dir <被试点技能目录>] [--host <宿主名>] [--json]

退出码: 0=全 PASS；1=有 FAIL；2=仅 WARN（与 check_skill.py / smoke_runner.py 一致）。
仅用标准库；不做任何写操作（--json 仅输出至 stdout）。

版本: v1.0（2026-10-03 收官回填批次首次版本化——补 VERSION 常量+报告头版本标识+
      _BlockArgParser 参数错误统一 exit 1，对齐工具族纪律）
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

VERSION = "v1.0"  # 2026-10-03 收官回填批次首次版本化（报告头标识，与 fix-log 可对照）

MIN_PY = (3, 10)

# 常见宿主 agent CLI（在环试点需要"逐条新会话跑查询"的能力载体）。
# 2026-10-02 联网核实：dsh=DeepSeek Harness 官方 CLI（npm @deepseek-ai/dsh，MIT）；
# pi=Pi Coding Agent 官方 CLI（earendil-works，pi.dev）；qwen=Qwen Code 官方 CLI；
# zcode=智谱官方 CLI（@zhipu/zcode）；glmcode=智谱社区 CLI（非官方，供探测）；
# trae=字节 TRAE；doubao=豆包 macOS 桌面会话 CLI（非编码宿主，仅列示）。
AGENT_CLIS = [
    "claude",        # Claude Code
    "codex",         # OpenAI Codex CLI
    "gemini",        # Gemini CLI
    "aider",         # aider
    "cursor-agent",  # Cursor CLI
    "qwen",          # Qwen Code（千问，已核实：~/.qwen/skills）
    "dsh",           # DeepSeek Harness（已核实：官方 CLI 名 dsh）
    "pi",            # Pi Coding Agent（已核实：earendil-works，pi.dev）
    "zcode",         # 智谱 ZCode（已核实：@zhipu/zcode，~/.zcode）
    "glmcode",       # 智谱社区 CLI（非官方）
    "trae",          # 字节 TRAE（豆包系编码代理）
    "doubao",        # 豆包桌面会话 CLI（macOS，非编码宿主）
    "zhipu",         # 智谱旧猜测名（保留以防私有别名）
]

# 宿主识别表（P-1：表驱动，替代硬编码 if 链）。命中任一 env 变量或家目录即认定。
# 2026-10-02 联网核实口径：
#   - Qwen Code：~/.qwen 已官方确认（个人技能 ~/.qwen/skills/）；
#   - DeepSeek Harness：官方 CLI=dsh 已确认；env DSH_HOME 与家目录约定未获官方文档证实（启发式保留）；
#   - 智谱：官方 CLI=ZCode，配置位于 ~/.zcode/cli/config.json → 家目录取 .zcode/.zai；
#     .zhipu/.glm 为启发式兜底；
#   - 豆包：编码代理形态为 TRAE；~/.doubao/.trae 均为启发式；
#   - 各 env 变量名均未获官方文档证实，识别失败时用 --host 显式覆盖。
HOSTS: list[dict] = [
    dict(name="Claude Code", env=["CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"], home=[]),
    dict(name="Cursor", env=["CURSOR_TRACE_ID"], home=[]),
    dict(name="DeepSeek Harness", env=["DSH_HOME", "DEEPSEEK_HARNESS"], home=[".dsh", ".deepseek"]),
    dict(name="Qwen Code", env=["QWEN_CODE"], home=[".qwen"]),
    dict(name="智谱 ZCode", env=["ZCODE"], home=[".zcode", ".zai", ".zhipu", ".glm"]),
    dict(name="豆包/TRAE", env=["TRAE", "DOUBAO"], home=[".trae", ".doubao"]),
    dict(name="WorkBuddy", env=["WORKBUDDY_SESSION"], home=[".workbuddy"]),
]


def check_python() -> tuple[str, str]:
    v = sys.version_info
    if (v.major, v.minor) >= MIN_PY:
        return "PASS", f"Python {v.major}.{v.minor}.{v.micro} >= 3.10"
    return "FAIL", f"Python {v.major}.{v.minor}.{v.micro} < 3.10，脚本族无法保证兼容"


def detect_host(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    env = os.environ
    home = Path.home()
    for h in HOSTS:
        if any(env.get(e) for e in h["env"]) or any(home.joinpath(d).is_dir() for d in h["home"]):
            return h["name"]
    if env.get("TERM_PROGRAM") == "vscode":
        return "VS Code (通用终端)"
    return "通用终端（未识别宿主）"


def host_homes(host: str) -> list[str]:
    """从 HOSTS 表查已知宿主的家目录列表；未知/自定义宿主按 .<host小写去空格> 派生。

    修复 2.1：已知宿主一律取表内 home 列表，禁止从宿主名猜测
    （"DeepSeek Harness" 会派生出 ~/.deepseekharness、"智谱 ZCode" 会派生中文路径、
    "豆包/TRAE" 会因 '/' 派生出多级目录——三者均为真实踩过的坑）。
    """
    for h in HOSTS:
        if h["name"] == host:
            return list(h["home"])
    return [f".{host.lower().replace(' ', '')}"]


def skill_dirs_for(host: str) -> list[tuple[str, Path, str]]:
    """返回 (标签, 路径, 说明)。用户级 + 项目级候选。"""
    home = Path.home()
    cwd = Path.cwd()
    cands: list[tuple[str, Path, str]] = []
    # WorkBuddy / Claude Code / Qwen Code：无条件按目录存在性探测（与宿主名判定解耦——
    # env 未识别出宿主时，只要目录真实存在仍可作为 B 路径证据；修复第四轮 2.1）
    if home.joinpath(".workbuddy", "skills").is_dir():
        cands.append(("WorkBuddy 用户级", home / ".workbuddy" / "skills", "本宿主技能库"))
        cands.append(("WorkBuddy 项目级", cwd / ".workbuddy" / "skills", "工作区技能库（可选）"))
    if home.joinpath(".claude", "skills").is_dir():
        cands.append(("Claude Code 用户级", home / ".claude" / "skills", "本宿主技能库"))
        cands.append(("Claude Code 项目级", cwd / ".claude" / "skills", "项目技能库（可选）"))
    # Cursor（评审第六轮 2.1）：env 识别 + 显式探测，与 WorkBuddy/Claude Code 对称。
    # 注意：HOSTS 表中 Cursor 的 home 特意保持空——~/.cursor 兼作 Cursor 编辑器配置目录，
    # 若入表会让装过编辑器的机器被 detect_host 误判为 Cursor（表遍历中 Cursor 先于 WorkBuddy）。
    if host == "Cursor" or home.joinpath(".cursor", "skills").is_dir():
        cands.append(("Cursor 用户级", home / ".cursor" / "skills",
                      "推测路径（编辑器配置目录 ≠ 必有技能库）；请人工确认该宿主实际技能库路径"))
        cands.append(("Cursor 项目级", cwd / ".cursor" / "skills", "项目技能库（可选）"))
    # 2026-10-02 联网核实：Qwen Code 官方确认 ~/.qwen/skills/（个人）/ .qwen/skills/（项目）
    # 此分支与 WorkBuddy/Claude 的"目录存在才探测"不对称是有意的（评审第六轮 2.3）：
    # 用户显式 --host Qwen Code 时，即使目录不存在也应报告官方预期路径（check_skill_dirs 报 WARN），
    # 请勿"修复"成对称。
    if host == "Qwen Code" or home.joinpath(".qwen", "skills").is_dir():
        cands.append(("Qwen Code 用户级", home / ".qwen" / "skills", "已官方核实（qwen-code-docs）"))
        cands.append(("Qwen Code 项目级", cwd / ".qwen" / "skills", "项目技能库（可选）"))
    # 第四轮 2.2：推测分支触发条件从硬编码名单改为查 HOSTS 表——
    # 已知宿主且表内声明了非空 home → 按表探测；未知宿主（非通用/VS Code）且尚无候选 → 按名字兜底。
    # 新增宿主只需改 HOSTS 表一处，不再需要同步本函数。
    host_entry = next((h for h in HOSTS if h["name"] == host), None)
    if (host_entry and host_entry["home"]) or (
        host_entry is None
        and host not in ("通用终端（未识别宿主）", "VS Code (通用终端)")
        and not cands
    ):
        for d in host_homes(host):
            cands.append((f"{host} 技能库（推测）", home / d / "skills",
                          "启发式探测；请人工确认该宿主实际技能库路径并回填 skill_dirs_for()"))
    # VS Code 仅是终端载体，无专属技能库，明确注明而非误报
    if host == "VS Code (通用终端)" and not cands:
        cands.append(("VS Code", cwd / "skills", "VS Code 无专属技能库；其内运行的编码 CLI 按各自宿主规则探测"))
    if not cands:
        cands.append(("通用", cwd / "skills", "未识别宿主，仅探测 ./skills（可手动指定）"))
    # 第四轮 2.2 配套：按路径去重并保持首次出现顺序（表内 home 与上方专用分支重叠时不重复报）
    # 评审第六轮 2.5：去重键用 normcase 而非 lower()——Linux 上 .lower() 会把
    # ~/Skills 与 ~/skills 两个不同目录误合成一条；normcase 按平台语义处理
    seen: set[str] = set()
    uniq: list[tuple[str, Path, str]] = []
    for label, p, note in cands:
        k = os.path.normcase(str(p))
        if k not in seen:
            seen.add(k)
            uniq.append((label, p, note))
    return uniq


def check_skill_dirs(host: str) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for label, p, note in skill_dirs_for(host):
        if p.is_dir():
            # P-3：仅扫一层（glob("*/SKILL.md")）——主流技能库为扁平结构；嵌套库请人工核对
            n = len(list(p.glob("*/SKILL.md")))
            out.append(("PASS", f"{label}: {p}（发现 {n} 个技能，仅扫一层）", note))
        else:
            out.append(("WARN", f"{label}: {p} 不存在", note + "；若该宿主不是交付目标可忽略"))
    return out


def check_agent_clis() -> tuple[str, str, list[str]]:
    # 第四轮 2.3：按解析后的真实路径去重——同一可执行文件的多个别名（如 zhipu 是 zcode 的软链）
    # 只报一次；AGENT_CLIS 本身无重名，按名字 set() 去重无效，必须 resolve
    found: list[str] = []
    seen: set[str] = set()
    for c in AGENT_CLIS:
        w = shutil.which(c)
        if not w:
            continue
        try:
            key = os.path.normcase(str(Path(w).resolve()))  # 第五轮 2.5：Windows 大小写不敏感去重
        except OSError:
            key = w
        if key not in seen:
            seen.add(key)
            found.append(c)
    if found:
        return "PASS", f"发现 agent CLI: {', '.join(found)}（路径 A：可脚本化逐条新会话）", found
    return (
        "WARN",
        "PATH 上未发现已知 agent CLI（" + "/".join(AGENT_CLIS) + "）",
        [],
    )


def frontmatter_block(text: str) -> str:
    """S-3 加固：显式提取第一个 '---' 行到下一个 '---' 行之间的块（非通用 YAML 解析）。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i])
    return ""


def frontmatter_keys(fm: str) -> set[str]:
    """2.3：逐行提取顶层键名（只看行首 `key:`，忽略注释），避免 'myname:' 误报为 'name:'。"""
    keys: set[str] = set()
    for ln in fm.splitlines():
        s = ln.strip()
        if not s or s.startswith("#") or ":" not in s:
            continue
        if ln != ln.lstrip():  # 缩进行视为嵌套键，非顶层
            continue
        keys.add(s.split(":", 1)[0].strip())
    return keys


def check_skill_dir_arg(skill_dir: str | None) -> tuple[str, str]:
    if not skill_dir:
        return ("WARN", "未提供 --skill-dir，跳过被试点技能体检")
    d = Path(skill_dir)
    if not d.is_dir():
        return ("FAIL", f"--skill-dir 不存在: {d}")
    sm = d / "SKILL.md"
    if not sm.is_file():
        return ("FAIL", f"{d} 缺少 SKILL.md")
    try:
        # utf-8-sig：自动剥离 UTF-8 BOM（评审第六轮 2.2——BOM 开头会被误判为无 frontmatter）
        text = sm.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as e:  # 评审第六轮 2.4：文件不可读（权限/占用）不崩溃，保留已收集结果
        return ("FAIL", f"{sm} 读取失败: {e}；请检查文件权限")
    # 第五轮 2.6：三分报错——无 frontmatter / frontmatter 为空 / 缺 name/description
    if not text.lstrip().startswith("---"):
        return ("FAIL", f"{sm} 无 YAML frontmatter（文件不以 --- 开头）；请以 check_skill.py 复核")
    fm = frontmatter_block(text)
    if not fm.strip():
        return ("FAIL", f"{sm} frontmatter 块为空（或 --- 未闭合）；请以 check_skill.py 复核")
    # 启发式判定：只认 frontmatter 顶层键集合含 name 与 description（逐行键判定，
    # 排除 myname:/filename: 子串误报），不替代 check_skill.py 的精确校验
    keys = frontmatter_keys(fm)
    if not {"name", "description"} <= keys:
        return ("FAIL", f"{sm} frontmatter 缺 name/description（启发式检测；请以 check_skill.py 复核）")
    return ("PASS", f"被试点技能就绪: {d}")


class _BlockArgParser(argparse.ArgumentParser):
    """参数错误统一 exit 1（阻断码）——argparse 默认 exit 2 撞 WARN 码
    （族纪律：naming_precheck v1.0.1 评审 5 先例；v1.0 收官回填批次补齐）。"""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        print(f"错误: {message}。下一步: 按用法核对参数后重试。", file=sys.stderr)
        raise SystemExit(1)


def main() -> int:
    ap = _BlockArgParser(description="K 类在环试点跨宿主兼容性检查入口")
    ap.add_argument("--skill-dir", help="被试点技能目录（可选，做基础体检）")
    ap.add_argument("--host", help="显式指定宿主名，仅影响路径裁决与技能库目录探测，不改变实际宿主能力；"
                                    "传入任意字符串也会触发 B 路径——请确认该宿主确实支持会话内子代理编排，"
                                    "否则应改用 agent CLI（路径 A）或降级 runbook（路径 C）")  # 第四轮 2.5：语义补全
    ap.add_argument("--json", dest="as_json", action="store_true", help="以 JSON 输出结论")
    a = ap.parse_args()

    # 2.1：统一三元组类型（note 可为空串），消除 results 标注与 check_skill_dirs 返回不一致
    results: list[tuple[str, str, str]] = []

    def add(level: str, msg: str, note: str = "") -> None:
        results.append((level, msg, note))

    add(*check_python())
    host = detect_host(a.host)
    add("PASS" if host != "通用终端（未识别宿主）" else "WARN", f"宿主识别: {host}")
    results.extend(check_skill_dirs(host))
    cli_level, cli_msg, _ = check_agent_clis()
    add(cli_level, cli_msg)
    add(*check_skill_dir_arg(a.skill_dir))

    # 第四轮 2.1：单一真源——B 路径判定直接复用 skill_dirs_for 的探测结果，
    # 不再从 HOSTS 表独立推导（Claude Code/Cursor 表内 home 为空会漏检 ~/.claude/skills，
    # 导致 env 未识别时 Claude Code 用户被误降级 C 路径）
    any_skill_dir = any(p.is_dir() for _, p, _ in skill_dirs_for(host))
    in_host_session = host != "通用终端（未识别宿主）" or any_skill_dir
    if cli_level == "PASS":
        path, advice = "A（全自动）", "用发现的 agent CLI 以子进程逐条新会话跑查询；run_trigger 编排可直接脚本化。"
    elif in_host_session:
        if host == "通用终端（未识别宿主）":
            # 第五轮 2.2：B 判定的唯一依据是磁盘上的宿主技能库，但它可能是历史安装残留——
            # 该场景与"真在宿主会话内"（第四轮 2.1：env 缺失但确在 Claude Code 内）从脚本视角
            # 完全不可区分，任何确定性规则都会牺牲其一；故保留 B 判定、advice 显式给出改走 C 的条件
            path, advice = "B（半自动，待确认）", (
                "检测到磁盘上存在宿主技能库，但未能识别当前宿主——该证据可能是历史安装残留。"
                "若你当前确实处于支持子代理编排的宿主会话内 → 按 B 执行（会话内派发子代理，每个子代理=独立新会话）；"
                "若仅是普通终端（技能库只是残留）→ 请改走 C（降级 runbook），不要尝试在无宿主环境下派发子代理。")
        else:
            path, advice = "B（半自动）", f"当前运行于 {host} 会话内（或检测到宿主技能库）：由会话内编排派发子代理（每个子代理=独立新会话）执行逐条查询；纯 shell 无法自动化。"
    else:
        path, advice = "C（降级 runbook）", "无 agent CLI 且非宿主会话：按操作手册 §5.1 先例降级为 runbook，人工逐条新开会话投喂查询并记录。"

    has_fail = any(r[0] == "FAIL" for r in results)
    has_warn = any(r[0] == "WARN" for r in results)
    verdict = "FAIL" if has_fail else ("WARN" if has_warn else "PASS")

    if a.as_json:
        print(json.dumps({
            "schema_version": "1.0",  # 2.8：供其他脚本消费时的结构化兼容标记
            "host": host, "pilot_path": path, "verdict": verdict,
            "checks": [{"level": l, "detail": m, "note": n} for l, m, n in results],  # 2.2：note 不再丢弃
            "advice": advice,
        }, ensure_ascii=False, indent=2))
    else:
        print(f"# host_compat 兼容性检查报告（{VERSION}）")
        print(f"宿主: {host}")
        print()
        # 第五轮 2.1：文本输出同步显示 note（此前只给 --json 补了 note，文本路径漏同步）
        for l, m, n in results:
            print(f"  [{l}] {m}" + (f"  ← {n}" if n else ""))
        print()
        print(f"在环试点路径: {path}")
        print(f"提示: {advice}")
        print(f"总结论: {verdict}")
        print("用法: python host_compat.py [--skill-dir <被试点技能目录>] [--host <宿主名>] [--json]；"
              "退出码: 0=全 PASS, 1=有 FAIL, 2=仅 WARN")

    return 1 if has_fail else (2 if has_warn else 0)


if __name__ == "__main__":
    sys.exit(main())
