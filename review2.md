检查的是当前 `main` 最新提交 `5158de0`。这一版相比上一版改善明显：上次指出的大部分核心问题已经修复，但仍然有几个需要处理的问题，其中我认为有 **2 个 P0、3 个 P1**。最新提交确实加入了路径安全、改名笔记定位、证据分级、配置快照和测试工程化等修复。

### 结论

| 优先级    | 当前问题                                           | 结论   |
| ------ | ---------------------------------------------- | ---- |
| **P0** | `safe_citekey()` 存在确定性碰撞，会导致不同论文覆盖同一笔记         | 必须修  |
| **P0** | 所谓“原子交付”仍不原子；失败生成可以污染旧笔记的图片                    | 必须修  |
| **P1** | `lint_note()` 没有使用 sanitized citekey，与新路径机制不一致 | 应立即修 |
| **P1** | Table 提取方向错误；当前算法默认图表都在 caption 上方             | 应修   |
| **P1** | 高图 / 与 caption 有间隔的 Figure 仍会被截断               | 应修   |
| P2     | `note_file` frontmatter 与实际 sanitized 文件名可能不一致 | 建议修  |
| P2     | Windows 保留文件名尚未处理                              | 建议修  |
| P2     | 39 项测试没有覆盖上述碰撞、图表几何、事务失败路径                     | 补测试  |
| P2     | lint 修复后仍允许部分结构错误 fail-open                    | 建议收紧 |

其中前两个已经通过隔离模拟实际复现，不只是静态推测。

## 1. P0：新的 `safe_citekey()` 会产生文件名碰撞

这是当前最值得优先修的问题。

现在实现为：

```python
s = re.sub(r"[^A-Za-z0-9_.\-]", "_", s)
s = re.sub(r"\.{2,}", "_", s)
s = s.strip("._-") or fallback
return s[:80]
```

它解决了上一版的目录穿越，但没有解决“不同原始 citekey → 同一个安全 citekey”的问题。

我按当前代码实际模拟：

```text
A&B   -> A_B
A B   -> A_B
A/B   -> A_B

论文   -> note
测试   -> note
```

也就是说，三个不同的 Better BibTeX citekey 可能对应同一个 `A_B.md`；两个中文 citekey 甚至都会变成 `note.md`。

问题随后被 `write_note_preserving()` 放大。它首先判断 sanitized target 是否存在：

```python
target = self.note_path(citation_key)
old_path = target if os.path.exists(target) else None
```

只要路径存在，它没有验证这个文件的 `zotero_key` 是否属于当前论文。

我做了隔离模拟：

```text
论文 K1: citekey = "A&B"
论文 K2: citekey = "A B"
```

先生成 K1：

```text
A_B.md
zotero_key: K1
我的笔记: K1_PRIVATE
```

再生成 K2。

最终磁盘上仍然只有：

```text
A_B.md
```

但内容变成：

```text
zotero_key: K2

## 我的笔记

K1_PRIVATE
```

也就是说，**K2 覆盖了 K1，同时把 K1 的私人手写笔记错误继承给 K2。**

这已经是实际的数据完整性错误，不只是文件命名不美观。

建议不要让 `safe_citekey()` 单独承担唯一标识。最稳妥的是：

```text
<sanitized-citekey>-<zotero-key>.md
```

或者：

```text
<sanitized-citekey>-<hash(original-citekey)[:8]>.md
```

更推荐前者，因为 Zotero key 本来就是稳定唯一 ID。

同时 `write_note_preserving()` 在发现规范目标已经存在时，应先读 frontmatter：

```python
if target exists:
    if target.zotero_key != current_zotero_key:
        # 这是 collision，不允许覆盖
```

现有测试只验证了 traversal 和普通 sanitize，没有任何碰撞测试。

---

## 2. P0：“原子交付”实际上仍然不是原子的

这版做了一个正确改进：先复制图片，图片全部成功之后才写 Markdown：

```python
missing = writer.import_images(...)
if missing:
    return False
writer.write_note_preserving(...)
```

但是 `import_images()` 是直接往最终目录一个一个 `copy2()`：

```python
dst = images/<citekey>/<name>
shutil.copy2(src, dst)
```

失败时只返回 missing。

因此仍然存在：

