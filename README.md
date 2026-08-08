# ZotNotes — Zotero → Obsidian 论文笔记工具

GUI 工具：列出 Zotero 文献库中的论文，勾选后自动生成 Markdown 深度笔记写入 Obsidian 仓库，
可选接 OpenAI 兼容接口（DeepSeek/Kimi/GLM 等）。生成采用**多阶段深度精读管道**
（参考 DeepPaperNote 设计）：读取 PDF 正文 → 提取图表 → LLM 写作规划 → 撰写 → 校验修复。

## 运行前提

1. **Zotero 7** 已运行，且已开启本地 API：
   设置 → 高级 → 勾选 *Allow other applications on this computer to communicate with Zotero*（需重启 Zotero 生效）。
2. **Better BibTeX 插件**（可选但推荐）：Zotero → 工具 → 插件 → 安装
   <https://retorque.re/zotero-better-bibtex/> 。装上后条目有稳定 citekey（如 `Endrei2026`），
   未安装时程序自动用「首作者+年份+Zotero key」生成。
3. **Obsidian vault**：笔记写入的仓库路径，程序只往里面写 `.md` 笔记，不依赖 Obsidian 运行。

## 运行方式

### 方式一：绿色免安装 exe（推荐给终端用户）

1. 从 **GitHub Releases** 下载最新的 `ZotNotes.exe`（单文件，自包含）。
2. 双击运行即可，无需本机装 Python；首次运行会在 exe 同目录自动生成 `config.json` 与 `template.md`。
3. 首次使用：点顶部「设置」填写 vault 路径与 LLM 接口，保存后「刷新」。

### 方式二：源码 + venv 运行（开发/修改用）

```bash
# 环境装在 D 盘（首次）
python -m venv /d/Users/pbrii/zotnotes_venv
/d/Users/pbrii/zotnotes_venv/Scripts/python.exe -m pip install -r requirements.txt

# 运行
cd /c/Users/pbrii/Desktop/论文笔记/zotnotes_tool
/d/Users/pbrii/zotnotes_venv/Scripts/python.exe main.py
```

### 打包 exe（改了源码后）

```bash
cd /c/Users/pbrii/Desktop/论文笔记/zotnotes_tool
/d/Users/pbrii/zotnotes_venv/Scripts/python.exe -m PyInstaller --clean --noconfirm ZotNotes.spec
# 产物为单个 dist/ZotNotes.exe（onefile，theme.json/icon.ico 已内置）
```

> `ZotNotes.spec` 是 **onefile** 配置：`collect_all` 收集 customtkinter/pdfplumber/pdfminer/pymupdf，
> `theme.json`、`icon.ico` 作为 datas 内置进 exe（运行时 `config.resource_path` 优先读 exe 同目录用户文件、
> 缺失回退内置副本，用户仍可覆盖配色）。`config.json`、`template.md` **不内置**——首启时在 exe 同目录
> 自动生成/创建，保证用户可编辑。发布到 GitHub 时把 exe 作为 **Release 资产**上传（不进源码仓库）。

## 使用流程

1. 点「设置」：确认 Zotero API 地址、vault 路径、笔记文件夹（默认 `LiteratureNotes`）、模板文件路径，
   填入 LLM 的 Base URL / API Key / 模型名。
2. 点「刷新」加载文献（大库自动分页拉全，单页上限 100）。右侧状态列显示
   「未生成 / 已生成 / 需原文 / 需修复」，每行有「PDF」「生成」按钮。
3. 单篇：点某行「生成」；批量：勾选多篇 → 点「生成勾选的笔记」；点「PDF」用系统阅读器打开原文。
4. 生成后可在 Obsidian 中打开对应笔记。

## 笔记模板

- 笔记按模板文件渲染，模板路径在「设置」里指定（可放 vault 内用 Obsidian 编辑）。
- 顶部「模板」按钮直接用系统默认程序打开模板文件。
- 占位符（带 `zotero:` 前缀，避免与 Obsidian 内置模板语法冲突）：
  `{{zotero:title}}` `{{zotero:authors}}` `{{zotero:year}}` `{{zotero:doi}}` `{{zotero:url}}`
  `{{zotero:zotero_key}}` `{{zotero:tags}}` `{{zotero:pdf}}` `{{zotero:item_type}}` `{{zotero:note_file}}`
  `{{zotero:llm}}`（LLM 生成的多阶段深度笔记正文；LLM 未启用或失败时为空白）
- 指定路径不存在时，程序会自动创建默认模板。

## 生成质量（多阶段深度管道）

