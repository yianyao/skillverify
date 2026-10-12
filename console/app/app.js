/* skillverify 操作台 · 壳逻辑（静态模式）
 *
 * 数据来源：<script type="application/json" id="nodes-data">（构建时内联，file:// 可用）。
 * 零网络请求：无 fetch、无外部资源。桥模式（M3）接入后另经 /health 探测增强。
 *
 * 校验引擎与执行桥同源：规则只读 nodes.json 的 compose_rules，本文件不硬编码任何
 * skillverify 业务规则（设计文档 §6）。
 */
"use strict";

/* ---------------------------------------------------------------- 数据与状态 */

function loadNodes() {
  const el = document.getElementById("nodes-data");
  if (!el) throw new Error("缺少 nodes-data 数据块（应由 build.py 内联）");
  const text = el.textContent.trim();
  if (!text || text === "null") {
    throw new Error("nodes.json 未内联：请先运行 python console/build.py");
  }
  return JSON.parse(text);
}

let DATA = loadNodes();

/* 桥模式（M3）：页面加载后探测 127.0.0.1:8742（serve_bridge.py 默认端口）。
 * 探到桥 → /catalog 实况数据替换内联快照 + 点亮执行按钮；探不到 → 保持静态模式。 */
const BRIDGE_URL = "http://127.0.0.1:8742";

const state = {
  domain: DATA.domains.length ? DATA.domains[0].id : null,
  selectedNode: null,
  selectedStep: null, // "pipelineId#步序"：按步骤实例高亮（同节点可在多条步骤出现，如 evals 主线第 2/3 步都是 evals 命令）
  values: {},      // nodeId -> paramId -> string | boolean
  confirmed: new Set(), // "nodeId|paramId" 已显式确认的 confirm 规则
  chosenVariant: {},    // slotKey -> nodeId
  focusParam: null,
  bridge: false,        // 桥模式（/health 探测成功后置 true）
};

/* ---------------------------------------------------------------- 工具 */

function $(sel) { return document.querySelector(sel); }

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v);
    }
  }
  for (const c of children) {
    if (c == null) continue;
    node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return node;
}

function paramValue(nodeId, p) {
  const vals = state.values[nodeId] || {};
  if (p.form.widget === "flag") {
    if (p.id in vals) return vals[p.id] === true;  // 用户动过：以用户为准
    return p.default === true;                     // 未动过：跟随 CLI 默认
  }
  const v = vals[p.id];
  if (typeof v === "string" && v.trim() !== "") return v.trim();
  // 未动过 = 预填 CLI 默认值（命令里显式带上，产物可审计、跨机器可复现）；
  // v === ""（用户主动清空）= 明确不传该参数，交还给 CLI 默认
  if (v == null && p.default != null && p.default !== false) return p.default;
  return null;
}

function setParamValue(nodeId, p, value) {
  if (!state.values[nodeId]) state.values[nodeId] = {};
  state.values[nodeId][p.id] = value;
}

/* ---------------------------------------------------------------- 校验引擎 */

/** 计算一个节点的全部校验问题。errors 阻断复制；warns 可继续（confirm/suggest）。 */
function computeIssues(node) {
  const errors = [];
  const warns = [];
  if (node.node_type !== "cli") return { errors, warns };

  const byId = Object.fromEntries(node.params.map(p => [p.id, p]));
  const val = (id) => {
    const p = byId[id];
    return p ? paramValue(node.id, p) : null;
  };

  // 1. 逐参数：required / 类型 / 范围
  for (const p of node.params) {
    const v = paramValue(node.id, p);
    const label = p.flag || "<" + p.id + ">";
    if (p.form.required && !v) {
      errors.push({ param: p.id, text: `${label} 为必填项` });
      continue;
    }
    if (!v) continue;
    const t = p.type || {};
    if (p.form.widget === "number") {
      const n = Number(v);
      if (!Number.isFinite(n)) {
        errors.push({ param: p.id, text: `${label} 须为数值` });
      } else if (t.min != null && n < t.min || t.max != null && n > t.max) {
        const span = t.min != null && t.max != null ? `${t.min}..${t.max}`
          : t.min != null ? `≥ ${t.min}` : `≤ ${t.max}`;
        errors.push({ param: p.id, text: `${label} 超出允许范围 ${span}` });
      }
    }
    if (p.form.widget === "choice" && t.kind === "choice" && t.choices &&
        !t.choices.includes(v)) {
      errors.push({ param: p.id, text: `${label} 取值须为：${t.choices.join(" / ")}` });
    }
    // path 存在性校验：纯静态模式跳过（设计文档 §5，桥模式才做）
  }

  // 2. compose_rules（与执行桥同源，设计文档 §6）
  for (const rule of node.compose_rules || []) {
    if (rule.rule === "requires") {
      const whenOk = !rule.when || val(rule.when) != null;
      if (whenOk && val(rule.require) == null) {
        errors.push({ param: rule.require, rule, text: rule.message });
      }
    } else if (rule.rule === "excludes") {
      const set = (rule.params || []).filter(id => val(id) != null);
      if (set.length > 1) {
        errors.push({ param: set[0], rule, text: rule.message });
      }
    } else if (rule.rule === "confirm") {
      // flag 参数只有显式勾选才算「启用」（false != null 恒真，未勾选不应弹确认）
      const target = byId[rule.param];
      const active = target && target.form.widget === "flag"
        ? val(rule.param) === true
        : val(rule.param) != null;
      if (active && !state.confirmed.has(node.id + "|" + rule.param)) {
        warns.push({ param: rule.param, rule, confirmKey: node.id + "|" + rule.param,
                     text: rule.message });
      }
    } else if (rule.rule === "suggest") {
      const v = val(rule.param);
      if (v && rule.values && rule.values.some(x => v.split(/[,\s]+/).includes(x))) {
        warns.push({ param: rule.param, rule, text: rule.message });
      }
    }
  }
  return { errors, warns };
}

