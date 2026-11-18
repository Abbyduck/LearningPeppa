# Wiki Transcript 清洗试采集

## 第三季归档（2026-11-18）

第三季分类中的 52 个 Transcript 页面已采集，保存在 `output/wiki/season3/`。逐集结果为 `episodes/S03E01.json` 至 `S03E52.json`，逐集报告在 `reports/`，总报告为 `REPORT.md`，待检查原文在 `review_items.json`。

崩溃前落盘的 8 页保存在 `browser-capture.json`，续采 44 页保存在 `browser-capture-part2.json`。两份原始分卷独立保留，构建时按 URL 逐项核对。编号证据在 `numbering-source.html`，与第三季分类的实际链接匹配。空剧本和过短页面仍生成带标记的 JSON，不补写台词。

离线重建：`python build_wiki_season3.py`。`previous_seasons_baseline.json` 保存前两季文件的采集前哈希，构建时检查它们未被更改。

## 第二季归档（2026-11-17）

第二季分类中的 53 个 Transcript 页面全部采集：52 集常规剧集和一个 E53+E54 圣诞合篇特别篇。结果位于 `output/wiki/season2/`，逐集 JSON 在 `episodes/`，总报告在 `REPORT.md`，异常原文在 `review_items.json`。特别篇保留一个来源页面对应一个 JSON，ID 为 `S02E53-E54`，不推测拆分边界。

第二季原始浏览器 DOM 保存在 `browser-capture.json` 和分集 `raw/` 中。编号证据在 `numbering-source.html`，来自此前保存的 Wiki Series 2 导航表，并与本次第二季分类的 53 个实际链接逐项匹配。

离线重建命令：`python build_wiki_season2.py`。新增规则处理星号声音标记、带短横线的声音事件、括号场景标题、台词前的舞台说明，以及更多页尾目录和 stub 组件。未知内容继续保留，不修正原文语法、不猜测说话人，也不补写缺失台词。报告单独列出过短正文与来源提示。第一季结果目录有采集前哈希基线，重建时验证其未改变。

## 第一季完整归档（2026-11-17）

第一季分类的 52 个 Transcript URL 已全部覆盖：新增采集 50 集，复用原有 2 集。结果位于 `output/wiki/season1/`，总报告为 `REPORT.md`，逐集 JSON 在 `episodes/`，逐集报告在 `reports/`，待检查原文在 `review_items.json`。

普通 HTTP 请求受到 403 限制，本次通过正常浏览器页面读取 `.mw-parser-output` 的 `outerHTML`，没有使用代理、访问令牌或绕过验证。原始 DOM 字符串直接存入两个 `browser-capture*.json` 分卷，并按哈希分集保存在 `raw/`。原有两集使用上次的正文文本导出。

`episode_index.json` 记录第一季分类和集序证据：Tidying Up 页面含带集号的 Series 1 导航表，52 个链接与分类逐项匹配。Cleaning the Car 的集号由此确认为 S01E33；第一季版本记录其 previous_ids 并沿用原条目 ID，原来的两个 JSON 文件不变。

离线重建：

```powershell
python build_wiki_season1.py
python -m unittest discover -s tests -p test_wiki_transcript.py -v
```

正文含疑似恶意编辑（跨作品角色）、无法确定的集合说话人、未知括号说明及少量格式异常。全部保留，并通过 review_flags、逐集报告和待检查清单标记；采集覆盖完整不代表源剧本正确或经过原声核验。解析器已覆盖普通段落、列表、嵌套列表、表格、缩进段落和混合括号，排除站内导航、播放器广告及编辑控件。

以下保留两集试采集说明。

已通过用户打开的浏览器页面取得两集正文：Muddy Puddles、Cleaning the Car。普通 HTTP 请求仍返回 403，本次没有绕过限制，而是读取正常加载后的页面 DOM。第二集的季集号尚未由来源验证，暂使用标题 ID。

`*.dom.html` 是浏览器中正文标题、段落原文导出的最小 HTML，保留原段落、顺序、标点和不间断空格；它不是原始 HTTP HTML。Muddy Puddles 从首个场景标题开始，共 88 条记录；Cleaning the Car 从首段旁白开始，共 76 条记录。网页导航、介绍、目录和空广告容器不进入此正文导出。原页面地址和采集方式写入 JSON 的 source。失败报告保留在 errors 目录，最新批次已经成功。

独立脚本 `wiki_transcript.py` 使用 BeautifulSoup 处理 DOM，不调用本项目的音频、ASR 或数据库流程。依赖为 `requirements-wiki.txt`；本机已安装至 `.wiki-deps`。

## 使用本地文件

把已获准使用的 HTML 放到 `wiki-input/`，在 `two_episodes.json` 对应项中添加 `"file": "文件名.html"`。完整 HTML 必须含 `.mw-parser-output` 正文区域；纯正文 HTML 可用该容器包裹。若提供的是仅含 Transcript 的文本，添加 `"file": "文件名.txt", "format": "transcript_text"`；不要将整个网页的纯文本当作 Transcript 输入。

```powershell
python wiki_transcript.py wiki-input/two_episodes.json --output output/wiki
python -m unittest discover -s tests -p test_wiki_transcript.py -v
```

不带 `file` 时执行一次普通公开 HTTP 请求；遇到访问拒绝立即记录，不绕过限制。单集失败不影响后续任务，命令在有失败时返回 1。

输出：

- `raw/<episode>/<sha256>.html`：原始字节，按内容哈希归档，不覆盖输入。
- `episodes/<episode>.json`：按原记录顺序清洗；同次发言不按标点拆分。
- `reports/<episode>.json`：发言、未知角色、场景、声音、未解析正文及不完整标记。
- `errors/`：失败记录及可获取到的 HTTP 错误响应；错误响应不是 Transcript。
- `batch_report.json`：本次批次结果，应先检查状态，避免将旧成功文件误认作本次结果。

每条记录保留 `raw_text` 与 `source_record`。ID 使用 `集ID_E原记录哈希`，插入其他不同记录不会改变原记录 ID；相同重复记录使用出现次数后缀并发出警告。原记录文字修改会生成新 ID；暂不进行模糊匹配以免错误复用身份。

当前说话人表列入家庭成员、旁白及本季正文中已明确的常见角色别名。未识别的角色和 All、Children 等未指明成员的集合标签保留 `raw_speaker`，`speakers` 为空并报告。括号分类使用保守规则，混合动作与声音和不能确认的注释标为 `unknown`。未解析文本不会静默丢弃。

测试覆盖 OS、onscreen、完整条件句、夹杂动作、交替片段、多说话人、纯笑声、空正文、未解析文本、重复运行和插入后 ID 稳定。另有真实 DOM 导出的回归验收，检查两集记录数、Muddy Puddles 的完整条件句与混合动作、Cleaning the Car 的中断发言不跨动作合并，以及多人说话人映射。无不完整启发式标记不等于已通过原声校验；本次只核对 Wiki 正文。
