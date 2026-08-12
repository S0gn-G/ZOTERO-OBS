# ZotNotes — Zotero → Obsidian 论文精读笔记

ZotNotes 是一个 Windows 桌面工具：从正在运行的 Zotero 读取文献和 PDF，调用 OpenAI 兼容模型生成结构化 Markdown 精读笔记，再把笔记与图表整体写入指定的 Obsidian 笔记目录。

- 源码：<https://github.com/westriver-moon/ZOTERO-OBS>
- Windows 成品：<https://github.com/westriver-moon/ZOTERO-OBS/releases>
- 当前发行版：`v0.2.0-rc.2`

## 使用条件

1. Windows 10/11。
2. Zotero 7 正在运行，并允许本机其他程序通信。
3. 一个用于保存论文笔记的文件夹，可以手动选择，也可以从 Obsidian 已登记的 Vault 中自动接入；写入时不要求 Obsidian 正在运行。
4. OpenAI 兼容接口的 Base URL、API Key 和模型名。
5. Better BibTeX 可选；没有 citekey 时程序会生成稳定的兜底名称。

## 快速开始

1. 下载并运行 `ZotNotes.exe`，或按下文说明从源码启动。
2. 可以点击顶栏“自动接入”，由程序寻找正在运行的 Zotero 和本机有效的 Obsidian Vault；只有一个 Vault 时直接接入其 `LiteratureNotes`，多个 Vault 时在专用窗口中选择一个。也可以跳过此按钮，继续手动选择输出文件夹。
3. 打开“设置”：
   - 确认自动接入的笔记目录，或手动选择最终输出文件夹；
   - 模板通常保持默认；
   - 填写模型接口地址、API Key 和模型名；
   - “研究领域 / 写作偏好”可留空。
4. 保存设置并刷新 Zotero 文献。
5. 搜索或筛选文献，单篇生成，或勾选当前列表后批量生成。
6. 已生成的文献可以直接重新生成；`## 我的笔记` 和 `## 疑问` 两个手写区会被保留。

主界面提供以下视图：

| 视图 | 内容 |
|---|---|
| 含 PDF | 默认视图，只显示带 PDF 附件的条目 |
| 全部 | 包括没有 PDF 的条目 |
| 未生成 | 尚无对应笔记的条目 |
| 需处理 | 需原文、仅摘要、需修复或上次生成失败的条目 |

“全选当前列表”只选择当前搜索与筛选结果。“PDF”按钮使用系统默认阅读器打开附件。批量生成最多并发处理 3 篇文献。

“自动接入”是显式操作：程序启动时不会自动读取 Obsidian 注册文件，也不会替用户切换笔记目录；只有点击按钮后才运行发现插件。界面还提供日间与夜间模式，可通过顶栏按钮即时切换并在下次启动时恢复。日间模式使用白色页面、黑色主操作和浅灰辅助面；夜间模式使用深灰页面、浅色主操作与相同的小面积语义状态色。论文列表整行共享同一悬停状态；鼠标经过标题、状态、空白处或操作按钮时不会反复闪烁。搜索输入会在短暂停顿后统一刷新，并复用已经创建的论文行，避免连续输入时重复重建整张列表。批量任务失败时，界面会在汇总状态之外直接显示首个具体错误，便于定位问题。

## 状态含义

| 状态 | 含义 |
|---|---|
| 未生成 | 尚无对应笔记 |
| 已生成 | 笔记完整 |
| 仅摘要 | PDF 正文不可用，依据 Zotero 摘要生成 |
| 需原文 | PDF 正文和摘要都不可用，只生成证据不足骨架 |
| 需修复 | 已有笔记正文仍含占位内容，可重新生成 |
| 失败 | 本次模型调用、校验或文件提交失败，可重试 |

## 设置与配置

界面只保留六项用户设置：