/* ---------------------------------------------------------------- 命令预览 */

/** 组装 argv token 列表：[{text, cls, paramId}]；未填值以占位显示。 */
function buildTokens(node) {
  const toks = [];
  if (node.node_type !== "cli") return toks;
  for (const t of node.cli.argv) toks.push({ text: t, cls: "tok-fixed", paramId: null });

  for (const p of node.params) {
    const v = paramValue(node.id, p);
    if (p.flag == null) {
      // 位置参数
      if (v) {
        const parts = p.nargs === "*" ? v.split(/\s+/) : [v];
        for (const piece of parts) {
          toks.push({ text: piece, cls: "tok-value", paramId: p.id });
        }
      } else if (p.form.required) {
        toks.push({ text: `<${p.id}>`, cls: "tok-empty", paramId: p.id });
      }
      continue;
    }
    if (p.form.widget === "flag") {
      if (v === true) toks.push({ text: p.flag, cls: "tok-flag", paramId: p.id });
      continue;
    }
    if (v == null) {
      if (p.form.required) {
        toks.push({ text: p.flag, cls: "tok-flag", paramId: p.id });
        toks.push({ text: `<?`, cls: "tok-empty", paramId: p.id });
      }
      continue;
    }
    if (p.form.widget === "multi-choice") {
      for (const item of v.split(/[,\s]+/).filter(Boolean)) {
        toks.push({ text: p.flag, cls: "tok-flag", paramId: p.id });
        toks.push({ text: item, cls: "tok-value", paramId: p.id });
      }
      continue;
    }
    toks.push({ text: p.flag, cls: "tok-flag", paramId: p.id });
    toks.push({ text: v, cls: "tok-value", paramId: p.id });
  }
  return toks;
}

function renderCommand(node) {
  const box = $("#cmd-preview");
  const copyBtn = $("#cmd-copy");
  const errBox = $("#cmd-errors");
  box.textContent = "";
  errBox.textContent = "";

  if (!node || node.node_type !== "cli") {
    box.appendChild(el("span", { class: "tok-empty",
      text: node ? "manual 节点无命令——按右侧行动卡逐步操作" : "点击左侧节点开始组装命令" }));
    copyBtn.disabled = true;
    return;
  }

  const issues = computeIssues(node);
  for (const e of issues.errors) {
    errBox.appendChild(el("span", { class: "msg error", text: "✕ " + e.text }));
  }
  for (const w of issues.warns) {
    const msg = el("span", { class: "msg warn", text: "⚑ " + w.text });
    if (w.confirmKey) {
      msg.appendChild(el("button", {
        class: "msg-confirm-btn", type: "button", text: "我知道，确认",
        onclick: () => { state.confirmed.add(w.confirmKey); renderAll(); },
      }));
    }
    errBox.appendChild(msg);
  }

  for (const tok of buildTokens(node)) {
    const cls = tok.cls + (tok.paramId && tok.paramId === state.focusParam ? " tok-focus" : "");
    box.appendChild(el("span", { class: cls, text: tok.text }));
    box.appendChild(document.createTextNode(" "));
  }
  copyBtn.disabled = issues.errors.length > 0;
  // 桥模式下执行按钮与复制同一阻断条件（桥端还会二次校验，不信任页面）
  const runBtn = $("#cmd-run");
  if (runBtn && !runBtn.hidden) runBtn.disabled = issues.errors.length > 0;
}

async function copyCommand() {
  const node = DATA.nodes[state.selectedNode];
  if (!node || node.node_type !== "cli") return;
  const issues = computeIssues(node);
  if (issues.errors.length) return;
  const line = buildTokens(node).map(t => t.text).join(" ");
  let ok = false;
  try {
    await navigator.clipboard.writeText(line);
    ok = true;
  } catch (_) {
    // file:// 下 clipboard API 可能被禁：降级 execCommand
    const ta = document.createElement("textarea");
    ta.value = line;
    document.body.appendChild(ta);
    ta.select();
    try { ok = document.execCommand("copy"); } catch (_) { ok = false; }
    ta.remove();
  }
  toast(ok ? "命令已复制" : "复制失败，请手动选中命令文本");
}

let toastTimer = null;
function toast(text) {
  const t = $("#toast");
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 1800);
}

/* ---------------------------------------------------------------- 套餐一键预填 */

function renderPresets(pipelines) {
  const bar = $("#preset-bar");
  bar.textContent = "";
  for (const pl of pipelines) {
    for (const ps of pl.presets || []) {
      bar.appendChild(el("button", {
        class: "preset-btn", type: "button",
        title: ps.description || "",
        text: "⚡ " + ps.title,
        onclick: () => applyPreset(ps),
      }));
    }
  }
}

