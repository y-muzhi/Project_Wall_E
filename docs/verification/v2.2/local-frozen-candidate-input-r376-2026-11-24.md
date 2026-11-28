# R376 当前候选 Schema 的固定输入核对

2026-11-24（香港时间），独立 `codex/2.2`。由现行 `schema_v22_release.py` 读取实际源码并构造固定输入字段，以本轮已验证 Linux x86_64 运行包摘要为依据。核查目标为 V2.2、Schema200、`FRESH_ONLY`，固定绑定 69 份现行源码文件及两份冻结设计。

V2.0 后端设计和 V2.01 后端迭代设计的根目录文件字节、独立分支既有 Git blob 及当前构建读取摘要均吻合。原 `db20-r50` 清单重新测得 SHA256 `10ff02e670eb705e6ac537eb9335449a72de9dbc93eeffbe46b16d7d74557f31`。主项目 V2.01 README、大纲、评审和前后端共五文件的冻结摘要另逐份核对。稀疏工作副本保有候选所需的后端输入。

编排没有发布 Schema、候选或 Git 提交。实际创建并打开 Schema 的证据见 [R362](local-x86-browser-scope-reload-r362-2026-11-24.md)，供真正集成的四目录变更范围见 [R371](local-source-candidate-handoff-r371-2026-11-24.md)。封存目标必须继续读取原两份设计和原资源清单。
