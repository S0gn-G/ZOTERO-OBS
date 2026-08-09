结论：当前设计主干是合理的，模块划分也比较清楚，之前修复计划中提到的分页、LLM 开关、YAML 转义、`needs_source` 重试、重复扫描等问题已经落实到当前代码。 但当前版本仍有几处会影响实际使用的数据一致性问题。其中有 4 项建议在继续扩展功能前先修掉。

### 一、静态检查结果

| 优先级    | 问题                                        | 判断      |
| ------ | ----------------------------------------- | ------- |
| **P0** | citekey 直接作为文件/目录路径                       | 必须修     |
| **P0** | 笔记写入与图片导入没有事务性，且图片复制失败被吞掉                 | 必须修     |
| **P0** | 改名后的笔记能被识别，却不能被正确覆盖                       | 必须修     |
| **P1** | 首次启动会持久化开发者本机 Vault 路径                    | 明显错误    |
| **P1** | Zotero PDF 附件定位是近似 (O(N^2))               | 大库性能问题  |
| **P1** | 批量生成期间设置可以改变，导致配置“分裂”                     | 并发设计问题  |
| **P1** | 图表裁剪算法很容易截掉宽图                             | 算法设计不足  |
| **P2** | “有摘要”就被视作足以生成完整深度笔记                       | 质量语义不严谨 |
| **P2** | LLM 兼容层、plan schema、lint fail-close 仍不够严格 | 可维护性问题  |
| **P2** | 当前测试本质是人工 smoke test，构建依赖也没有锁版本           | 工程化不足   |

最严重的是前四项。

**1. citekey 没有经过任何文件名规范化。**

现在 `citationKey` 最终直接进入：

`<notes_dir>/<citationKey>.md`

以及：

`images/<citationKey>/`