| 字段 | 用途 |
|---|---|
| `notes_path` | 最终的论文笔记输出目录 |
| `template_path` | Markdown 模板；留空时使用程序目录的 `template.md` |
| `llm_base_url` | OpenAI 兼容接口地址 |
| `llm_api_key` | API Key |
| `llm_model` | 模型名称 |
| `llm_profile` | 研究领域或写作偏好；留空时使用通用学术研究者设定 |

此外，程序会在配置文件中保存一项界面状态 `appearance_mode`，值为 `light` 或 `dark`。它只记录顶栏日间/夜间按钮的当前选择，不是设置页中的新增选项。

Zotero 地址固定为 `http://127.0.0.1:23119/api/`；“自动接入”只对该标准本地 API 发出一个小型探测请求，不读取完整文献库。Obsidian provider 只读取 `%APPDATA%\obsidian\obsidian.json` 中已登记且仍存在的 Vault；发现阶段不创建目录。文献存在 PDF 时始终读取正文，不提供额外高级开关。

配置保存在源码目录或 `ZotNotes.exe` 同目录的 `config.json`。文件结构与 `config.example.json` 一致：

```json
{
  "notes_path": "",
  "template_path": "",
  "llm_base_url": "https://api.deepseek.com/v1",
  "llm_api_key": "",
  "llm_model": "deepseek-chat",
  "llm_profile": "",
  "appearance_mode": "light"
}
```

旧版的 Vault 路径和笔记子目录会在读取时合并为 `notes_path`；缺少界面状态的旧配置默认使用日间模式。保存后只会写入上述六项用户设置和一项界面状态。`config.json` 含明文 API Key，已被 `.gitignore` 排除，不要上传或分享个人配置。

## 生成与写入规则

```text
Zotero 本地 API
  → 文献、附件与 citekey
  → PDF 正文和图表提取
  → LLM 规划、写作、校验与一次修复
  → Markdown 和图片事务提交
  → Obsidian 笔记目录
```

证据不足时程序不会要求模型猜测：没有 PDF 正文但有摘要时标记为“仅摘要”；正文和摘要都没有时生成“需原文”骨架。占位词和已选图表链接先由本地确定性整理，只有仍存在结构或格式问题时才调用模型修复一次；仍有问题则本次生成失败，不写入残缺结果。同一篇笔记的规划、写作和修复共用一个模型客户端连接；同次运行中重新生成未变化的 PDF 时会复用正文提取结果。

笔记文件默认直接使用论文标题，例如 `Auto-Encoding Variational Bayes.md`。Windows 文件名中的非法字符会替换为连字符；只有论文标题与已有文件冲突时才追加 Zotero key。图片仍位于稳定的 `images/<安全 citekey>-<Zotero key>/`。程序根据 frontmatter 中的 `zotero_key` 定位已有笔记，因此用户可以在输出目录及其子目录中自由改名或移动笔记，重新生成不会把名称改回。若同一 Zotero key 对应多份笔记，程序会报告冲突，不会任选一份覆盖。

重新生成时，Markdown 和图片通过暂存、切换与回滚作为一个整体提交，避免新笔记与旧图片混用。任何图片缺失或提交失败都会撤销本次写入。

## 模板

顶部“模板”按钮使用系统默认编辑器打开当前模板。模板不存在时，程序会自动创建默认模板。

支持以下占位符：

```text
{{zotero:title}}       {{zotero:authors}}     {{zotero:year}}
{{zotero:doi}}         {{zotero:url}}         {{zotero:zotero_key}}
{{zotero:tags}}        {{zotero:pdf}}         {{zotero:item_type}}
{{zotero:note_file}}   {{zotero:llm}}
```

## 文件与资产位置