/** 套餐 = 跨节点参数预填 + 变体槽选择；路径类参数仍由使用者自填。 */
function applyPreset(ps) {
  for (const [nid, vals] of Object.entries(ps.values || {})) {
    const node = DATA.nodes[nid];
    if (!node || node.node_type !== "cli") continue;
    for (const [pid, v] of Object.entries(vals)) {
      const p = node.params.find(x => x.id === pid);
      if (!p) continue;
      setParamValue(nid, p, p.form.widget === "flag" ? (v === true) : String(v));
    }
  }
  for (const [slot, vid] of Object.entries(ps.variants || {})) {
    state.chosenVariant[slot] = vid;
  }
  const first = Object.keys(ps.values || {}).find(nid => DATA.nodes[nid]);
  if (first) {
    selectNode(first);
  } else {
    renderCanvas();
    renderInspector();
  }
  toast("已应用套餐：" + ps.title);
}

/* ---------------------------------------------------------------- 画布渲染 */

function nodeBadge(node) {
  const badges = [];
  if (node.node_type === "manual") badges.push(el("span", { class: "badge manual-badge", text: "行动卡" }));
  if (node.condition) badges.push(el("span", { class: "badge condition", text: "条件", title: node.condition }));
  return badges;
}

function nodeCard(nodeId, extraClass, onSelect, descOverride) {
  const node = DATA.nodes[nodeId];
  if (!node) return el("div", { class: "placeholder-empty", text: "未知节点 " + nodeId });
  // 步骤卡可带差异化文案（step.card）：同一节点在流程线里多段使用时
  // （如 evals 主线：方式 A 纯校验 vs --run-with 委托执行），光看节点摘要分不出哪步是哪步
  const summary = node.summary || "";
  const desc = descOverride ||
    (summary ? summary.slice(0, 46) + (summary.length > 46 ? "…" : "") : "");
  const card = el("button", {
    class: "node-card " + (extraClass || "") + (state.selectedNode === nodeId ? " selected" : ""),
    type: "button",
    // 左栏宽度有限：截断摘要的完整全文挂 title，悬停即可读
    title: (descOverride ? descOverride + "\n——\n" : "") + (summary || node.title),
    onclick: onSelect || (() => selectNode(nodeId)),
  });
  card.appendChild(el("span", { class: "node-id", text: node.title }));
  for (const b of nodeBadge(node)) card.appendChild(b);
  if (desc) card.appendChild(el("span", { class: "node-desc", text: desc }));
  return card;
}

function renderCanvas() {
  const pipelines = DATA.pipelines.filter(p => p.domain === state.domain);
  const wrap = $("#pipelines");
  const note = $("#canvas-note");
  wrap.textContent = "";
  // 执行流当前步（M2-07）：高亮按「步骤实例」（pipelineId#步序）判定——
  // 同一节点可在同一条流程线出现多次（如评测主线第 2/3 步都是 evals 命令），
  // 按节点 id 匹配会让多步齐亮（M4 验收发现的缺陷）。
  // 回退：选中未带步骤上下文（如行动卡跳转）时，只标第一条匹配步。
  const stepMatch = (step) => (step.node && state.selectedNode === step.node) ||
    (step.slot && (step.variants || []).includes(state.selectedNode));
  const isCurrentStep = (pl, i) => {
    if (state.selectedStep) return state.selectedStep === pl.id + "#" + i;
    return stepMatch(pl.steps[i]) && pl.steps.findIndex(stepMatch) === i;
  };

  const chainSteps = (chain, pl) => {
    pl.steps.forEach((step, i) => {
      if (i > 0) chain.appendChild(el("li", { class: "step", }, el("div", { class: "step-connector" })));
      const cur = isCurrentStep(pl, i);
      const stepKey = pl.id + "#" + i;
      if (step.node) {
        const li = el("li", { class: "step" + (cur ? " current" : "") });
        li.appendChild(el("span", { class: "step-index", text: cur ? "▶ " + (i + 1) : String(i + 1) }));
        li.appendChild(nodeCard(step.node, null, () => selectNode(step.node, stepKey), step.card));
        if (step.condition) {
          li.appendChild(el("div", {
            class: "param-hint ref",
            text: "条件：" + step.condition,
            style: "margin:2px 0 0 10px",
          }));
        }
        if (step.note) {
          li.appendChild(el("div", {
            class: "param-hint ref",
            text: step.note,
            style: "margin:2px 0 0 10px",
          }));
        }
        chain.appendChild(li);
      } else if (step.slot) {
        const li = el("li", { class: "step" + (cur ? " current" : "") });
        li.appendChild(el("span", { class: "step-index", text: cur ? "▶ " + (i + 1) : String(i + 1) }));
        const group = el("div", { class: "variant-group" });
        group.appendChild(el("div", { class: "variant-group-label",
          text: "◆ " + step.slot + (step.note ? " — " + step.note : "") }));
        for (const vid of step.variants || []) {
          const chosen = state.chosenVariant[step.slot] === vid;
          const card = nodeCard(vid, chosen ? "chosen" : "", () => {
            state.chosenVariant[step.slot] = vid;
            selectNode(vid, stepKey);
          });
          group.appendChild(card);
        }
        li.appendChild(group);
        chain.appendChild(li);
      } else if (step.label) {
        // 纯说明步骤（无命令节点）：如评测主线的「步骤 1 准备评测资产」（人工编写，无 CLI 可组装）
        const li = el("li", { class: "step" });
        li.appendChild(el("span", { class: "step-index", text: String(i + 1) }));
        li.appendChild(el("div", { class: "prep-card", title: step.note || step.label,
          text: step.label }));
        if (step.note) {
          li.appendChild(el("div", {
            class: "param-hint ref",
            text: step.note,
            style: "margin:2px 0 0 10px",
          }));
        }
        chain.appendChild(li);
      }
    });
  };

  for (const pl of pipelines) {
    const block = el("div", { class: "pipeline-block" });
    const curIdx = pl.steps.findIndex((_, i) => isCurrentStep(pl, i));
    block.appendChild(el("div", {
      class: "pipeline-title" + (curIdx >= 0 ? " current" : ""),
      text: pl.title + (curIdx >= 0
        ? `　·　▶ 当前第 ${curIdx + 1} 步 / 共 ${pl.steps.length} 步` : "") }));
    const chain = el("ol", { class: "pipeline-chain" });
    chainSteps(chain, pl);
    // 实况新增节点（桥模式 /catalog）：机械层已就绪、语义层待补（设计文档 §9.4）
    const newOnes = Object.values(DATA.nodes).filter(n => n.manual_missing);
    if (newOnes.length && pl === pipelines[0]) {
      const label = el("li", { class: "step" }, el("div", {
        class: "new-nodes-label",
        text: "◆ 新增节点（实况参数面已就绪，语义层补 manual 后自动入域）" }));
      chain.appendChild(label);
      for (const n of newOnes) {
        const card = nodeCard(n.id);
        card.appendChild(el("span", { class: "badge missing-badge", text: "语义层待补" }));
        chain.appendChild(el("li", { class: "step" }, card));
      }
    }
    block.appendChild(chain);
    wrap.appendChild(block);
  }

  renderPresets(pipelines);

  // hosts.toml 档位面板（M4-03，只读）：静态模式 = 构建时捕获，桥模式 = 实时捕获
  const oldHp = document.getElementById("hosts-panel");
  if (oldHp) oldHp.remove();
  const hp = DATA.hosts_panel;
  if (hp && hp.text && state.domain === "ops") {
    const panel = el("div", { class: "hosts-panel", id: "hosts-panel" });
    panel.appendChild(el("div", {
      class: "hosts-title",
      text: "hosts.toml 有效档位（" + (hp.source || "discover --show-config") + "）——与 discover 输出一致，只读" }));
    panel.appendChild(el("pre", { class: "hosts-pre", text: hp.text }));
    wrap.appendChild(panel);
  }

  note.textContent = "「条件」徽标 = 满足条件才需要跑（不隐藏，避免不知道它存在）；" +
    "「行动卡」节点非 CLI 命令，点开看分步指引。虚线框 = 互斥选一。" +
    "▶ 高亮 = 当前正在配置的步骤（执行到哪一步了）。";
}

