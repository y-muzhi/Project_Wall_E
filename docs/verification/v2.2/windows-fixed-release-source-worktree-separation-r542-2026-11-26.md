# V2.2 当前工作区与既有固定交付隔离

日期 2026-11-26（香港时间）。两隔离仓库分别在 `codex/2.2`、`codex/2.2-integration`，均为 `deacba8a9545122f35a2f85c125a354205e06461`，树 `5230b7123a763b944f2cd45cb270f6c0b531b828`。分别以仓库原入口 `prepare-v22-release-source.py` 和实际 Windows Git 读取该固定历史对象到工作区外的本轮临时目录。依 `--verify-manifest-sha256` 回读，应用 1,426 项、构建 877 项，两个清单 SHA256 均为 `aa04ae2357e8a405717a3ca26741df90922b64208845b42f4eaeeeac2dbd7eee`。

两个导出中的 `backend/app/infrastructure/resources.py` 字节各自匹配明确 Git 提交，和各自含 R531 的当前未交付工作树文件不同。提交参数仅给符号 `HEAD` 的输入均返回 `CONTENT_OBJECT_ID_INVALID`，未创建输出。验收原始输出目录未被复用。

首次脚本解码 Windows 诊断失败；使用原始字节取得诊断后，确认宿主默认沙箱 TEMP 路径过深，无法生成要求的文件路径。以主项目的短 `output/.r542-*` 临时目录重试，两工作树与暂存区外运行完成，临时目录按归属清理。没有创建新 Git 提交、移动引用、变更索引或建立当前工作树的正式候选。
