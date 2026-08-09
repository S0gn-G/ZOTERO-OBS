# ZotNotes — Zotero → Obsidian 论文笔记

ZotNotes 从正在运行的 Zotero 读取文献与 PDF，用 OpenAI 兼容模型生成结构化 Markdown 笔记，并把笔记和图表整体提交到指定的 Obsidian 笔记目录。

- 源码仓库：<https://github.com/westriver-moon/ZOTERO-OBS>
- Windows 成品：<https://github.com/westriver-moon/ZOTERO-OBS/releases>
- 当前分支：`main`

## 使用条件

1. Zotero 7 正在运行，并允许本机其他程序通信。
2. 一个用于保存论文笔记的文件夹；可以是 Obsidian vault 内的任意目录。
3. OpenAI 兼容接口的 Base URL、API Key 和模型名。
4. Better BibTeX 可选；没有 citekey 时程序会生成稳定的兜底名称。

## 使用

1. 打开“设置”，选择最终的笔记输出文件夹，填写模型连接信息。
2. 刷新 Zotero 文献。
3. 用搜索框或“含 PDF / 全部 / 未生成 / 需处理”筛选。
4. 单篇生成，或勾选当前列表后批量生成。已经生成的文献可直接重新生成，手写区会保留。

设置只保留六项：`notes_path`、`template_path`、`llm_base_url`、`llm_api_key`、`llm_model`、`llm_profile`。Zotero 使用标准本地地址 `http://127.0.0.1:23119/api/`，PDF 正文在存在时始终读取。

## 工作方式

```text
Zotero 本地 API
  → 文献、附件、citekey
  → PDF 正文与图表提取
  → LLM 规划、写作、校验与一次修复
  → Markdown + 图片事务提交
  → Obsidian 笔记目录
```

证据不足时不会让模型猜测：没有 PDF 正文但有摘要时标为“仅摘要”；正文和摘要都没有时生成“需原文”骨架。生成后的全部校验问题都必须清零，否则本次生成失败，不会写入残缺结果。

笔记文件采用 `<安全 citekey>-<Zotero key>.md`，图片位于 `images/<安全 citekey>-<Zotero key>/`。程序按 frontmatter 中的 `zotero_key` 识别笔记，因此在 Obsidian 中改名或移动到输出目录的子文件夹后仍能定位。若同一 Zotero key 出现两份笔记，会明确报冲突而不是任选一份覆盖。

重新生成会保留 `## 我的笔记` 与 `## 疑问` 两个手写区。Markdown 与图片通过暂存、切换和回滚作为一个整体提交，避免出现新笔记配旧图片或旧笔记配新图片。

## 资产与运行时地址

| 资产 | 地址 |
|---|---|
| 本地配置 | 源码目录或 `ZotNotes.exe` 同目录的 `config.json` |
| 默认模板 | 源码目录或 exe 同目录的 `template.md`；设置中可指向其他文件 |
| 笔记 | `notes_path/<safe-citekey>-<zotero-key>.md`，也能继续留在其子目录 |
| 图片 | `notes_path/images/<safe-citekey>-<zotero-key>/` |
| 主题与图标 | `theme.json`、`icon.ico`；打包时内置，exe 同目录文件可覆盖 |
| Zotero 数据源 | `http://127.0.0.1:23119/api/` |
| LLM | 设置中的 `llm_base_url` |

界面字体优先使用免费开源的 Noto Sans SC；系统没有该字体时由 Tk 使用系统字体替代。字体本身没有打进仓库或 exe。

## 源码运行与测试

```powershell
python -m pip install -r requirements.txt
python main.py
python -m pip install -r requirements-dev.txt
python -m pytest -p no:cacheprovider
```

打包：

```powershell
python -m PyInstaller --clean --noconfirm ZotNotes.spec
```

产物为 `dist/ZotNotes.exe`。`config.json` 含明文 API Key，已被 `.gitignore` 排除，不要将个人配置上传或分享。

## 项目结构

```text
main.py                 GUI 入口
config.py               六项配置、旧配置迁移、原子保存
zotero_client.py        Zotero 本地 API、分页、PDF 附件解析
note_generator.py       PDF/图表提取与 LLM 生成管道
obsidian_writer.py      笔记定位、手写区保留、整体事务提交
gui/app.py              主界面、筛选、单篇与批量任务
gui/settings_view.py    精简设置页
gui/design.py           统一颜色、字体、层级与状态样式
gui/icons.py            缓存的轻量图标
tests/                  自动回归测试
ZotNotes.spec           单文件 Windows 打包配置
```
