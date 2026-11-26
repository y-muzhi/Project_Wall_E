# R441／R442 恢复副本发布与受管备份派发

2026-11-25，独立 `codex/2.2` 当前实施源码。依据 V2.01 后端 4.10、4.12.1—4.12.3、6.5、7.10 及 V2.2 独立迭代。验证使用 Ubuntu 24.04.5 x86_64 本机隔离来宾，固定 CPython 3.13.18、SQLite 3.54.1、31 项依赖及 19 项宿主库，运行包 SHA256 `0241128f2faa82bcc1f34d3f87196b0b817333caec2d070bf5a91f0cd3998e9e`。来宾卸载公开编译工具装配所用的网络设备后才读入项目资料，没有宿主端口转发。

- R441 覆盖正式恢复副本在暂存之前和之后的冻结竞争、排他发布及目录同步时的互斥、同步中断后的原 inode 重取，以及无需原宿主准入的独立备份演练。专项夹具使用同一原数据准备和新目标。固定正式候选的重新装配、实物核验和采用须在实际集成交付后再执行。
- R442 覆盖错误策略、宿主先冻结、完成命令预读、原授权变化、执行响应中断和原捕获读回。原登记观察只读，原计划摘要与首次领取在同一事务内核对。现有管理业务专项核对错授权摘要前后原状态为 ACCEPTED／PLANNED，正确授权才转 RUNNING／DISPATCHING。异机策略的本机核验阶段和独立取回条件仍通过既有专项。
- R442 对照另外在固定 Ubuntu 来宾运行完整双普通站闭环，各自真实创建／保存需求文档并正常停机；真实管理 SQLite 中，过早完成、错捕获策略及宿主冻结均保持原操作 `ACCEPTED/PLANNED`。固定管理命令实际派发原捕获、生成并读回原结果，冻结后同一原键只读核对成功。来宾输出确认 `Actual managed SQLite capture, original dispatch and frozen readback passed`；这是管理登记业务实跑，不替代正式候选管理服务复验。

- Windows 导入及流程夹具执行 `test_v22_closed_artifact_publication.py` 和 `test_v22_managed_backup_dispatch.py`，29 项通过、2 项不适用场景跳过。无网来宾用已准入的固定解释器执行 `pytest -q --tb=short -p no:cacheprovider backend/tests/infrastructure/test_v22_*.py`，277 项通过、2 项不适用场景跳过。项目既有 Starlette TestClient 发出 httpx 弃用提示。Ruff 检查覆盖后端应用全部 661 文件，并单独检查改动的入口及专项。