甚至还进入临时目录前缀。`note_path()` 只是简单 `os.path.join()`，没有过滤 `/`、`\`、`..`、Windows 保留字符，也没有做最终路径 confinement 检查。 GUI 又直接把 Zotero/Better BibTeX 给出的 `citationKey` 传入这一链路。

这不应该依赖“正常 citekey 一般不会这样写”。文件系统边界应该由程序自己保证。

**2. “生成成功”目前并不等价于笔记真正完整落盘。**

当前顺序是：

`generate_note → write_note_preserving → import_images → cleanup`

而 `import_images()` 对单张图片复制时的 `OSError` 直接 `continue`，不会告诉调用者失败。 `_run_generate()` 又只要整个函数没抛异常就返回 `"OK"`。

因此会出现这种真实状态：

> Markdown 已经写入，正文引用 `images/.../fig_x.png` → 图片实际没写进去 → GUI 仍显示“已生成”。

这与当前架构图里表达的“失败隔离/成功交付”并不完全一致。

正确做法应是“暂存 → 完整校验 → 原子提交”，至少也应让 `import_images()` 返回 expected/written 差异并把缺图作为失败。

**3. “笔记改名也能识别”与“重新生成保留手写内容”目前实际上不能同时成立。**

`scan_states()` 的确通过 frontmatter 中的 `zotero_key` 识别笔记，因此改名后仍会显示“已生成”。 README 也明确宣称这一点，并同时承诺重新生成保留“我的笔记/疑问”。

但真正覆盖时，`write_note_preserving()` 并不会根据 `zotero_key` 找原文件，而是重新计算：

`<citationKey>.md`

然后只检查这个规范路径是否存在。

所以只要用户在 Obsidian 中改过文件名，重新生成就可能产生第二份 Markdown；旧文件里的手写内容也不会合并进新文件。

这里应该把扫描结果改成：

`zotero_key -> actual_note_path`

而不是仅仅得到一个 key 集合。

**4. 首次启动配置存在明显错误。**

`config.example.json` 正确地把 `vault_path` 设成空字符串。

但真正的 `DEFAULT_CONFIG` 却写成：

`C:\Users\pbrii\Desktop\论文笔记\REID`

而最新提交又增加了“首次启动自动把 DEFAULT_CONFIG 写进 config.json”。

因此现在一个新用户第一次启动，实际上会自动获得开发者个人机器路径。这应该直接改为 `""`，随后在 UI 明确要求用户选择 Vault。

---

### 二、虚拟机执行模拟

因为隔离容器无法直接 DNS 访问 GitHub，我没有使用可能过期的本地副本，而是通过 GitHub connector 读取当前 `main@9e1728b`，将关键逻辑放入隔离目录执行模拟。没有修改仓库。

| 模拟项目                  | 结果                              |
| --------------------- | ------------------------------- |
| 核心模块 `py_compile`     | **通过**，未发现基础语法错误                |
| Mock Zotero 55 篇、分页拉取 | **通过**                          |
| Mock PDF 附件关联和路径解析    | **通过**                          |
| 500 → 1500 条规模附件定位    | 约 **0.020s → 0.178s，9×**        |
| 空 `vault_path` 写笔记    | `FileNotFoundError`             |
| citekey=`../escape`   | **实际越出 LiteratureNotes 目录**     |
| 模拟图片 `copy2()` 失败     | 函数仍返回 **成功**，Markdown 已存在而图片不存在 |
| 模拟 Markdown 写入阶段异常    | 图表临时目录可能残留                      |
| 已改名笔记重新生成             | **产生第二份文件，旧手写内容未带入**            |
| 475pt 宽模拟论文图          | 当前算法只截取约 **300pt**，右侧被裁掉        |

其中附件关联性能问题直接来自 `_find_pdf()`：每处理一篇论文，就重新遍历所有 Zotero item 查其 PDF。 3 倍规模出现约 9 倍耗时，符合二次复杂度特征。

这里非常容易优化。拉完 `items` 后先做一次：

`parentItem -> PDF attachment`

索引，之后每篇论文 (O(1)) 查附件即可，整个解析阶段从近似 (O(N^2)) 下降到 (O(N))。

### 三、图表提取设计需要重做一部分

当前实现并不是真的“识别图表边界”，而是：

找到 `Figure N / Fig. N` 图注 → 根据图注位置向上截最多 320pt → 横向范围主要根据图注文本 bbox 决定。

这有三个明显问题。

第一，图注通常比图本身窄，因此“图注宽度 ≠ 图片宽度”；我的模拟已经实际截掉了宽图右侧。

第二，只识别 `Figure/Fig.`，并不识别 `Table N`。README 当前称其为“图表提取”，这个说法比实际能力更强。

第三，`_page_captions()` 对一个文本 block 只读取第一行 spans，多行图注不够稳健。

短期可以直接将横向 clip 放宽到正文页面宽度；长期更适合利用 PyMuPDF 的 image/drawing/text bbox 联合确定候选区域，而不是让 caption bbox 决定 figure bbox。

### 四、LLM 管道框架合理，但“证据等级”目前太粗

当前 fail-closed 的条件实际上是：

```text
pdf_text 非空 OR abstract 非空
```

只要 Zotero 中存在一个 abstract，即使 PDF 根本没有读到，也会继续执行 plan → write → lint，并最终可能被标为 `ok`。

对于“深度论文阅读软件”，我建议把现在二值的“有证据/无证据”改成至少三级：

`fulltext` / `abstract_only` / `none`

`abstract_only` 可以生成摘要级笔记，但不应该和真正阅读了正文、实验、方法章节的笔记使用同一个 `ok` 状态。

另外还有两个较隐蔽的问题。`llm_plan()` 只验证输出“是 dict”，并不验证 `paper_type`、`figures_to_reference`、`mechanism_flow` 等字段是否合法；同时对所谓所有“OpenAI 兼容接口”直接发送 `response_format=json_object`，兼容性假设比较强。 修复轮 `llm_fix()` 只拿到原草稿和 issue，没有再次拿到原始 evidence bundle，这也削弱了修复阶段的事实约束。

还有一点属于产品定位：PLAN/WRITE prompt 目前被硬编码成“SR 与 ReID 领域资深研究员”。 如果这个软件只服务你自己的 SR/ReID 阅读流程，这完全合理；如果准备做成通用 Zotero→Obsidian 工具，则应该把领域 profile 从生成管道中抽离。

### 五、并发和关闭过程还有一个设计隐患

批量生成时 `writer` 在任务开始时根据当前 Vault 创建一次，但 `_run_generate()` 内部读取的是共享的 `self.cfg`。 同时设置按钮在 `_busy` 时没有被锁死，设置窗口保存后会直接替换 `self.cfg` 和 `self.writer`。

因此理论上可以出现：

> 批量任务开始于旧 Vault → 用户中途修改设置 → 后续 LLM 调用读取新配置 → 文件仍由旧 writer 写入旧 Vault。

解决方式很简单：点击生成时先 `deepcopy/freeze cfg`，整个 batch 都只使用这一份不可变快照，同时 busy 时禁用设置修改。

### 六、测试体系目前不足以承担后续重构

`test_core.py` 和 `test_pipeline.py` 现在主要是打印结果，没有 assertion，也强依赖真实 Zotero/PDF/API。  因此它们更接近手动冒烟脚本，不是真正的自动回归测试。

此外 `requirements.txt` 全部没有固定版本，也不包含 README 构建流程中直接使用的 PyInstaller。 README 却描述了在新 venv 中装完 `requirements.txt` 后直接运行 `python -m PyInstaller`。 建议至少拆成 runtime/dev-build 两组依赖并固定可重复构建版本。

---

综合来看，**我不建议现在重构整个项目**。目前的分层——`ZoteroClient → NoteGenerator → ObsidianWriter → GUI`——是成立的，UI 工作线程通过队列回主线程的思路也正确。 当前问题主要集中在“边界和事务”而不是整体架构错误。

建议修改顺序是：先解决 **citekey 路径约束 → 笔记/图片原子交付 → 改名笔记实际路径索引 → 首启 Vault 配置**；然后处理 **PDF 附件 O(N²) → 批量配置快照 → 图表提取**；最后再做 **证据等级、LLM schema/provider abstraction、pytest 和可重复构建**。

如果这四个最高优先级问题不修，我会认为当前版本适合继续开发和个人试用，但还不适合作为“可靠的论文笔记工具”正式发布。