/* ---------------------------------------------------------------- 检查器渲染 */

function ioSection(title, items, renderItem) {
  if (!items || !items.length) return null;
  const sec = el("div", { class: "insp-section" });
  sec.appendChild(el("h3", { text: title }));
  const list = el("ul", { class: "io-list" });
  for (const item of items) list.appendChild(el("li", null, renderItem(item)));
  sec.appendChild(list);
  return sec;
}

function pitfallSection(pitfalls) {
  if (!pitfalls || !pitfalls.length) return null;
  const sec = el("div", { class: "insp-section" });
  sec.appendChild(el("h3", { text: "常见坑" }));
  for (const pf of pitfalls) {
    const text = typeof pf === "string" ? pf : pf.text;
    const ref = typeof pf === "string" ? null : pf.ref;
    const item = el("div", { class: "pitfall-item", text });
    if (ref) item.appendChild(el("span", { class: "pf-ref", text: "出处：" + ref }));
    sec.appendChild(item);
  }
  return sec;
}

/* 节点档案：怎么调用 / 有无约束 / 影响到什么 / 被谁调用（产出被谁消费在下方 outputs 段逐项给出） */
const EXEC_CLASS_ZH = { "read-only": "只读命令", "mutating": "会写记录", "manual": "人工动作（非命令）" };
const RULE_LABEL_ZH = { requires: "必配", excludes: "互斥", confirm: "需确认", suggest: "建议" };

