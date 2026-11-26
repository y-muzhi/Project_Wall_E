# R415 最新 V2.2 集成输入树与回放

2026-11-24（香港时间）。采用当前隔离 `codex/2.2` 中的 R412–R414、R417、R419、R427 源码。与 R389 使用相同范围 `backend`、`frontend`、`shared`、`tools`。在独立对象库和临时索引里从两个实际基线装入工作区文件，经 `git diff --cached --binary --full-index` 生成变更，再以另一临时索引 `git apply --cached --binary` 回放。两组分别同初次装入的整树完全一致，四个源码子树在两组之间逐项一致。

| 起点 | 回放后整树 | 差异与补丁 SHA256 |
| --- | --- | --- |
| `a0f40592702cb702ed928849ac540479c22c224f` | `de61a840aab7bc91a6a68bd5cfe1fb684bdc0137` | 204 增、84 改，2,768,869 字节，`01aa82c909c48a4bd9317dbbeabe237f06452f03815f0710927de88ce2531a01` |
| `deacba8a9545122f35a2f85c125a354205e06461` | `0294aa055489096efccc14416bb209452a2c8984` | 43 增、95 改，1,084,192 字节，`7dbfce6de4ccfab56d644d39917b13f6fe23baf268ae7ca41a3dd73c6f29aafa` |

| 源目录 | 共同子树 |
| --- | --- |
| `backend` | `6c6a8a4c147fd8993d13ea54175c4919b500d415` |
| `frontend` | `c0f82c5a90ec6ea096bfd605a0aec8b5ac030f04` |
| `shared` | `28abdfd852ed5bcc543ca3d60ae18d2355728519` |
| `tools` | `05b8f3e550cffb1148f0512111f46166d7e3bc31` |

校验前后两个工作区的实际 HEAD 均为 `deacba8a9545122f35a2f85c125a354205e06461`，真实引用、索引保持。开发索引 SHA256 为 `c4106e8ef44b8dc0adf645c27654184b459f497f81c01be89b1bd844fad8d88f`，集成索引为 `882cf39f95c0c9c5aa07bacb37da8a68c24fc7ab10cba4dac4433d49ced3fd3e`，集成工作区干净。仍须在授权后登记实际交付及集成来源，才能生成正式候选证据和发布包。

回放结束后在两套工作区分别按原字节计算两份后端设计的 Git blob，与各自 HEAD 对应项相同。V2.0 后端 blob 为 `dea7d048bfac6d0d8dd0be18ed8258925307b628`，V2.01 后端 blob 为 `ea3db09a23ab6694c4187cda402f6dcf25ed808c`。以当前 `schema_v22_release.py` 的原算法只读算出 69 份 Schema 来源映射的规范 SHA256 为 `39c724d58700c070d2388a01a02a63ae75f7f7696367063a54b03ef98d118c78`，两份设计列表的规范 SHA256 为 `5ec13932a43a1c7cc3f4b903daf61047cd54d6bf7acf1348cb994d9922777a29`。本轮涉及 `worker.py`、`environment_admission.py`、`environment_ordinary.py` 等受清单绑定源码。真正的隔离候选需要按集成源码和目标运行包重新生成 Schema 清单。
