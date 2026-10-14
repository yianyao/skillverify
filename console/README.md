# skillverify 操作台（console）

skillverify 的官方配套插件：把"哪条流程、每个节点要什么数据、有哪些参数、产出什么、谁来消费"做成可点击、可组装、可校验的本地界面。零侵入设计——不改 skillverify 任何代码，整体删除本目录即无痕。

## 快速开始（静态模式，双击即用）

```bash
python console/build.py        # 一次性构建（内省 + 合并语义层 + 内联）
```

然后**双击打开 `console/app/index.html`**——断网、无服务、无 Python 环境均可完整使用：

> **Windows 一键启动（桥模式）**：直接双击 `console/start.bat`——自动探测
> Python（含 uv）与 skillverify 可用性（没装也能用仓库模式跑），起桥 + 开页面。
> 日常运维（重跑生成器 / 同步 manual 与指南 / 处理"语义层待补"徽标）见
> **`console/操作文档.md`**。

- 左侧：语义评审主线（六步流程）节点链；「条件」徽标 = 满足条件才需要跑；虚线框 = 三档执行互斥选一；
- 右侧：逐参数表单（必填标 `*`，含参数影响与坑位提示）；
- 底部：命令预览随表单逐 token 联动高亮，校验有 error（红，阻断复制）与 warn（黄，可继续）两级；
- 顶部横幅标注数据快照版本与构建时间——**静态模式数据是构建快照**，skillverify 演进后需重建。

页面零网络请求（数据已内联进 HTML），可放心在离线环境使用。

## 重新构建（skillverify 演进后）

```bash
python console/build.py            # 重跑内省 → 重新合并 → 重新内联
git diff console/nodes.json        # 人工过目参数面差异
```

- `console/nodes.json` 是生成产物（入库，守卫比对对象）；
- 语义层在 `console/manual/*.json`（每节点一文件，可选——缺失的节点不生成，`_domain.<域>.json` 声明域/流程线/manual 型节点）；
- 机械层与语义层冲突时生成器逐条报错退出（语义层不得覆盖 argparse 已声明字段）。

## 目录结构

```
console/
  introspect.py        # 通用命令面内省脚本（子进程内执行，不含业务知识；
                       # 数据源 auto：优先 describe 协议，argparse 遍历兜底）
  build_nodes.py       # 生成器：内省机械层 + manual 语义层 → nodes.json
  build.py             # 构建脚本：nodes.json 内联进 app/index.html
  nodes.json           # 生成产物（schema: skillverify.console-nodes/1）
  manual/              # 人工语义层（每节点一文件 + 域声明）
  app/                 # index.html（构建产物）/ app.js / style.css
```

## 常见问题

**Q：双击打开后一片空白 / 提示 nodes.json 未内联？**
先跑 `python console/build.py`。`index.html` 中 `<script id="nodes-data">` 数据块由构建脚本注入。

**Q：路径输入框不校验目录存在？**
静态模式跳过存在性校验（设计约定，存在性检查留给执行桥模式）。

**Q：内省数据从哪来？**
`introspect.py` 默认 `--data-source auto`：目标模块按 describe 协议导出
`describe_surface()`（skillverify 已提供，等价于 `skillverify describe --json`）
就优先用它——稳定契约、不碰 argparse 私有结构；没有该协议的任意 argparse
工具自动回退为遍历 parser。两条数据源产出逐字段一致（守卫测试第 5 断言把关）。

**Q：为什么 `--strict` / `--blind` / `--accept` 会弹黄色确认条？**
这些是显式危险/留痕动作（confirm 规则），点"我知道，确认"放行。规则数据全部来自 `nodes.json` 的 `compose_rules`，页面与执行桥两端同源生效，不在任何一端硬编码。

**Q：语义评审的完整流程文档在哪里？**
见仓库根的验证流程指南.md（五·语义评审：三种执行方式与 schema、六·交付门禁）与操作手册.md（A5 语义评审）；操作台每个参数与坑位条目均带 `ref` 出处字段可溯源。

## 执行桥（M3，已可用）

静态模式下页面数据是构建快照。启动执行桥后刷新页面，即升级为**在线模式**（顶部徽标变绿"桥已连接"）：

```bash
# 开发仓库（未安装入口时）：
python console/serve_bridge.py --tool-cmd "python -m skillverify"
# 已安装 skillverify 入口时：
python console/serve_bridge.py
# 可选：--port 8742（默认） / --python <内省解释器> / --import/--factory/--extra-path（对接自定义 parser）
```

- **参数面实时**：`GET /catalog` 实况内省并与入库快照 diff——skillverify 改了参数，**刷新页面即见**新表单；差异在顶部横幅逐字段可见；语义层未覆盖的新命令显示"语义层待补"徽标（补 manual 即消，无需重建）；
- **一键执行**：`POST /run` 桥端二次校验（白名单 / 逐参数 schema / compose_rules，不信任页面）后以**数组 argv**（永不 shell）执行，回显 stdout/stderr 与退出码；
- **执行审计**：每次执行追加到 `<trace根>/console/history.jsonl`（`ts/node/argv/exit_code/duration_ms/timed_out`，滚动 1000 条），页面「🕘 历史」查看尾部 50 条；
- **安全边界**：仅绑 127.0.0.1；**Host 必须是回环地址、来源只接受 `file://`（`Origin: null`）
  或同源 `http://127.0.0.1:<port>`，其余一律 403 且不回 `Access-Control-Allow-Origin`**
  （不设这道闸时，浏览器里任意一个网页都能 POST `/run`——而白名单里就有 `evals --run-with`
  与 `review run --runner` 这两个"命令串"参数，等于把本机命令执行权交出去）；
  端口被占直接退出（不重试不换口）；超时按节点 `execution.timeout_s` 强杀；cwd 必须是已存在目录。
- **已知残留（别当成"已经安全了"）**：沙箱 iframe 与 `data:` 页面发出的 `Origin` 也是 `null`，
  与 `file://` 无法区分；桥在跑的时候别同时浏览不可信页面。要更硬就得改成"桥自己托管页面 +
  一次性令牌"，那是另一个量级的改动，目前没做。

页面在 `file://` 打开也能探到桥（桥已放开跨源头）；探不到桥时自动保持静态模式，一切照旧。

## 定位与边界（**这是给谁用的**）

- **它是什么**：`skillverify` 的**本地操作台**——把"有哪几条流程、每个节点要什么数据、
  有哪些参数、产出什么、哪些组合是错的"做成可点击、可校验的页面；起执行桥后能一键执行。
  事实（命令面/参数/规则）从**真解析器**派生，人只写判断（`manual/` 是人工语义层）。
- **它不是什么**：不是产品、不是服务、**不随 wheel 分发**（`pyproject.toml` 里没有它），
  也不承诺多人协作或长期托管——它是**单人本机**的自用加速器（双击 `start.bat` 即用）。
- **维护成本（要认账的部分）**：4 个 Python 文件 + 人工语义层 + 前端产物。
  **改了 `skillverify` 的命令面或 `manual/` 就必须重跑 `python console/build.py`**，
  否则 `tests/test_console_consistency.py` 会红——它把 `nodes.json`、`index.html` 的内联快照、
  以及 manual 里手抄的数字**三样都跟源码对账**。
- **要删就删干净**：CLI 的十二个命令与全部规则**不依赖** `console/`；真要移除，同时删掉
  `tests/test_console_consistency.py`、`tests/run_all.py` 里的那一行、`.github/workflows/`
  的 console-guard job，以及 `AGENTS.md`/《仓库结构说明》里的提及——否则守卫会红着提醒你。