function profileSection(node) {
  const sec = el("div", { class: "insp-section profile" });
  sec.appendChild(el("h3", { text: "节点档案（怎么调 / 约束 / 影响 / 上下游）" }));
  const list = el("ul", { class: "io-list" });

  const how = el("li");
  how.appendChild(el("div", { class: "io-name", text: "怎么调用" }));
  const ex = node.execution || {};
  let howText = node.node_type === "manual"
    ? "非 CLI 命令——按下方行动卡逐步操作。"
    : "在下方参数表单填写，底部生成完整命令（复制或经执行桥运行）。";
  howText += "类别：" + (EXEC_CLASS_ZH[ex.class] || ex.class || "未知");
  if (ex.timeout_s) howText += "；建议超时上限 " + ex.timeout_s + " 秒";
  if (ex.history === "central") howText += "；执行留痕进中央记录";
  how.appendChild(el("div", { class: "io-meta", text: howText }));
  list.appendChild(how);

  const rules = node.compose_rules || [];
  const cr = el("li");
  cr.appendChild(el("div", { class: "io-name", text: "有无约束" }));
  if (rules.length) {
    for (const r of rules) {
      const label = RULE_LABEL_ZH[r.rule] || r.rule;
      cr.appendChild(el("div", { class: "io-meta",
        text: "【" + label + "】" + (r.message || JSON.stringify(r)) }));
    }
  } else {
    cr.appendChild(el("div", { class: "io-meta", text: "无组合约束——参数按表单填写即可" }));
  }
  list.appendChild(cr);

  const ef = node.effects
    ? (typeof node.effects === "object" ? node.effects : { text: String(node.effects) })
    : null;
  if (ef) {
    const li = el("li");
    li.appendChild(el("div", { class: "io-name", text: "影响到什么" }));
    li.appendChild(el("div", { class: "io-meta", text: ef.text }));
    if (ef.ref) li.appendChild(el("div", { class: "io-consumers", text: "出处：" + ef.ref }));
    list.appendChild(li);
  }

  if (node.consumers && node.consumers.length) {
    const li = el("li");
    li.appendChild(el("div", { class: "io-name", text: "被谁调用 / 产出被谁消费" }));
    li.appendChild(el("div", { class: "io-meta",
      text: Array.isArray(node.consumers) ? node.consumers.join("、") : node.consumers }));
    list.appendChild(li);
  }

  sec.appendChild(list);
  return sec;
}

function paramRow(node, p) {
  const row = el("div", { class: "param-row", "data-param": p.id });
  const head = el("div", { class: "param-head" });
  const flagLabel = p.flag == null ? "<" + (p.name || p.id) + ">" : p.flag;
  const flagEl = el("span", { class: "param-flag" });
  flagEl.appendChild(document.createTextNode(flagLabel));
  if (p.form.required) flagEl.appendChild(el("span", { class: "req-mark", text: "*" }));
  head.appendChild(flagEl);
  head.appendChild(el("span", { class: "param-kind", text: kindLabel(p) }));
  row.appendChild(head);

  const ctrl = el("div", { class: "param-control" });
  // 表单初始值走 paramValue（含默认值预填），与命令预览/桥执行同源，
  // 避免"表单看着空、命令里却带着默认值"的两张皮
  const cur = paramValue(node.id, p);
  const widget = p.form.widget;
  let input;

  if (widget === "choice") {
    input = el("select");
    input.appendChild(el("option", { value: "", text: "（默认：" + displayDefault(p) + "）" }));
    for (const c of (p.type && p.type.choices) || []) {
      const opt = el("option", { value: c, text: c });
      // selected 走 property 而非 setAttribute——setAttribute("selected", null)
      // 会给每个 option 挂上 selected，浏览器取最后一个（M2 验收发现的 M1 缺陷）
      opt.selected = cur === c;
      input.appendChild(opt);
    }
  } else if (widget === "flag") {
    const wrap = el("label", { class: "switch" });
    input = el("input", { type: "checkbox" });
    input.checked = cur === true;
    wrap.appendChild(input);
    wrap.appendChild(el("span", { class: "track" }));
    wrap.appendChild(el("span", { class: "state-text", text: input.checked ? "开" : "关" }));
    input.addEventListener("change", () => {
      wrap.querySelector(".state-text").textContent = input.checked ? "开" : "关";
    });
    ctrl.appendChild(wrap);
  } else if (widget === "number") {
    input = el("input", { type: "number" });
    if (p.type && p.type.min != null) input.min = p.type.min;
    if (p.type && p.type.max != null) input.max = p.type.max;
    if (p.type && p.type.kind === "int") input.step = "1";
    if (cur != null) input.value = cur;
    if (p.default != null && cur == null) input.placeholder = "默认 " + p.default;
  } else if (widget === "runner") {
    input = el("textarea", { rows: "2", placeholder: p.form.placeholder ||
      "例如：claude -p　（stdin 进指令 / stdout 出 JSON / 退出码可靠）" });
    if (cur != null) input.value = cur;
  } else {
    input = el("input", { type: "text" });
    if (p.form.placeholder) input.placeholder = p.form.placeholder;
    else if (p.default != null && p.default !== false) input.placeholder = "默认 " + p.default;
    if (cur != null) input.value = cur;
    if (widget === "multi-choice") {
      input.placeholder = "多个值用逗号分隔，如 W-02,W-08";
    }
    if (widget === "path") {
      input.placeholder = p.form.placeholder || "目录路径（静态模式不校验存在性）";
    }
  }

  if (widget !== "flag") {
    ctrl.appendChild(input);
  }

  // 焦点 → 命令 token 高亮
  const focusHandler = () => {
    state.focusParam = p.id;
    row.classList.add("focused");
    renderCommand(node);
  };
  const blurHandler = () => {
    state.focusParam = null;
    row.classList.remove("focused");
    renderCommand(node);
  };
  input.addEventListener("focus", focusHandler);
  input.addEventListener("blur", blurHandler);

  // 数值越界：失焦时钳制到范围内（SOP M1-17）
  if (widget === "number") {
    input.addEventListener("change", () => {
      const n = Number(input.value);
      if (input.value !== "" && Number.isFinite(n) && p.type) {
        if (p.type.min != null && n < p.type.min) input.value = p.type.min;
        else if (p.type.max != null && n > p.type.max) input.value = p.type.max;
      }
    });
  }

  input.addEventListener("input", () => {
    const v = widget === "flag" ? input.checked : input.value;
    setParamValue(node.id, p, v);
    refreshRowMessages(row, node, p);
    renderCommand(node);
  });

  if (p.effects) ctrl.appendChild(el("div", { class: "param-hint effects", text: p.effects }));
  if (p.pitfall) {
    const pt = typeof p.pitfall === "string" ? p.pitfall : p.pitfall.text;
    ctrl.appendChild(el("div", { class: "param-hint pitfall", text: pt }));
  }
  if (p.ref) ctrl.appendChild(el("div", { class: "param-hint ref", text: "出处：" + p.ref }));

  row.appendChild(ctrl);
  refreshRowMessages(row, node, p);
  return row;
}

