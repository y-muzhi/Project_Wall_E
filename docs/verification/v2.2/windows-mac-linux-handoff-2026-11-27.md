# V2.2 Windows 受信源码和 Mac Linux 启动准备

2026-11-27（香港时间）。开发、集成各自显式暂存 V2.2 源码、脚本、资源和专项测试。两索引整树同为 `783a92e96ceed8c79425c60394d7c8a03e9cd61f`，共 172 个变更文件。开发提交 `27905ede384e7b1a216eb735c969825c31507141` 后，集成核对同一索引树并快进采用该提交。软件历史保留。首次本地路径 `git fetch` 遇到 Windows MSYS shell 权限错误，改用原生 Git `pack-objects`／`unpack-objects` 传入确切对象，在核对直接父提交和已暂存树后更新集成引用。

使用两边实际 Git 及项目 `prepare-v22-release-source.py`，按明确提交和树在新临时根各导出并以 `--verify-manifest-sha256` 回读。应用 1,458 项、构建 881 项，源码清单 `9a0afb0e5aaabfc8020b4e80cc9a993c7df62d21ae5326f5ab00ef5a1c9756a0`，程序摘要 `4e6c5b9a506697bfe4354749386c15583a32a3e8e90111359cdbe3d60f0619a6`。两侧输出完全一致，独立临时目录清理。此前 R547 的物理预检包含 3 项未跟踪的管理前端生成物，本次显式源码提交排除；核对两边各三份输出字节一致并仅清理这些可重建的 `frontend/dist-management`。保留 Windows 主工作区 V2.11 及现有用户数据、运行输入和环境。

本轮根据原来宾输入核对 CPython 与 SQLite 原档、bootstrap wheel 及固定 lock，逐项复算两个架构各 31 个 wheel 的文件字节、长度、锁定版本和目标标签。整理的 `aarch64` wheel 清单摘要 `22b07c01b1adaeb4f9b7d678f7453fe5c03985dd4dbbeaa69678a5dfc5b909ef`，`x86_64` 清单 `b2a89b6479f9dad10bf122fb082351edfcc1bc268ba5ebfa51f2b541f2217464`。V2.01 原五文件与实施断点原摘要一致，供交接保留字节。锁定运行输入准备是 Windows 离线核对，Mac 目标安装、本机实际构建和端到端产出依 [启动文档](../../project/v2.2/Mac%20Linux双环境验证启动_V_2.2.md) 独立执行。
