# 原生权限来源与前驱链（2026-11-13）

## 基线、授权和边界

香港12:21启动用户要求的两小时工作量接续；本批代码与检查实际执行至12:34，随后同步文档与断点。master／28a7c9e13c73a9d386081a6dd894244b51746a45，开／收Git折叠425条，保留其他改动。BE0.17-draft-17 SHA256 1a8d277f25de570ce72e74a73ff763bf73f622fcf94b61f0820b78a1a5c6fd37；FE0.16-draft-16 SHA256 38557cee854697044ab7daba30f694738429be1235264a153851e8fc808cf3a7，DRAFT及Schema200 db20-r44不变。

读取AGENTS、原进度／计划／映射、BE APP-CODE-CONDITIONS与7.4.4及关联原会话规则、FE配置能力绑定、实际原生动作／driver／资源目录／授权路径。尚未重读无关设计全章。先登记[独立pending](../../iterations/pending/v2.0/WALL-E.原生权限原会话来源绑定迭代V1_V_2.0.md)，源码和Ruff格式结果均完整内存、同目录临时文件、fsync、原字节CAS及os.replace保存。

本轮无新API／Schema／资源／前端src变更；不真实模型／计数、不用户库／Git目标写入、不启停用户服务、不SYSTEM／WFP安装或提交推送。

## 实际实现

1. apply_permission及observe_permission现在先核对原创建意图、完整metadata与严格正ACK；before的全部六项来自该不可变来源。当前GET和调用方同时给出其他id／title／agent／model／metadata／permission也不能自证合法，失败在网络和新意图之前。
2. 可显式传程序持有的原START或HANDOFF／REPAIR创建scope（同controller，继任为原第1或4步）；源scope持久在原权限意图，重开／恢复按它读取。task_id／instance_id必须与根创建一致；缺失、损坏、他任务／实例及本次APPLY_PAIR冒充创建均拒绝。旧无来源字段意图仅指原START。
3. 原生重复更新显式携带前驱scope元组，持久完整列表，逐个验证原意图及严格ACK、同一创建来源、准确前缀和before有序累积。跳项、乱序、重复、环、自引用、未确认／损坏或错回执不查询HTTP；不得自动挑选最新文件。未知与独立新进程恢复只有GET，原PATCH不重发。前驱读取前后执行停止检查，不在长链中忽略STOP。

这些是底层原生来源与恢复能力。前驱ACK不证明业务APPLIED／EFFECTIVE；正式C39生产者仍须从已采用的业务链提供scope，实际资源编译／OS同组与原生／业务最终采用尚未接通。CONTROL_ONLY现有行为不扩大。

## 命令、环境及实际结果

项目.venv锁定Python／Ruff；获批当前Windows用户运行真实loopback HTTP、私有NTFS和原子原意图。所有专项通过tools/quality_python.py离线护栏，tools.quality_gate.environment隔离环境，TemporaryDirectory独占临时根，pytest使用-p no:cacheprovider与显式--basetemp；stdout／stderr仅内存汇总，finally清理，无真实秘密／普通data访问。

- 初版来源绑定：test_v20_native_permission_application.py 72项，14.86秒通过。
- 初版共享调用方：test_v20_opencode_instance_control.py、test_v20_native_acknowledgement.py、test_v20_native_session_policy.py共169项，31.70秒通过。后续有源码变更，故再做最终联合。
- 继任来源后82项17.67秒；原生前驱及跨进程恢复后96项24.58秒通过。都是历史阶段结果，不相加。
- 最终四文件同一次运行：267项55.68秒通过（权限专项最终98项，关联169项）。包含真实loopback、NTFS、新进程恢复和前驱中途STOP；供应方、OpenCode正式执行器及OS策略仍非本证据。仅已有Starlette／httpx弃用警告，无依赖修改。
- python -m ruff check --no-cache选中上述修改的生产／测试文件：通过；python -m ruff format --no-cache --check backend/app与本次专项：486文件通过。git diff --check通过，仅既有application-router.test.mjs CRLF提示。
- tools/cleanup-test-artifacts.py --dry-run：JSON=0／screenshots=0；本轮walle-permission-*专属临时根查询0。未删除正常DB、初始化包或服务运行日志。

## 服务现场

12:33获批当前用户只读检查，8000／5173无监听，之前实际后端391372／前端440368均不存在；前端连接WinError10061。历史服务日志只保留旧启动成功，未说明退出原因，不推断故障根因。此状态不同于00:50启动记录，不能沿用旧“正在运行”。本轮没有启动／停止／重启服务，也未恢复已取消的Node／Vite崩溃专项。新源码未通过重启加载到用户服务，不宣称当前页面已使用本轮实现。

## 最终源码原字节摘要

| 文件 | SHA256 |
| --- | --- |
| backend/app/code_tasks/task_native_actions.py | 790979562713bbbe6011935c3de062ba34a540a6d6242b02daa7d4aa021dc9d5 |
| backend/tests/infrastructure/test_v20_native_permission_application.py | 598ba142d02736f9ca600263680fc78b544c311c7c85817d2eac33a54f313ac6 |

下一单元：已采用业务C39链→原生来源scope绑定，真实资源→NativeCodingPolicy确定编译、PATCH原生产者／未知恢复、OS／config/providers／session同组采用及随后会话基准。不能仅凭本轮原生ACK开放权限，也不能把底层元组当客户端可填写的授权。