- **正文提取**：`pdfplumber` 解析 PDF 全文（截取前约 3 万字符）作为证据。
- **图表提取**：`pymupdf` 按图注（"Figure N / Fig. N"）定位并渲染 PDF 图表，保存到
  `笔记文件夹/images/<citekey>/`，正文用相对路径 `![...](images/<citekey>/fig_N.png)` 引用。
- **写作规划**：LLM 第一轮读证据包输出结构化 JSON 计划（论文类型/要点/图表取舍/机制流程/关键数值）。
- **撰写**：LLM 第二轮按固定章节骨架写整篇笔记（核心信息/原文摘要翻译/创新点/一句话总结/方法主线含机制流程/核心实验/局限/与我的研究的关系）。
- **校验修复**：`lint_note` 检查必需章节、占位符、图表引用、表格单元格公式、表格列数、标题层级；
  发现缺失时 LLM 第三轮修复，**修复后再 lint 一次**；仍含占位符或缺必需章节则判定失败（不写入残缺笔记），按钮变「重试」。
- **Obsidian 渲染约束**：WRITE_SYSTEM 明令表格单元格内禁用 `$...$` 行内公式（Obsidian 表格内公式渲染异常），
  单元格符号用纯文本或反引号（如 `I_SR`）；表格各行列数一致；标题只用 `##` / `###`。
- **fail-closed**：无 PDF 正文且无摘要时不硬编，生成骨架笔记并标记 `evidence: insufficient`，GUI 显示橙色「需原文」；
  「需原文」骨架可直接点「生成」重试，无需开启覆盖。
- **覆盖保护**：重复生成只覆盖 LLM 正文，旧笔记手写的「我的笔记 / 疑问」分区会被拼回新笔记（`merge_handwritten`），不会丢手写内容。
- 批量生成**并发执行**（最多 3 路，`MAX_WORKERS=3`）。
- **失败隔离**：某篇 LLM 调用失败时不写入残缺笔记，该行按钮变「重试」，可单独重试。

## 笔记格式

每篇笔记一个 `.md` 文件，文件名 = citekey。frontmatter 含 `zotero_key`、标题、作者、年份、DOI、URL、
标签、PDF 路径、`aliases`（论文标题，Obsidian 文件树中显示为别名，可 `[[论文标题]]` 链接）；
正文含 LLM 生成的深度笔记分区 + 手写的「我的笔记」「疑问」分区（重新生成时保留）。
程序通过扫描笔记目录里各文件 frontmatter 的 `zotero_key` 判断某篇是否已生成（改名也能识别），
**单次扫描**即可同时得出三种状态集合：
- `ok`：完整笔记 → 绿色「已生成」
- `insufficient`：`evidence: insufficient` 骨架 → 橙色「需原文」
- `placeholder`：正文（「## 我的笔记」之前）含 ≥2 处「待补充/TODO/TBD」→ 红色「需修复」

列表行的元信息行会显示 `更新于 <时间>`：取自笔记文件最后修改时间，
Obsidian 里手动编辑过即为编辑时间，从未编辑过即生成时间。

## 项目结构

```
main.py              入口
config.py            配置读写 (config.json)；frozen 时 BASE_DIR 指向 exe 目录
zotero_client.py     Zotero 本地 API 客户端（分页拉全、PDF 附件定位、citekey 兜底）
note_generator.py    多阶段深度管道（正文/图表提取 + plan/write/lint/fix + 骨架）
obsidian_writer.py   vault 写入（含 images 导入、手写区合并）+ 状态检测
template.md          默认笔记模板（可自定义）
gui/app.py           主窗口（文献列表 + 每行/批量生成，线程安全 UI 调度）
gui/settings_view.py 设置窗口
gui/icons.py         PIL 绘制线性图标
test_core.py         只读自检脚本
test_pipeline.py     端到端管道测试
ZotNotes.spec        PyInstaller 打包配置
架构流程图.md         Mermaid 架构流程图
修复计划.md           历次修复计划存档
```

## 依赖

```
customtkinter  openai  requests  pdfplumber  pymupdf   # PIL 由 customtkinter 环境提供
```

## 常见问题

- **列表为空 / 读取失败**：Zotero 未启动或未开本地 API（见运行前提）；开启「仅显示含 PDF」时无 PDF 条目被隐藏。
- **生成失败 / 按钮变「重试」**：网络、代理或接口限流，程序对接口超时自动重试；可稍后点「重试」。
- **摘要空 / 状态「需原文」**：未开「读取 PDF 正文」，或 PDF 是扫描版（无文字层）。
- **`config.json` 明文存 API Key**：不要整文件夹分享；拷贝给别人前清空 `llm_api_key`。
