# AGENTS.md — 减肥管家 · AI 代理协作约定（扣子编程 / 其他 AI 会话必读）

> 任何 AI 在这个仓库里拉代码、改代码、部署之前，必须先读完本文件并遵守。
> 项目文档索引见 `docs/README.md`；运行链路见 `docs/06-运行流程.md`。

## 项目本质

- `code/app.py`：**单文件零依赖** Python 服务（仅标准库，禁止引入第三方依赖）
- 前端：app.py 内嵌的 `INDEX`（单页），CSS 走**设计令牌架构**（见下）
- 数据（用户的真实账本，动它之前先想）：
  - `data/fitness.db` — SQLite，唯一的账本
  - `data/profiles/*.json` — 用户身体档案与热量线
  - `data/meals/*.jpg` — 记录照片

## 部署链路（扣子编程 veFaaS）

```
setup.sh（生成 config.json，支持环境变量注入）→ http_run.sh -p $PORT → app.py
```

- 端口：`PORT` 环境变量优先，回退 config.json 的 port
- 环境变量注入（在扣子平台密钥区配置，不要写进仓库）：
  `FITNESS_ACCESS_CODE` / `FITNESS_LLM_API_KEY` / `FITNESS_TEXT_LLM_API_KEY`
  （BASE_URL/_MODEL 有默认值可不设；本地已有 config.json 时保留不覆盖）

## 🔴 每次拉代码 / 合并 / 部署的强制检查清单

1. 合并后 `python -m py_compile code/app.py` 必须通过
2. **四大部署适配禁止丢失**（历史上丢过，逐项 grep 确认）：
   - `init_db()` 开头的 `os.makedirs`（data/profiles/meals 三目录）
   - `PORT` 环境变量优先逻辑（main 里）
   - `scripts/http_run.sh`（-p 传端口 + PORT 导出）
   - `.coze/` 目录
3. 全文件 grep 无冲突标记：`<<<<<<<` `=======` `>>>>>>>`
4. 前端 JS：提取 script 块跑 `node --check`
5. **关键元素/函数存在**（历史教训：丢过 `<script>` 开标签导致全页静默瘫痪、丢过设置弹窗导致 mockChk null）：
   - `<script>` 标签恰好 1 个
   - `function showBack`、`id="mockChk"`、`id="mback"`、`id="u1"`
6. 设计令牌：CSS 颜色只允许 `var()` 引用（:root Base + [data-theme=home 绿 / meal 蓝]），禁止硬编码色值；两套主题结构完全一致仅颜色不同

## ⚠️ 数据安全红线

- `data/fitness.db` 是用户**真实账本**。FaaS 沙箱重建会清空它：
  - 任何"重新部署/清空/迁移数据"的操作前，**必须先明确告知用户数据会丢，经确认才执行**
  - 已知局限：SQLite 在沙箱内不持久；是否迁移平台数据库由用户决定，勿擅自迁移
- 测试模式（mock）：只能由用户在设置页开关；**生产部署配置必须 mock=false**
- 误导性文案禁止：不给进食引导建议（如"可以吃夜宵"），超支提示用状态陈述

## 配置注入约定

- `code/config.json` 被 .gitignore（含 API key，绝不入库、绝不截图外传）
- setup.sh：无 config.json 时从 config.example.json 生成占位；`FITNESS_*` 环境变量注入真实值
- 工作区已有 config.json → 保留，部署打包不得用模板覆盖

## 协作约定

- 大改动先输出**报告清单**再执行；涉及数据的问题**必须先问**
- 自检顺序：py_compile → node --check（提取 script）→ 本地启动探活 /api/health → 访问码 401/带码 200 → 真实识别非 400 固定值
- 完成后报告：做了什么、改了哪些文件、用户需要做什么

## 🏷️ 发布（tag）策略

- **提交（push）≠ 发布（tag）**：日常只 push 代码，线上服务不动；实验性改动随时可提交
- 打 tag 的唯一条件：**用户明确说「发布/上线/更新到服务器」**，或完成完整功能批次后用户确认
- 我（AI）不得擅自打 tag 发布
- 打 tag 前的固定自检：py_compile → 前端 JS node --check → 本地启动探活 /api/health → 访问码 401/带码 200
- 打 tag 后：等 10 秒探活线上服务并报告；异常立即回滚（git reset 到上一 tag + 重启）并告知用户