```text
复制 fig_1 成功
复制 fig_2 失败
→ 本轮生成判失败
```

但 `fig_1` 已经永久写进正式目录。

更严重的是覆盖旧笔记时。

我模拟了：

```text
旧笔记：
images/cite/fig_1.png = OLD_IMAGE
```

本轮生成：

```text
fig_1.png = NEW_IMAGE   ← 成功覆盖
fig_2.png               ← 复制失败
```

实际结果：

```text
生成状态：失败
Markdown：仍然是旧版本
fig_1.png：已经变成 NEW_IMAGE
```

所以失败生成会产生：

> **旧 Markdown + 新图片**

这仍然是数据污染。

同理，Markdown 自身的写入：

```python
with open(old_path, "w") as f:
    f.write(merged)
```

也是直接覆盖，不是 atomic replace。

正确结构应该是：

```text
生成
 ↓
<tmp transaction dir>/
    note.md
    images/
 ↓
验证全部存在
 ↓
os.replace / rename
 ↓
正式目录
```

对于覆盖生成，还应保留旧 images，直到新的 Markdown 和全部图片都成功后再一次性切换。

所以当前 commit message 中“原子交付：笔记与图同时落盘才判成功”的方向正确，但实现还没达到真正的原子性。

---

## 3. P1：`lint_note()` 与新的 `safe_citekey()` 不一致

这是这次路径修复引入的新回归。

生成 prompt 已经正确使用：

```python
images/{safe_citekey(note_key)}/
```

实际图片目录同样使用：

```python
images/safe_citekey(citation_key)
```

但 `lint_note()` 仍然使用原始 `note_key`：

```python
wanted = {
    f"images/{note_key}/{f['name']}"
    for f in figures
}
```

并检查：

```python
f"images/{note_key}/{name}"
```

因此我模拟：

```text
原始 citekey:
Wang&Li,2022

safe:
Wang_Li_2022
```

LLM 按正确 prompt 输出：

```markdown
![图](images/Wang_Li_2022/fig_1_p1.png)
```

`lint_note()` 却实际返回：

```text
图表引用指向不存在的文件：
images/Wang_Li_2022/fig_1_p1.png

计划要求引用的图表未在正文中出现：
fig_1_p1.png
```

即：

> **正确路径被 lint 当成错误路径。**

而且它还会触发 `llm_fix()`。LLM 甚至有可能把正确的 safe 路径“修复”成错误的原始路径。

现有 `test_lint.py` 只测试 citekey=`"k"`，所以没有发现这一问题。

修复很简单：

```python
safe_key = safe_citekey(note_key)

wanted = {
    f"images/{safe_key}/{f['name']}"
    for f in figures
}
```

并新增测试：

```python
test_lint_uses_safe_citekey()
```

---

## 4. P1：新增 Table 支持，但裁剪方向是错的

这一版值得肯定的一点是图注识别从：

```text
Figure / Fig.
```

扩展到了：

```text
Figure / Fig.
Table / Tab.
```

并且支持多行 caption。

但是后续算法把 Figure 和 Table 完全使用同一种裁剪方式：

```python
y0 = ...
y1 = cap["y0"] - 4
```

即始终：

> **截 caption 上面的区域。**

这对 Figure 很常见，因为 Figure caption 通常在图下方。

但 Table 的 caption 很多论文放在表格上方。

我在虚拟环境生成了一张模拟 PDF：

```text
y=180    Table 1. Accuracy results
y=220
          ┌─────────────┐
          │ actual table│
          │             │
y=400     └─────────────┘
```

运行当前算法后实际得到的 clip：

```text
y = 55.0 ~ 163.1
```

实际表格：

```text
y = 220 ~ 400
```

所以提取结果**完全不包含表格**，截到的是 Table caption 上面的正文。

这一点应该按 `kind` 分开：

```text
Figure:
    优先向 caption 上方找

Table:
    优先向 caption 下方找
```

最好再结合 `page.find_tables()` / drawing bbox / text block geometry，而不是仅靠固定方向。

---

## 5. P1：高 Figure 仍然会截掉顶部

新版增加了 `_image_rects()`，这个方向也是正确的。

但条件是：

```python
if r.y1 >= cap["y0"] - 4:
    y0 = min(y0, r.y0)
```

