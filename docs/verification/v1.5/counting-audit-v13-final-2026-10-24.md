# V1.5计数审计与受限执行器最终联合

2026-10-24T13:33:32.194489+08:00。命令：.venv/Scripts/python.exe -m pytest backend/tests/infrastructure/test_counting_journal.py backend/tests/infrastructure/test_tokenization.py backend/tests/guide/test_v15_evaluation_tool.py backend/tests/guide/test_v15_count_probe.py -q -p no:cacheprovider。

退出码=0；实际结果：32 passed, 1 warning, 24 subtests passed in 270.39s (0:04:30)。

先前27文件：13 failed／197 passed／13 subtests，917.67秒；13失败均在旧V1.0自动初始化夹具setUp。已转换为正常V1.5创建＋接受＋真实Context及8项计数，保留13项同等审计／锁／退休／fsync／30天边界／失败不覆盖／实际裁剪证明；单独13 passed、11 subtests／49.30秒。未修改业务代码来容纳旧初始化。

本联合补充新纯计数工具4项（在27文件启动后新增）；不声称28文件完整联合重跑。27文件中其余197通过的生产源码不变，无新失败或生产改变因此不机械重跑完整集。全部临时库与私有响应／loopback，无真实凭证／供应方调用，无原始日志／测试JSON留存。

最终静态核对：git diff --check通过（仅既有CRLF规范化提示）；cleanup-test-artifacts.py --dry-run为JSON0／screenshots0；v9—v13资源长度／SHA及BE摘要通过。backend/app源码SHA=3b6164bc5806cc672769175bbf2f0c4279b9b9368a94d185f4b0340fb3c6fe56，与原联合时完全相同；原108正常证据文件聚合SHA仍61e51eb528ef7edbf366c2e3855f331320cd961c76fd21a7759f79bf37e15ce9。13个旧夹具Temp锁文件的清理被自动审批拒绝，保留为未完成项；正常库／审计不删。
