# 独立CHECK_DRIVER本轮复核（2026-11-11）

香港22:49—22:56，沿用户本轮约两小时实施的相关隔离Windows检查授权。工作树master／28a7c9e及现行DRAFT设计；无正常服务／数据、真实模型／计数、SYSTEM／WFP安装、Git提交推送。

## 环境及命令

由tools.quality_gate.environment清除私密配置与外网环境，WALLE_TEST_CONTROLLER_POSITIVE=1，固定SQLite3.54.1；独占TemporaryDirectory，tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider --tb=short，目标backend/tests/infrastructure/test_v20_guard_browser_driver.py。实际Windows LPAC／独立Job／专属结果管道及认证Guard，WFP安装／读取为原网络夹具，不是真实SYSTEM／WFP证明。

## 实际结果

- DRIVERCURRENT：1项通过、1项跳过，137.28秒。通过的是原RELEASE ACK后缺最后观测的恢复与清理证明；trusted-frames仍因复制CPython在脚本前退出0xC0000022、零可信结果帧而跳过，未通过正式驱动准入。
- DRIVERUCRT：仅在该次新临时运行包中加入同机System32/ucrtbase.dll，重算完整runner manifest并沿原只读副本核对，保留零capabilities及原LPAC／Job／专属管道。trusted-frames仍1项跳过，80.39秒，未改变现象；未把该覆盖发布到正式资源或永久修改运行包工具。
- 只读PE直接导入检查确认Anaconda CPython核心的已复制zlib及系统依赖；一次最小PE解析探针遇python3.dll空导入目录未处理而停止，不作为完整闭包／根因证据。此前选择文件可打开／SEC_IMAGE的历史证据也不能推出所有启动依赖正常。
- 只读查询对应本次临时路径、时间范围的CodeIntegrity事件：NoMatchingEventsFound，无对应事件。不据此排除全部OS策略或判定确切拒绝对象。

两个运行均保留原STOP／RELEASE和本地空Job核对后清理TemporaryDirectory、临时profile及子进程；ucrt overlay脚本不留文件。未放宽目录ACL、capabilities、浏览器sandbox、网络或系统策略。正式CHECK_DRIVER及真实浏览器三进程联合仍未完成；本轮普通Chrome实际SPA／HTTP证据见[coding检查配置](coding-check-configuration-2026-11-11.md)，两者不得替代。

下一步需定位实际加载器拒绝对象，或取得符合固定零能力／包边界的完整运行闭包；继续按独立迭代和真实Windows证据处理，不默认添加能力／安装／真实调用。