这相当于只有：

> 图片底边几乎碰到 caption

才会利用图片 bbox 向上扩张。

实际论文中图和图注之间有几十 pt 间隔很正常。

我又构造了一张模拟 PDF：

```text
Figure:
y = 60 ~ 400

空隙:
400 ~ 490

caption:
Figure 1...
y ≈ 487
```

当前算法实际裁剪：

```text
y = 167.1 ~ 483.1
```

而真正 Figure 从：

```text
y = 60
```

开始。

因此约前 107 pt 被截掉。

根因就是这句：

```python
r.y1 >= cap["y0"] - 4
```

太严格。

至少应该允许合理 gap，例如：

```python
0 <= cap_y - image_bottom <= FIG_CAPTION_MAX_GAP
```

更好的做法仍然是根据邻近布局做 candidate matching。

---

## 6. P2：frontmatter 的 `note_file` 仍然可能是假的

`generate_note()` 仍然：

```python
note_file = note_key + ".md"
```

但真正保存使用：

```python
safe_citekey(citation_key) + ".md"
```

例如：

```text
citekey:
Wang&Li,2022
```

frontmatter：

```yaml
note_file: "Wang&Li,2022.md"
```

实际：

```text
Wang_Li_2022.md
```

虽然目前程序似乎没有依赖 `note_file` 回查文件，但这已经形成元数据不一致。

直接改成：

```python
note_file = safe_citekey(note_key) + ".md"
```

即可。

---

## 7. P2：Windows 保留设备名仍没处理

项目目标是 Windows 单文件 exe，因此这个边界有实际意义。

目前：

```python
safe_citekey("CON") == "CON"
safe_citekey("NUL") == "NUL"
```

但 Windows 明确保留 `CON / PRN / AUX / NUL / COM1…9 / LPT1…9`，即使加扩展名也仍然保留，例如 `NUL.txt`。([Microsoft Learn][1])

所以：

```text
CON.md
NUL.md
```

并不是有效的普通 Windows 文件名。

建议 sanitize 后再做一次：

```python
if stem.upper() in WINDOWS_RESERVED_NAMES:
    stem = "_" + stem
```

---

## 上一轮的问题修复情况

这里整体做得比上一版好很多。

“首启写死开发者 Vault”已经彻底改成空路径，同时 GUI 在生成前拦截空 Vault。

“改名笔记无法覆盖”也已经正确改为通过 frontmatter `zotero_key` 找实际文件，再写回原路径。 对应测试也已经存在。

Zotero 附件查找已经由每篇扫描整个库改成一次建立 `parentItem -> attachment` 索引，因此上一版近似 (O(N^2)) 的问题已经消失。

批量生成现在使用 `cfg = dict(self.cfg)` 快照，同时 busy 时禁用设置按钮，上一版配置分裂问题已经基本闭环。

“摘要也算完整正文”的问题已经改成 `fulltext / abstract_only / none` 三级状态，这是合理的。

LLM 计划增加 schema 基础校验、`response_format` 不支持时回退，并把 evidence bundle 再传给修复轮，也比上一版稳健。

依赖现在也已经固定版本，并拆出了 `requirements-dev.txt`。

### 最终判断

当前版本已经从上一版的“有明显数据边界漏洞”进步到了**主体设计基本可用，但仍有两个数据一致性漏洞需要先堵住**的状态。

我建议下一次提交只做一轮比较集中的修复，不再大改架构：

1. **重新设计 citekey 唯一映射**，解决 sanitize collision，并校验目标文件 `zotero_key`。
2. **真正做 transaction write**，图片先写临时目录，全部成功后一次性 replace，避免失败污染旧图片。
3. `lint_note()`、`note_file` 全部统一使用同一个 canonical safe key。
4. Figure/Table 分开做空间搜索，尤其 Table 改为优先向下。
5. 增加四类回归测试：`citekey collision`、`Windows reserved names`、`safe-key image lint`、`table-above-caption / tall-figure`。

这五项完成之后，我认为这个项目的底层可靠性才基本可以闭环，再继续优化论文精读质量会更合适。

[1]: https://learn.microsoft.com/zh-cn/windows/win32/FileIO/naming-a-file "文件命名、路径和命名空间 - Win32 apps | Microsoft Learn"
