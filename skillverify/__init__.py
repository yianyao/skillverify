"""skillverify —— Agent Skill 生命周期验证套件（个人小团队版）。

设计前提：≤2 人团队、宿主无关、纯标准库优先、强制 UTF-8。
对外只暴露必要的入口，内部模块按职责分层：

  encoding  强制 UTF-8 的 IO 辅助（根治 Windows GBK 崩溃）
  spec      官方规范校验（对齐 skills-ref 0.1.1 行为）
  lint      官方留白的补检（引用/预算/卫生/脚本契约/安全/依赖）
  evalx     评测资产校验（官方 evals.json schema 与 workspace 结构）
  discover  技能发现（声明式宿主适配，不含宿主名硬编码）
  report    统一结果模型与人读/机读输出
  cli       命令行入口
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