/** 只刷新一行的问题消息（输入时不整树重渲染，避免丢焦点）。 */
function refreshRowMessages(row, node, p) {
  row.querySelectorAll(".msg").forEach(m => m.remove());
  const issues = computeIssues(node);
  const anchor = row.querySelector(".param-control");
  for (const e of issues.errors) {
    if (e.param === p.id) anchor.appendChild(el("div", { class: "msg error", text: "✕ " + e.text }));
  }
  for (const w of issues.warns) {
    if (w.param !== p.id) continue;
    const msg = el("div", { class: "msg warn", text: "⚑ " + w.text });
    if (w.confirmKey) {
      msg.appendChild(el("button", {
        class: "msg-confirm-btn", type: "button", text: "我知道，确认",
        onclick: () => { state.confirmed.add(w.confirmKey); renderAll(); },
      }));
    }
    anchor.appendChild(msg);
  }
}

function kindLabel(p) {
  const t = p.type || {};
  if (t.kind === "flag") return "开关";
  if (t.kind === "choice") return "枚举" + (t.choices ? `：${t.choices.join(" / ")}` : "");
  if (t.kind === "path") return "路径" + (t.must_be_dir ? "（目录）" : "") + (t.must_exist ? "（须存在）" : "");
  if (t.kind === "int") return "整数" + rangeSuffix(t);
  if (t.kind === "float") return "数值" + rangeSuffix(t);
  if (p.nargs === "*") return "可多个";
  if (p.nargs === 2) return "两个值";
  return "文本";
}

function rangeSuffix(t) {
  if (t.min != null && t.max != null) return `（${t.min}..${t.max}）`;
  if (t.min != null) return `（≥ ${t.min}）`;
  if (t.max != null) return `（≤ ${t.max}）`;
  return "";
}

function displayDefault(p) {
  if (p.default == null || p.default === false) return "不启用";
  if (p.default === true) return "启用";
  return String(p.default);
}

function renderInspector() {
  const box = $("#inspector");
  box.textContent = "";
  const node = state.selectedNode ? DATA.nodes[state.selectedNode] : null;
  if (!node) {
    box.appendChild(el("div", { class: "placeholder-empty",
      text: "← 点击左侧节点链中的任一节点，查看逐参数表单与产出/消费明细" }));
    return;
  }

  box.appendChild(el("h2", { text: node.title }));
  if (node.summary) box.appendChild(el("div", { class: "node-summary", text: node.summary }));
  if (node.condition) {
    box.appendChild(el("div", { class: "msg warn",
      text: "⚑ 条件节点：" + node.condition }));
  }
  if (node.ref) box.appendChild(el("div", { class: "node-ref", text: "出处：" + node.ref }));

  box.appendChild(profileSection(node));

  // lint 规则目录（M4-01）：rules 快照逐条渲染，级别徽标 + 修复指引（title 悬浮）
  if (node.rules && node.rules.length) {
    const sec = el("div", { class: "insp-section" });
    sec.appendChild(el("h3", {
      text: `规则目录（${node.rules.length} 条）` +
        (node.rules_note ? "" : "") }));
    if (node.rules_note) {
      sec.appendChild(el("div", { class: "param-hint ref", text: node.rules_note }));
    }
    for (const r of node.rules) {
      const row = el("div", { class: "rule-row", title: r.remediation ? "修复指引：" + r.remediation : "" });
      row.appendChild(el("span", { class: "rule-rid", text: r.rid }));
      row.appendChild(el("span", { class: "rule-lv lv-" + r.level, text: r.level }));
      row.appendChild(el("span", { class: "rule-title", text: r.title }));
      sec.appendChild(row);
    }
    box.appendChild(sec);
  }

  if (node.node_type === "manual") {
    renderActionCards(box, node);
    return;
  }

  // 逐参数表单：位置参数固定在最前
  const formSec = el("div", { class: "insp-section" });
  formSec.appendChild(el("h3", { text: "参数表单（带 * 必填）" }));
  for (const p of node.params) formSec.appendChild(paramRow(node, p));
  box.appendChild(formSec);

  const inputs = ioSection("输入（要准备什么）", node.inputs, item => {
    const frag = document.createDocumentFragment();
    frag.appendChild(el("div", { class: "io-name", text: item.name }));
    if (item.from) frag.appendChild(el("div", { class: "io-meta", text: "来源：" + item.from }));
    if (item.shape) frag.appendChild(el("div", { class: "io-consumers", text: "形态：" + item.shape }));
    return frag;
  });
  if (inputs) box.appendChild(inputs);

  const outputs = ioSection("产出（去哪里、谁消费）", node.outputs, item => {
    const frag = document.createDocumentFragment();
    frag.appendChild(el("div", { class: "io-name", text: item.name }));
    if (item.path) frag.appendChild(el("div", { class: "io-meta", text: item.path }));
    if (item.schema) frag.appendChild(el("div", { class: "io-consumers", text: "schema：" + item.schema }));
    if (item.consumers) frag.appendChild(el("div", { class: "io-consumers",
      text: "消费方：" + (Array.isArray(item.consumers) ? item.consumers.join("、") : item.consumers) }));
    return frag;
  });
  if (outputs) box.appendChild(outputs);

  const pitfalls = pitfallSection(node.pitfalls);
  if (pitfalls) box.appendChild(pitfalls);
}

