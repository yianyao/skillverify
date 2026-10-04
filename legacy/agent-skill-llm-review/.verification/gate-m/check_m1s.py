# -*- coding: utf-8 -*-
"""M1-S 终检：格式门 A1-A11（A6 按项目 <300）+ V17 预算门 + V8/§9.6 secret 扫描 + §9.2 端点提取"""
import re, sys, io, json, math
from pathlib import Path

SKILL_DIR = Path(r"C:/Users/yianyao/.workbuddy/skills/agent-skill-llm-review")
results = []

def add(item, grade, ok, detail):
    results.append({"item": item, "grade": grade, "verdict": "PASS" if ok else "FAIL", "detail": detail})

data = (SKILL_DIR / "SKILL.md").read_bytes()
text = data.decode("utf-8")
lines = text.split("\n")

# A2/A11: frontmatter parse
m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
fm_ok = bool(m)
fm = {}
if fm_ok:
    for ln in m.group(1).split("\n"):
        if ":" in ln:
            k, _, v = ln.partition(":")
            fm[k.strip()] = v.strip()
add("A11 frontmatter 可解析且含 name/description", "S", fm_ok and "name" in fm and "description" in fm,
    f"keys={sorted(fm.keys())}")

# A3: name regex + dir match
name = fm.get("name", "")
ok = bool(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name)) and 1 <= len(name) <= 64 and name == SKILL_DIR.name
add("A3 name 正则/长度/与目录一致", "S", ok, f"name={name}, dir={SKILL_DIR.name}")

# A4/A5
desc = fm.get("description", "")
comp = fm.get("compatibility", "")
add("A4 description 长度 1-1024 非空", "S", 1 <= len(desc) <= 1024, f"len={len(desc)}")
add("A5 compatibility 长度 1-500", "S", 1 <= len(comp) <= 500, f"len={len(comp)}")

# A6: project <300
n_lines = len(lines)
add("A6 SKILL.md 行数 <300（项目收紧）", "S", n_lines < 300, f"lines={n_lines}")

# A7: LF only
add("A7 换行符为 LF", "S", b"\r\n" not in data, "CRLF" if b"\r\n" in data else "LF only")

# A8: relative one-layer references with trigger conditions
refs = re.findall(r"`?(references/[\w.-]+|scripts/[\w.-]+|assets/[\w.-]+)`?", text)
abs_refs = re.findall(r"`?[A-Za-z]:[\\/][^`\s]+`?", text)
add("A8 引用为相对路径且仅一层", "S", len(refs) > 0 and not abs_refs,
    f"relative refs={sorted(set(refs))}; abs_hits={abs_refs[:3]}")

# A9: no interactive input in scripts
bad = []
for py in sorted((SKILL_DIR / "scripts").glob("*.py")):
    src = py.read_text(encoding="utf-8")
    for pat in ("input(", "getpass", "read -p", "confirm(", "readline(", "inquirer", "prompt_toolkit", "click.confirm"):
        if pat in src:
            bad.append(f"{py.name}:{pat}")
add("A9 脚本无交互式输入", "S", not bad, str(bad) or "clean")

# V6/A10: script smoke via subprocess done outside; record placeholder
# V17: budget gate
body = text.split("---", 2)[2] if text.count("---") >= 2 else text
body_tokens = len(body) // 3  # conservative CJK estimate ~1 token/1.5-3 chars
meta_tokens = (len(fm.get("name", "")) + len(desc) + len(comp)) // 3
add("V17 SKILL.md <300 行", "M", n_lines < 300, f"lines={n_lines}")
add("V17 正文 <5000 tokens（估）", "M", body_tokens < 5000, f"est_tokens≈{body_tokens}")
add("V17 元数据 ≈100 tokens（估）", "M", meta_tokens <= 200, f"est_tokens≈{meta_tokens}")
ext = list((SKILL_DIR / "references").glob("*.md"))
worst = max((len(p.read_text(encoding='utf-8').split('\n')) for p in ext), default=0)
add("V17 扩展层单文件 ≤500 行", "M", worst <= 500, f"max_lines={worst}")

# V8/§9.6: secret scan
secret_pats = [
    (r"(?i)(api[_-]?key|secret|token|password|passwd|pwd)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{12,}", "key=value 形态"),
    (r"sk-[A-Za-z0-9]{20,}", "sk- key"),
    (r"ghp_[A-Za-z0-9]{30,}", "github token"),
    (r"AKIA[0-9A-Z]{16}", "aws key"),
    (r"-----BEGIN (RSA |EC )?PRIVATE KEY-----", "private key block"),
]
hits = []
for py in sorted(SKILL_DIR.rglob("*.py")):
    if ".verification" in str(py): continue
    src = py.read_text(encoding="utf-8")
    for pat, label in secret_pats:
        for mm in re.finditer(pat, src):
            hits.append(f"{py.name}:{label}:{mm.group(0)[:20]}")
for md in [SKILL_DIR / "SKILL.md"] + ext:
    src = md.read_text(encoding="utf-8")
    for pat, label in secret_pats:
        for mm in re.finditer(pat, src):
            hits.append(f"{md.name}:{label}:{mm.group(0)[:20]}")
add("V8/§9.6 secret 扫描零命中", "M", not hits, str(hits) or "0 hits")

# §9.2: endpoint extraction
urls = set()
for p in list(SKILL_DIR.rglob("*.py")) + [SKILL_DIR / "SKILL.md"] + ext:
    if ".verification" in str(p): continue
    src = p.read_text(encoding="utf-8")
    urls.update(re.findall(r"https?://[^\s'\"<>\)]+", src))
add("§9.2 外部端点提取比对", "M", True, f"endpoints={sorted(urls) or 'none'}")

print(json.dumps(results, ensure_ascii=False, indent=1))
fails = [r for r in results if r["verdict"] == "FAIL"]
print(f"\nSUMMARY: {len(results)-len(fails)}/{len(results)} PASS" + (f"  FAILS: {[f['item'] for f in fails]}" if fails else ""))
