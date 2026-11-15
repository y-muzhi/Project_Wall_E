# 离线运行包清单准备（2026-11-13）

## 范围与来源

香港14:06起接续本轮实际时段，依据BE7.4.4及[实施前pending](../../iterations/pending/v2.0/WALL-E.离线执行器运行包清单准备迭代V1_V_2.0.md)。master／28a7c9e13c73a9d386081a6dd894244b51746a45，正式设计／Schema／当前目录pin未改；无真实执行器、下载、安装、供应方、用户库／Git目标／服务操作。其他任务改动保留，源码原子保存。

## 实际实现

- infrastructure/opencode_runtime_preparation.py读取已准备的离线目录，逐真实NTFS身份／路径和有界原字节生成现有schema1清单，再调用既有_inventory／_verify_tree／_verify_control_files核对完全相同的闭包及配置规则，输出确定引用。准备上限100000枚举条目，原文件／总量／清单容量及取消／墙钟限制独立保留。
- 目标须在源树外且不存在。完整清单同目录临时写入、flush/fsync／关闭，经原verify_opencode_runtime_bundle重新校验后，以同卷os.link无覆盖原子发布，再移除自己临时名；现有或竞争目标不替换。源树不写入、不执行。
- 原opencode_runtime_bundle.py复用LockedFileSource的分块取消回调；无copy回调时只对控制文件保留正文，其他文件仅摘要，真正复制回调仍提供原始字节。既有原文件身份、只读DACL／运行角色发布及重核路径未删。
- tools/prepare-opencode-runtime.py为明确两个绝对路径的准备入口，打印文件数及非秘密引用；不改变任何pin／准入／配置或用户服务。已有check-opencode-binary.py继续只读校验。用法见[准备说明](../../project/v2.0/执行器运行包准备说明_V_2.0.md)。

## 命令与实际结果

使用项目.venv、tools.quality_gate.environment及TemporaryDirectory；固定bootstrap tools/python-v20.py tools/quality_python.py，pytest -q -p no:cacheprovider --tb=short --basetemp <本轮临时根>/pytest。当前Windows用户真实NTFS；所有假包／JSON清单／CLI输出在临时根，finally清理，仅本Markdown留结果。

- 初版test_v20_opencode_runtime_preparation.py与既有test_v20_opencode_runtime_bundle.py共26项10.90秒通过。
- 扩展最终核对失败／核对后取消／真实双发布者竞争后，首次28通过／1失败：故障注入把文件变长，原有容量检查先抛CONFIG_READ_BYTES_EXCEEDED，而测试期待摘要不符；产品正确拒绝。改为同长度变更，以确实到达摘要边界，不放宽生产校验。
- 同两文件29项11.44秒通过；随后补真实同字节换文件与外部硬链接两项，首次30通过／1错误期待：硬链接在LocalPathGuard就按MULTIPLE_HARD_LINKS_REJECTED拒绝，比预期ConfigReadError更早。改为核对原NTFS边界的准确错误，不修改生产放行规则。最终同两文件31项11.57秒通过：新准备专项20项，原包／DACL／复制／环境11项。实际CLI成功及重复拒绝，不覆盖已有目标；中断／最终失败／竞争后本轮临时名均0。
- 选中生产／工具／测试Ruff lint通过；末次格式及源码摘要见下方收口补充。

## 未覆盖

隔离假包不是已发布OpenCode运行包。真实二进制、完整真实依赖包、SYSTEM／LPAC／WFP、真实模型与完整产品交付仍需独立证据；此清单准备器不能使ready=false改变。本轮没有把用户目录重新打包或发布到正式运行路径。

## 收口补充

选中生产／工具／测试lint通过，全489生产＋10专项＋1工具共500文件格式通过。git diff --check通过，仅既有CRLF提示；清理dry-run JSON=0／screenshots=0。完整本轮摘要见[汇总](managed-native-configuration-2026-11-13.md)；本单元关键原字节：

| 文件 | SHA256 |
| --- | --- |
| backend/app/infrastructure/opencode_runtime_preparation.py | 358d6e15bf056d255a202e10859a74d405b53e9ad95b7cea9cc65abbe3d02b5a |
| backend/app/infrastructure/opencode_runtime_bundle.py | 43fdc93b3b231638a88316fcd23fd88300a2f09d4c95421f02648ec598df8164 |
| tools/prepare-opencode-runtime.py | 89a07eed5f3a6d9ca3e5612386b5e578531877dec62f0d7e5eff1f55bc37ef70 |
| backend/tests/infrastructure/test_v20_opencode_runtime_preparation.py | 0a012f05bc7b3c10bfb2557524f7ee68f368e2573a3cbaca5f0d6c2d89836ffa |

