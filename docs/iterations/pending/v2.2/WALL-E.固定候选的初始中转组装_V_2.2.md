# WALL-E V2.2 固定候选的初始中转组装

2026-11-25。依据 V2.01 后端 4.7、4.11、7.7、7.10、8.2。现有受信管理入口核验、安装和封存固定候选。追加 `prepare-release-build`，将独立构建的应用快照和前端产物组装为已有入口可直接读取的中转包。原构建须从获准的集成交付独立执行，应用快照及前端索引摘要由受信构建步骤测定。

- 受保护计划固定管理范围、原集成操作、仓库、commit 和 tree、候选 ID、构建完成时间、实际固定运行与 Schema、导出源码清单、应用快照及完整前端索引摘要。计划绑定应用、前端、Schema、中转和预期发布根。管理身份只读核对已成功集成交付、各开发原交付及原资源字节。应用、前端、Schema、中转、发布、运行和管理目录相互独立。
- 组装核对固定应用、实际前端文件、Schema 来源及权限，按实际字节生成两类索引、发布清单和原协议的构建记录。前端保留原构建字节。检查引用初始为空，后续由独立应用、浏览器、构建和恢复验证收集。
- 从中转父目录内私有暂存，完整核对后以候选 ID 排他发布并同步。相同计划重取原结果，已占用且不符的目录保留。发布后同步或复验结果不明时保留原目录并报告待核实。
- 输出提供候选描述和中转发布策略，沿已有受信登记接 `inspect-release-build` 和 `prepare-candidate-validation`。组装与重读核对源清单的 commit、tree 和全部应用文件。应用输入只包含导出源码文件，组装在受保护的中转包内用固定运行工具生成程序快照。前端构建输出与构建源的对应关系由受信构建方负责，已有候选入口继续独立复核原集成交付。

受信宿主从原管理安装调用 `manage_registry.py prepare-release-build`，在通用 `--root`、`--sha256`、`--project`、`--program-sha256`、`--runtime-entry`、`--anchor`、`--anchor-sha256`、`--catalog`、`--catalog-sha256` 外，指定 `--release-build-policy` 与 `--release-build-policy-sha256`。计划文件名为 `release-build-policy.v1.json`，目录引用为 `{path, identity}`，其中 `identity` 采用现有 `{device, inode}`。`schema_ref` 和 `source_manifest_ref` 使用 `{path, sha256}`。源清单采用独立、根所有的只读文件。同一候选 ID 下只采用原计划摘要。构建输入文件为根所有、只读普通文件，索引沿既有 `0444`／`0555` 和 UTF-8 路径排序规则。输出中的 `candidate`、`candidate_sha256`、`publication_policy` 和 `publication_policy_sha256` 按原登记及策略文件保存方式采用。中转清单、构建记录和计划回执分别落盘。

| 计划字段 | 来源 |
| --- | --- |
| `format_version`、`manager_id`、`host_id`、`registry_generation` | 计划版本 1 和当前受信管理范围 |
| `release_id` | 本次候选的独立 UUID |
| `delivery_operation_id`、`repository_ref`、`source_commit`、`source_tree` | 原成功集成交付 |
| `application`、`frontend` | 受保护应用快照及前端构建根和各自文件身份 |
| `staging_root`、`publication_root` | 当期中转父目录和预期发布父目录的实际文件身份 |
| `runtime_manifest_sha256`、`schema_ref` | 目标固定运行包及独立 Schema 发布 |
| `source_manifest_ref` | 实际 Git 导出清单；受信构建方按原输出摘要安装受保护文件 |
| `program_sha256`、`frontend_index_sha256` | 受信构建方核对的程序快照和规范前端索引摘要 |
| `compatibility_refs`、`built_at` | 原兼容引用及实际构建时间 |

组装成功后，`staging_root/<release_id>/release` 为既有验证和封存入口所需的固定文件闭包。相邻的 `build-record.v1.json` 被候选描述引用，`staging-receipt.v1.json` 保留本次计划摘要。先以返回的候选描述和策略登记并读取中转，再准备独立候选安装。收齐实际检查后沿原最终组装、封存和发布准入。

## 固定提交的独立构建输入

`tools/prepare-v22-release-source.py` 根据已选 commit 及其 tree，从本地 Git 读取 V2.2 应用和前端构建所需的跟踪文件。先核对两份 Schema 设计、全部 Schema 源文件、冻结结构资源和前端锁文件等必需项。用原 Git blob ID 复核归档内每个文件，拒绝路径别名、符号链接、子模块、LFS 指针、漏文件和归档替换内容。

输出为独立新目录下的 `application`、`build` 和源码清单。前端锁、源码、共享材料和后端公开资源在 `build` 中各自物化，已有工作树、索引和 Git 引用只读。两侧公共文件分别复制，供非特权构建步骤准备自己的依赖和前端产物。应用输入供受信构建方核对和保护，导出及重读返回预期的 `program_sha256`，组装时独立生成并复核实际程序快照。此命令的清单只证明所选择 Git 对象与源文件字节，当前真实登记和正式候选仍分别经已有入口核对。

构建完成后，可用同一命令的 `--output <导出根> --verify-manifest-sha256 <导出时记录的摘要>` 重读。它核对应用和构建两侧的固定输入、全部父目录及逐文件字节，拒绝新增源码、替换路径或共享文件。构建树中的 `frontend/node_modules` 和 `frontend/dist` 保留为独立输出，前端真实产物仍由候选中转索引独立核验。源文件被修改时回原交付重新确认。

受信构建方将 `application` 的原文件内容、实际 `build/frontend/dist`，以及原导出清单分别复制到彼此独立的受保护 ext4 位置。应用输入保留导出时的 `0444`／`0555`，前端文件固定为只读。构建后重读返回的 `program_sha256` 写入计划。以现有发布索引 `{format_version, role, files}` 和前端文件逐项 `path`、`mode`、`bytes`、`sha256` 计算 `frontend_index_sha256`。组装入口独立复算两项摘要，同时生成固定程序快照，导出工作区继续归非特权构建身份。
