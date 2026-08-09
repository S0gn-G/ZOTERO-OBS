查看的是当前 `main` 最新提交 `0ec39b8`。结论是：**上一轮指出的大部分问题已经真正修掉，但底层可靠性还没有完全闭环。** 我重新做了静态审查，并针对文件事务和图表几何做了隔离模拟。目前仍能确认 **2 个 P0、3 个 P1**。

先说修好的部分。这一版新的唯一命名 `<safe citekey>-<zotero key>` 确实解决了上一版的 sanitize 碰撞；Windows `CON/NUL/COM1` 等保留名也处理了。当前：

```text
A&B + K1 → A_B-K1
A B + K2 → A_B-K2
A/B + K3 → A_B-K3

CON → _CON
../../../etc/passwd → etc_passwd
```

`lint_note()`、LLM prompt、图片目录和 `note_file` 也基本统一到了新的 stem。

但是下面这些问题仍然存在。

### P0-1：“事务式导入”仍然不是“笔记 + 图片”的整体事务

当前 `_run_generate()` 的顺序仍然是：

```text
generate_note
    ↓
import_images        ← 图片正式提交
    ↓
write_note_preserving ← Markdown 正式提交
```

`import_images()` 自己现在确实做得比上一版好：先复制进 `.tmp`，全部成功后再替换正式图片目录；图片复制中途失败已经不会污染旧图片。

但问题在于：**图片事务已经 commit 以后，Markdown 写入仍然可能失败。**

我按当前实现做了隔离故障注入：

```text
旧 Markdown = OLD
旧 fig.png = OLDIMG

新图片 import_images 成功
→ fig.png = NEWIMG

随后模拟 write_note_preserving 抛 OSError
```

最终实际状态：

```text
Markdown = OLD
fig.png   = NEWIMG
生成结果  = 失败
```

也就是说，上一次指出的：

> 旧 Markdown + 新图片

仍然可以出现，只是触发条件从“第二张图复制失败”变成了“图片提交成功后 Markdown 提交失败”。

现有测试只覆盖了“图片事务内部失败时旧图片不变”和“图片事务成功替换”，并没有覆盖“图片成功 + 笔记失败”这个跨资源事务。

建议不要继续让 GUI 自己串：

```python
import_images()
write_note()
```

而是在 `ObsidianWriter` 内建立一个统一的：

```python
commit_generation(...)
```

更稳妥的结构甚至是版本化图片目录：

```text
images/<stem>/<generation-id>/
```

先完整写新图片，再生成引用这个 generation 的临时 Markdown，最后只用一次 `os.replace()` 原子切换 Markdown。旧图片版本稍后清理。这样 Markdown 永远只会指向一套完整存在的图片。

---

### P0-2：所谓“目标文件归属检查”仍然会覆盖不属于当前论文的文件

这一版增加了：

```python
owner = self._zotero_key_of(target)

if owner is None or owner == current_key:
    old_path = target
```

初衷是正确的。

但这里实际上有两个问题。

第一，`owner is None` 被认为可以安全覆盖。因此如果用户恰好有一个人工创建的：

```text
A_B-K1.md
```

但没有 Zotero frontmatter，程序会直接覆盖它。

第二，更隐蔽：

```text
target 已存在
owner = OTHER
当前 zotero_key = K1
```

代码虽然发现 owner 不匹配，但随后：

```python
old_path = self._find_note_by_key("K1")
```

如果找不到 K1 的其他旧文件，最后仍会调用：

```python
self.write_note(... K1 ...)
```

而 `write_note()` 算出来的还是**同一个被 OTHER 占用的 target**。

我进行了实际模拟：

```text
cite-K1.md:
    zotero_key: OTHER
    OTHER DATA
```

执行：

```text
write_note_preserving(... zotero_key=K1)
```

结果：

```text
cite-K1.md:
    zotero_key: K1
    K1 DATA
```

`OTHER DATA` 被覆盖。

所以当前“归属检查”实际上还是 **fail-open**。

这里应该明确：

```python
if target.exists():
    owner = _zotero_key_of(target)

    if owner != current_zotero_key:
        # 不允许覆盖
        raise NotePathConflict(...)
```

包括 `owner is None` 也应该认为是未知文件，而不是默认属于自己。

---

### P1-1：Table → Figure 同页排列会导致 Figure 被确定性跳过

这是这一版图表裁剪新引入的主要逻辑问题。

现在 Table 使用：

```python
y0 = caption 底部
y1 = 下一个 caption 顶部
```

Table 提取后：

```python
prev_bottom = y1
```

而 Figure 使用：

```python
figure_bottom = 当前 Figure caption 顶部
figure_top = max(prev_bottom, ...)
```

考虑非常正常的论文布局：

```text
Table 1 caption
[ Table 1 ]

正文

[ Figure 1 ]
Figure 1 caption
```

假设：

```text
Table caption:   y=180~190
Figure caption:  y=420~430
```

我直接按当前 `_clip_region()` 顺序模拟：

```text
Table:
    crop = 194 ~ 416
    height = 222
    prev_bottom = 416

Figure:
    y1 = 420 - 4 = 416
    y0 = max(prev_bottom=416, ...)
       = 416

    height = 0
```

结果：

```text
Table  → 成功提取
Figure → 因 height < MIN_FIG_H 被跳过
```

也就是说，**只要同一页里 Table caption 出现在 Figure caption 前面，Table 的裁剪很可能把 Figure 本体一起吞进去，然后真正的 Figure 又因为 `prev_bottom` 被推进到 caption 前而无法提取。**

