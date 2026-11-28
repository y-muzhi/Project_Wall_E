# V2.2 最新双工作区固定源码预检

2026-11-26（香港时间）。在实际 `codex/2.2` 和 `codex/2.2-integration` 上各读取 HEAD `deacba8a9545122f35a2f85c125a354205e06461`。核对 `backend`、`frontend`、`shared`、`tools` 的 2,739 个已跟踪及未忽略源码，每个路径的文件字节、摘要及原索引模式或未跟踪状态一致。物理文件组合摘要 `1e02f05d754e17b170f879ffb791504929b4d79de0eaf2ad6c99e976d900b093`。主工作区 V2.01 五份原设计文件再次与原摘要相同。

各自使用临时索引和可写的临时对象库，原对象库仅作读取备选。依次执行 `git read-tree`、`git add --all --sparse -- backend frontend shared tools`、`git write-tree`；通过 `git diff-tree --no-renames` 核对相对 HEAD 增 62、改 113、删 0，树外文档无差异，变更路径及状态原字节组合摘要 `772636b708903e27cebb7a132ec63612a234404d3cfa848d5a818295c1ef8700`。两侧预检整树相同，摘要 `78f5b369a2d7ef0691eafdffd1e76e4ec5d3a2d1`。

| 目录 | 两侧预检 Git 子树 |
| --- | --- |
| backend | `5658cc7f49d0c46f5e3096719bee92029175dd80` |
| frontend | `33c283f0e8415ecd47903f8327025395dfbb2007` |
| shared | `28abdfd852ed5bcc543ca3d60ae18d2355728519` |
| tools | `f638bf99f116528141d78abe409ff5199cea9aab` |

每边在结束前核对原索引文件 SHA256、索引无暂存、HEAD 及全部引用原字节一致。仅保留本文，临时对象及索引已清理。正式集成交付须在明确授权后用真实提交重新核对；预检对象没有持久化，不能用于候选准入。
