# R432 当前集成交付输入

2026-11-24（香港时间）。在 `codex/2.2` 使用本轮 R430–R431 的完整源码，保持 R415 的 `backend`、`frontend`、`shared`、`tools` 四目录。按两个基线分别使用独占对象目录和临时索引，通过 `git read-tree`、`git add --all`、`git diff --cached --binary --full-index` 和 `git apply --cached --binary` 比较首次形成和回放后的整树。

| 原提交 | 回放树 | 变化与补丁 SHA256 |
| --- | --- | --- |
| `a0f40592702cb702ed928849ac540479c22c224f` | `8b781c8f1f60238a1a0251a0cda4222a02fce3a5` | 205 增、84 改，2,786,662 字节，`229d1ccd80141b274ecbe65be3f32603b51df9f0cbfee086bd8ca4c672bb9160` |
| `deacba8a9545122f35a2f85c125a354205e06461` | `9986258a785586da1af61047722e3c9289aac35e` | 44 增、99 改，1,110,170 字节，`a3a19d3ff47ab17243ba81062fb98a070dd9099d479bef619be828500a5e4f7a` |

两组的四个源码子树分别是 `310f832da5e785ff93033a6502e6b0c788fcf106`、`c0f82c5a90ec6ea096bfd605a0aec8b5ac030f04`、`28abdfd852ed5bcc543ca3d60ae18d2355728519` 和 `05b8f3e550cffb1148f0512111f46166d7e3bc31`。前后两套实际 HEAD、分支、引用和索引保持，集成工作区干净。主项目五份冻结 V2.01 摘要逐项相同。实际 Schema 的 69 份来源映射及两份设计的规范摘要与 R415 一致，分别为 `39c724d58700c070d2388a01a02a63ae75f7f7696367063a54b03ef98d118c78` 和 `5ec13932a43a1c7cc3f4b903daf61047cd54d6bf7acf1348cb994d9922777a29`。固定程序字节已更新，集成后须重建固定程序与候选。正式提交、登记和封存仍待相应授权。