function renderActionCards(box, node) {
  const sec = el("div", { class: "insp-section" });
  sec.appendChild(el("h3", { text: "行动卡（按步骤操作）" }));
  for (const act of node.actions || []) {
    const card = el("div", { class: "action-card" });
    card.appendChild(el("span", { class: "step-no", text: "步骤 " + act.step }));
    card.appendChild(el("span", { class: "step-text", text: act.text }));
    if (act.node_ref) {
      card.appendChild(el("div", { class: "step-node",
        text: "→ 跳转节点：" + act.node_ref,
        onclick: () => selectNode(act.node_ref) }));
    }
    if (act.ref) card.appendChild(el("div", { class: "step-ref", text: "出处：" + act.ref }));
    sec.appendChild(card);
  }
  box.appendChild(sec);
  const pitfalls = pitfallSection(node.pitfalls);
  if (pitfalls) box.appendChild(pitfalls);
}

/* ---------------------------------------------------------------- 顶层渲染 */

function selectNode(nodeId, stepKey) {
  state.selectedNode = nodeId;
  // 步骤上下文：从流程线卡片点击时带上（同节点多步时精确高亮那一步）；
  // 其他入口（行动卡跳转/套餐）不带 → 回退「只标第一条匹配步」
  state.selectedStep = stepKey || null;
  state.focusParam = null;
  renderCanvas();
  renderInspector();
  renderCommand(DATA.nodes[nodeId]);
}

function renderDomainTabs() {
  const tabs = $("#domain-tabs");
  tabs.textContent = "";
  for (const d of DATA.domains) {
    tabs.appendChild(el("button", {
      class: "domain-tab" + (d.id === state.domain ? " active" : ""),
      type: "button",
      text: d.title || d.id,
      onclick: () => {
        state.domain = d.id;
        state.selectedNode = null;
        state.selectedStep = null;
        renderDomainTabs();
        renderCanvas();
        renderInspector();
        renderCommand(null);
      },
    }));
  }
}

function renderAll() {
  renderCanvas();
  renderInspector();
  renderCommand(DATA.nodes[state.selectedNode]);
}

function init() {
  $("#snap-version").textContent = DATA.tool_version || "";
  $("#snap-time").textContent = "构建于 " + (DATA.generated_at || "未知");
  $("#cmd-copy").addEventListener("click", copyCommand);
  $("#cmd-run").addEventListener("click", runViaBridge);
  $("#cmd-history").addEventListener("click", showHistory);
  $("#history-close").addEventListener("click", () => { $("#history-panel").hidden = true; });
  renderDomainTabs();
  renderCanvas();
  renderInspector();
  renderCommand(null);
  // 默认选中第一条流程线的首个命令节点（label 型说明步骤无命令，跳过），开箱即见表单
  const pipeline = DATA.pipelines.find(p => p.domain === state.domain) || DATA.pipelines[0];
  const firstIdx = pipeline ? pipeline.steps.findIndex(s => s.node) : -1;
  if (firstIdx >= 0) {
    selectNode(pipeline.steps[firstIdx].node, pipeline.id + "#" + firstIdx);
  }
  initSplitter();
  detectBridge();  // 异步探测执行桥，不阻塞静态功能
}

/* ---------------------------------------------------------------- 布局：左栏拖宽 / 收起 */

function initSplitter() {
  const layout = $("#layout");
  const splitter = $("#splitter");
  const toggle = $("#canvas-toggle");
  if (!splitter || !toggle) return;
  const MIN_W = 240;
  let dragging = false;

  splitter.addEventListener("mousedown", (e) => {
    if (e.target === toggle || document.body.classList.contains("canvas-collapsed")) return;
    dragging = true;
    e.preventDefault();  // 拖动时别选中文本
  });
  document.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const rect = layout.getBoundingClientRect();
    // 右栏至少留 360px；超出即到头
    const w = Math.min(Math.max(e.clientX - rect.left, MIN_W), rect.width - 360);
    layout.style.gridTemplateColumns = w + "px 6px 1fr";
  });
  document.addEventListener("mouseup", () => { dragging = false; });
  splitter.addEventListener("dblclick", () => { layout.style.gridTemplateColumns = ""; });

  toggle.addEventListener("click", () => {
    const collapsed = document.body.classList.toggle("canvas-collapsed");
    layout.style.gridTemplateColumns = "";  // 清掉拖宽的行内样式，交给收起态类接管
    toggle.textContent = collapsed ? "⟩" : "⟨";
    toggle.title = collapsed ? "展开左栏" : "收起左栏";
    splitter.title = collapsed ? "展开左栏" : "拖动调整左栏宽度；双击恢复默认宽度";
  });
}

/* ---------------------------------------------------------------- 桥模式（M3） */

