# V2.2 R61 源码交接差异往返验证

2026-11-21。独立 Windows 分支 `codex/v2.2-windows-implementation`，对应原 Linux 基线 `a0f40592702cb702ed928849ac540479c22c224f`。分别使用临时 Git 对象目录和两个临时索引。以 `git read-tree` 载入该基线，`git add -A -- backend frontend shared tools` 仅写临时索引，再以 `git diff --cached --binary --full-index --no-ext-diff --no-textconv` 形成固定差异。第二独立索引通过 `git apply --cached --whitespace=error --check`、实际采用并获得相同树。拒绝破坏的差异及对已采用树重复采用。没有向真实运行目录运行 Git apply。

最终比对覆盖 83 个修改和 115 个新增源文件。差异为 1584484 字节，SHA256 `9ab56fb38f20427c77b653bd2f4da5006a314f8792a23b47d4c58d5924d7baec`，采用后的 Git tree `7c9d767c170170c5a9a4c9d0742c1829bc1748c0`。源范围不含暂存配置、正常服务数据或结算记录。实际分支的索引摘要不变，暂存为空。临时对象、临时索引和差异数据已清理。

接续先核对原开发／集成目录与实际未提交变动，在独立暂存索引或目录验证补丁；若原目标文件另有修改，逐一合并，不能直接覆盖。实际源码改写前复验原文件字节，按 `AGENTS.md` 同目录 fsync 后原子替换。Linux 普通业务、固定发布、恢复及候选验证后再使用受信发布入口，不把源码差异作为运行包。