| 内容 | 位置 |
|---|---|
| 本地配置 | 源码目录或 exe 同目录的 `config.json` |
| 默认模板 | 源码目录或 exe 同目录的 `template.md` |
| 笔记 | `notes_path/<论文标题>.md`；同名冲突时追加 Zotero key，也可由用户改名或移入子目录 |
| 图片 | `notes_path/images/<safe-citekey>-<zotero-key>/` |
| 主题与图标 | `theme.json`、`icon.ico`；打包时内置，同目录文件可覆盖 |
| Obsidian Vault 注册信息 | `%APPDATA%\obsidian\obsidian.json`；仅在点击“自动接入”后读取 |
| Zotero 数据源 | `http://127.0.0.1:23119/api/` |
| LLM | 设置中的 `llm_base_url` |

界面使用 Windows 自带的 `Microsoft YaHei UI`，不需要额外下载或在 exe 中分发字体文件。

## 当前架构

```mermaid
%%{init: {"theme": "base", "themeVariables": {"fontFamily": "Microsoft YaHei UI, sans-serif"}}}%%
flowchart TB
    ZOTERO["Zotero 7 本地 API"] -->|"分页读取"| ZCLIENT["zotero_client.py<br/>元数据与附件解析"]
    ZCLIENT -->|"文献列表"| APP["gui/app.py<br/>搜索、筛选与任务调度"]
    APP -->|"单篇 / 批量任务"| WORKERS["工作线程<br/>最多并发 3 篇"]
    WORKERS --> GENERATOR["note_generator.py<br/>证据提取、写作与校验"]
    GENERATOR -->|"已校验内容 + 临时图表"| WRITER["obsidian_writer.py<br/>定位、合并与事务提交"]
    WRITER -->|"原子提交 / 完整回滚"| NOTES["notes_path<br/>Markdown + images/"]

    ENTRY["main.py<br/>程序入口"] --> APP
    SETTINGS["gui/settings_view.py<br/>六项用户设置"] --> APP
    VISUAL["gui/design.py + gui/icons.py<br/>视觉系统"] --> APP
    AUTOCONNECT["自动接入按钮"] --> DISCOVERY["discovery/core.py<br/>Provider 契约与结果聚合"]
    DISCOVERY --> ZPROVIDER["discovery/zotero.py<br/>Zotero API 探测"]
    DISCOVERY --> OPROVIDER["discovery/obsidian.py<br/>Obsidian Vault 发现"]
    OPROVIDER --> OBSREG["obsidian.json"]
    DISCOVERY --> VAULTUI["gui/vault_selection.py<br/>多 Vault 选择"]
    VAULTUI --> APP

    CFGFILE["config.json"] <--> CONFIG["config.py<br/>迁移与原子保存"]
    CONFIG -->|"读取 / 保存"| APP
    THEME["theme.json + icon.ico"] --> VISUAL

    PDF["PDF 正文与图表"] --> GENERATOR
    TEMPLATE["template.md"] -->|"渲染结构"| GENERATOR
    GENERATOR <-->|"规划、写作、修复"| LLM["OpenAI 兼容接口"]

    classDef source fill:#E8F5E9,stroke:#4F8A66,color:#173D2A,stroke-width:1px;
    classDef ui fill:#F2F8F4,stroke:#74A487,color:#173D2A,stroke-width:1px;
    classDef core fill:#DDF1E4,stroke:#2F7650,color:#123622,stroke-width:1.5px;
    classDef storage fill:#F7FAF8,stroke:#8AA697,color:#263A30,stroke-width:1px;

    class ZOTERO,PDF,LLM source;
    class ENTRY,APP,SETTINGS,VISUAL,WORKERS,AUTOCONNECT,VAULTUI ui;
    class ZCLIENT,GENERATOR,WRITER,CONFIG,DISCOVERY,ZPROVIDER,OPROVIDER core;
    class CFGFILE,THEME,TEMPLATE,NOTES,OBSREG storage;
```

界面层只负责交互和任务编排；发现层通过统一 provider 契约隔离 Zotero 探测与 Obsidian 注册格式，新增发现来源时只需实现并注册 provider。核心服务分别处理配置、Zotero、生成与写入。生成内容必须通过校验后才交给写入层，Markdown 与图片作为同一事务提交。