目前 `tests/test_figures.py` 都是在单独测试一个 caption 的 `_clip_region()`，没有做：

```text
Table → Figure
Figure → Table
Table → Figure → Figure
```

这种顺序集成测试，所以 58 项测试也没有发现它。

---

### P1-2：Table 提取仍然严重“过裁”

当前 Table 如果后面没有其他 Figure/Table caption：

```python
y1 = page_h - MARGIN_BOTTOM
```

也就是：

> 从 Table caption 下方一直截到整页底部。

例如模拟：

```text
Table caption bottom = 112
真正 table bottom   = 250
页面 bottom          = 842
```

当前区域：

```text
116 ~ 802
```

也就是说，表格后 **552 pt 的正文、公式、下一幅图等都会一起进入所谓的 table 图片**。

而 `_image_rects()` 目前也没有真正解决这个问题：

```python
y1 = max(y1, r.y1)
```

由于默认 `y1` 已经通常非常大，如果真实表格图片在：

```text
200 ~ 300
```

`max(802, 300)` 还是 802。

所以所谓“向下探到图片”实际上不会帮助缩小 Table 边界。

这里建议不要继续用 caption-to-next-caption 作为 Table 主算法。当前 PyMuPDF 版本可以考虑把表格检测作为候选 bbox 来源，然后用 caption 与最近 table bbox 做关联；如果检测不到，再使用保守高度/文本块间距兜底。

---

### P1-3：用户关闭软件时生成线程可能被直接杀死

单篇和批量外层线程当前仍然都是：

```python
threading.Thread(..., daemon=True)
```

而目前没有看到针对窗口关闭的生成任务协调机制。

这意味着用户如果在：

```text
“生成中…”
```

直接关闭程序，后台 daemon thread 不保证把当前事务执行完成。

特别是当前图片目录 commit 是：

```text
dest → dest.old
tmp  → dest
删除 old
```

如果进程恰好在：

```text
dest → dest.old
```

之后退出：

```text
images/<stem>/       不存在
images/<stem>.old/   存在
```

旧 Markdown 此时会暂时失去原图片路径。

因此建议增加关闭协议：

```text
WM_DELETE_WINDOW
       ↓
_busy ?
 ├─ 否 → 正常退出
 └─ 是 → 禁止立即退出 / 明确取消
```

至少保证当前文件 commit 区间不能被窗口关闭打断。

---

还有几个次一级问题。

第一，LLM prompt 中路径变量仍有一个明显不一致。前面已经改成：

```text
images/<image_dir>/
```

但后面给模型的具体插入格式仍然写成：

```markdown
![图注说明](images/<note_key>/<文件名>)
```

虽然 user message 又提供了真实 image dir，模型多数时候可能能选对，但 system prompt 本身是矛盾的。应该统一成 `<image_dir>`。

第二，`llm_profile` 号称可以改成 NLP、医学等领域，但 `WRITE_SYSTEM_TMPL` 的“与我的研究的关系”仍然硬编码：

```text
与 SR / ReID 领域的交叉点
```

所以当前 profile 还没有真正做到通用化。

第三，Table caption 只支持阿拉伯数字：

```text
Table 1
Table 2
```

不支持论文中很常见的：

```text
TABLE I
TABLE II
```

第四，新文件命名迁移还有一个轻微语义问题。生成正文的 frontmatter：

```text
note_file = <canonical stem>.md
```

但如果用户之前把笔记改名为 `my-paper.md`，`write_note_preserving()` 会继续写回这个实际旧路径。 因此：

```yaml
note_file: "Wang2026-K1.md"
```

可能并不是当前真实文件名。若这个字段以后参与链接或索引，会造成问题。

### 对这一版的整体判断

上一轮的问题修复情况大致可以概括为：

| 上一轮问题                      | 当前状态              |
| -------------------------- | ----------------- |
| citekey sanitize 碰撞        | **已修**            |
| Windows 保留名                | **已修**            |
| canonical image/lint 路径不一致 | **已修**            |
| Figure caption gap         | **基本修复**          |
| 图片复制中途失败污染旧图片              | **已修**            |
| Markdown + images 整体事务     | **仍未修完**          |
| Table 提取                   | **修了一半，并产生混排新问题** |

因此我目前不会再建议大规模重构。核心分层已经比较稳定，**下一版只需要做一轮“可靠性交付 + 图表几何”集中修复**：

1. 把 Markdown 与 images 合并为真正的 generation transaction。
2. 目标文件 owner 不匹配或未知时 fail-closed，绝不覆盖。
3. 重构 `_clip_region`，至少加入 `Table→Figure` 顺序测试，避免 `prev_bottom` 吞掉后续 Figure。
4. Table 用真正的 table bbox 来确定底边，不再默认截到 next caption/page bottom。
5. 增加正常关闭/生成中退出的保护。
6. 补 `prompt image_dir`、Roman numeral Table、重复 `zotero_key` 检测等 P2 项。

另外，当前提交没有 GitHub Actions 运行记录；仓库声称的“58 项全绿”我无法通过远程 CI 独立确认。隔离环境又无法 DNS 访问 GitHub，且缺少仓库固定的 `customtkinter`/精确 PyMuPDF 版本，所以这次我没有伪称跑过完整 58 项测试；我读取的是 `0ec39b8` 的精确源码，并对上述文件事务和裁剪算法做了针对性的执行模拟。执行模拟已经稳定复现了 **“笔记失败但图片已变”**、**“归属不符文件仍被覆盖”** 和 **“Table→Figure 后 Figure 高度变 0”** 三个问题。