async function detectBridge() {
  try {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 1500);
    const res = await fetch(BRIDGE_URL + "/health", { signal: ctl.signal });
    clearTimeout(timer);
    if (!res.ok) return;
    enterBridgeMode(await res.json());
  } catch (_) { /* 探不到桥 = 静态模式，保持快照横幅 */ }
}

async function enterBridgeMode(health) {
  state.bridge = true;
  const badge = document.querySelector("#snapshot-banner .snap-badge");
  badge.textContent = "桥已连接";
  badge.classList.add("bridge");
  $("#snapshot-banner").title = "执行桥在线（" + (health.tool_version || "版本未知") +
    "）：参数面以 /catalog 实况为准，可一键执行";
  $("#snap-version").textContent = health.tool_version || "";
  $("#snap-time").textContent = "实况目录 · 刷新页面即同步";
  $("#run-row").hidden = false;
  $("#cmd-run").hidden = false;
  $("#cmd-history").hidden = false;
  try {
    const res = await fetch(BRIDGE_URL + "/catalog");
    if (!res.ok) throw new Error("HTTP " + res.status);
    applyCatalog(await res.json());
  } catch (e) {
    toast("桥已连接，但实况目录获取失败：" + e.message);
  }
}

/** 用实况目录替换内联快照（语义层仍来自桥端 manual 合并，页面零硬编码）。 */
function applyCatalog(catalog) {
  const had = state.selectedNode;
  DATA = catalog;
  state.domain = DATA.domains.length ? DATA.domains[0].id : null;
  if (had && DATA.nodes[had]) state.selectedNode = had;
  else state.selectedNode = null;
  renderDomainTabs();
  renderCanvas();
  renderInspector();
  renderCommand(state.selectedNode ? DATA.nodes[state.selectedNode] : null);

  const banner = $("#catalog-banner");
  const diff = catalog.diff || {};
  if (diff.available && (diff.new_nodes.length || diff.removed_nodes.length ||
                         diff.param_changes.length)) {
    banner.hidden = false;
    banner.textContent = "⟳ 实况差异（相较入库快照）：" + diff.summary +
      (diff.new_nodes.length ? "——新节点：" + diff.new_nodes.join("、") : "") +
      "（悬停看逐字段明细）";
    banner.title = JSON.stringify({
      param_changes: diff.param_changes, removed_nodes: diff.removed_nodes,
      notes: catalog.notes || [],
    }, null, 2);
  } else {
    banner.hidden = true;
  }
}

async function runViaBridge() {
  const node = DATA.nodes[state.selectedNode];
  if (!node || node.node_type !== "cli" || !state.bridge) return;
  if (computeIssues(node).errors.length) return;
  // 已显式确认的 confirm 规则随请求上报（桥端二次校验，不信任页面）
  const confirmed = [];
  for (const rule of node.compose_rules || []) {
    if (rule.rule !== "confirm") continue;
    const p = node.params.find(x => x.id === rule.param);
    if (!p) continue;
    const active = p.form.widget === "flag" ? paramValue(node.id, p) === true
      : paramValue(node.id, p) != null;
    if (active && state.confirmed.has(node.id + "|" + rule.param)) confirmed.push(rule.param);
  }
  const args = {};
  for (const p of node.params) {
    const v = paramValue(node.id, p);
    if (v === true) args[p.id] = true;
    else if (v != null) args[p.id] = v;
  }
  const btn = $("#cmd-run");
  const out = $("#run-output");
  btn.disabled = true;
  btn.textContent = "执行中…";
  try {
    const res = await fetch(BRIDGE_URL + "/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ node: node.id, args, confirmed,
                             cwd: $("#run-cwd").value.trim() || undefined }),
    });
    const data = await res.json();
    out.hidden = false;
    if (!res.ok) {
      out.textContent = "✕ 桥端拒绝（HTTP " + res.status + "）：\n" + (data.error || "");
      toast("桥端拒绝执行");
      return;
    }
    out.textContent = `$ ${node.title}　（exit=${data.exit_code}，` +
      `${data.duration_ms}ms${data.timed_out ? "，超时强杀" : ""}）\n` +
      (data.stdout || "") + (data.stderr ? "\n[stderr]\n" + data.stderr : "");
    toast(data.ok ? "执行成功（exit 0）" : "执行结束（exit " + data.exit_code + "）");
  } catch (e) {
    toast("执行失败：" + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "▶ 执行";
  }
}

async function showHistory() {
  try {
    const res = await fetch(BRIDGE_URL + "/history?limit=50");
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    const list = $("#history-list");
    list.textContent = "";
    if (!data.records.length) {
      list.appendChild(el("div", { class: "placeholder-empty",
        text: "暂无执行审计（经桥跑一次命令后再看）" }));
    }
    for (const r of data.records.slice().reverse()) {
      list.appendChild(el("div", { class: "history-item" },
        el("div", { class: "history-line" },
          el("span", { class: "history-ts", text: r.ts }),
          el("span", { class: "history-node", text: r.node }),
          el("span", { class: "history-exit " + (r.exit_code === 0 ? "ok" : "bad"),
            text: "exit " + r.exit_code + " · " + r.duration_ms + "ms" +
                  (r.timed_out ? " · 超时强杀" : "") })),
        el("div", { class: "history-argv", text: "$ " + (r.argv || []).join(" ") })));
    }
    $("#history-panel").hidden = false;
  } catch (e) {
    toast("历史读取失败：" + e.message);
  }
}

document.addEventListener("DOMContentLoaded", init);