| 模块 | 职责 |
|---|---|
| `main.py` | GUI 入口 |
| `config.py` | 六项用户设置、一项界面状态、旧配置迁移与原子保存 |
| `zotero_client.py` | Zotero 分页读取、元数据标准化与 PDF 路径解析 |
| `note_generator.py` | PDF/图表提取、模型调用、校验与模板渲染 |
| `obsidian_writer.py` | 笔记定位、手写区保留与整体事务提交 |
| `discovery/` | 自动发现契约、聚合器及 Zotero/Obsidian providers |
| `gui/app.py` | 主界面、筛选、单篇和批量任务 |
| `gui/settings_view.py` | 六项用户设置编辑 |
| `gui/vault_selection.py` | 多个 Obsidian Vault 的专用选择窗口 |
| `gui/design.py` | 颜色、字体、层级和状态样式 |
| `gui/icons.py` | 轻量界面图标 |
| `tests/` | 自动回归测试 |
| `ZotNotes.spec` | 单文件 Windows 打包配置 |

刷新在工作线程中分页读取 Zotero，同时递归扫描输出目录中的 Markdown；搜索和四种视图仅在本地改变显示。自动发现同样在工作线程执行，但只由“自动接入”按钮触发，结果经 UI 队列回到主线程；多 Vault 的选择和配置保存都发生在用户确认之后。设置、刷新、发现与生成不会同时执行状态性操作。

### 自动接入设计约束

自动接入只维护以下必要不变量，不增加配置项、管理页面或通用“安全框架”：

| 环节 | 当前规则 |
|---|---|
| Vault 注册数据 | 只接受存在的绝对目录；规范化后去重；注册文件的编码或 JSON 错误作为 Obsidian 发现结果显示，不影响 Zotero 探测 |
| Zotero 探测 | 本地 API 必须返回 HTTP 200 和 JSON 列表，空列表也表示连接可用 |
| 配置提交 | 先原子保存新配置，成功后再切换内存配置与 writer；失败时保持原连接并显示原因 |
| UI 任务队列 | 单个回调异常后仍继续轮询，后续刷新或生成结果不会滞留 |
| 多 Vault 选择 | 窗口使用独立行号标识候选，同名或重复 provider identity 不会串选 |
| 窗口尺寸 | 主窗口和 Vault 选择器根据逻辑屏幕尺寸收缩，常见 125% 缩放小屏仍能访问底部操作栏 |

实现中没有引入 UNC 探测线程、目录写权限预检、全局 `except Exception` 或高级设置；这些机制会增加状态与代码量，却不属于当前功能边界。

## 源码运行与测试

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

运行完整测试：

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -p no:cacheprovider
```

## Windows 打包

请在只安装本项目依赖的隔离虚拟环境中打包，避免 Anaconda 等全局环境中的 PyQt/PySide 包被 PyInstaller 一并收集：

```powershell
py -m venv .venv-build
.\.venv-build\Scripts\Activate.ps1
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m PyInstaller --clean --noconfirm ZotNotes.spec
```

产物为 `dist/ZotNotes.exe`。

## 常见问题

- 刷新失败：确认 Zotero 已启动并允许本机其他程序通信。
- 自动接入找不到 Obsidian：先在 Obsidian 中打开过目标 Vault，并确认该目录仍然存在；也可以继续在设置中手动选择输出文件夹。
- 检测到多个 Obsidian Vault：在选择窗口中根据名称和完整路径选定一个；取消不会改变现有配置。
- 搜不到无 PDF 文献：切换为“全部”。
- 显示“需原文”：PDF 可能是扫描件或附件路径无效；补充可提取文本的 PDF 后重新生成。
- 生成失败：查看界面底部信息，确认模型地址、API Key 和网络后重试。
- 移动笔记后提示重复：输出目录及其子目录中存在相同 `zotero_key` 的多份 Markdown，需要人工只保留正确的一份。

## 许可证

本项目采用 MIT License，见 `LICENSE`。
