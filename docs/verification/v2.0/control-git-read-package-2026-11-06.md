# 控制Git只读准备包与断连核对（2026-11-06）

未提交V2工作区，BE0.17-draft-17／FE0.16-draft-16不变；按[只读包细化](../../iterations/pending/v2.0/WALL-E.控制Git只读准备包实施细化_V_2.0.md)实施。源码同目录临时文件、fsync、原字节复核及os.replace。

## 实际范围

windows_private_package.py：只在实际活动operator-only父包下按预留nonce创建新读取子包，绑定父FileID及原ControllerPrimaryToken；operator完整权限、不同真实读者仅RX，已有包和ACL不修改。windows_empty_directory.py沿同读者创建只读空hooks，保留OWNER_RIGHTS限制；windows_private_record.py拒绝读取包承载Guard私有记录。原进程退出后允许核对原静态副本及清理，禁止重新授予或新建执行资源。

固定Schema来源更新，显式发布db20-r15，manifest SHA256为34f1c1cbcdb1916a48b25902f6e39718c1a6842b6c7ffcfe0754487de9151b40；保留r1—r14，SQL物理结构沿r13，没有升级正常数据库。

## 检查与修复

普通非提升隔离环境；quality_gate.environment、tools/python-v20.py／quality_python.py、pytest --basetemp位于自动清理的.tmp目录，无业务凭据／外网／真实模型／用户服务变更。

- 四文件专项：test_v20_control_git_read_package.py、test_v20_windows_private_package.py、test_v20_windows_config_copy.py、test_v20_windows_private_record.py；修正旧未初始化对象夹具后50通过、6子场景，3.01秒。实际原普通token、配置副本、只读hooks、退出后静态核对／拒绝新分配、父对象重定向及多SID ACL负例。
- 扩大至空hooks、原生Git配置及metadata两对象格式、published_schema、maintenance_flow、startup共10文件：90通过、6子场景、1失败，151.17秒。失败为维护测试硬编码2026-11-05时间早于动态夹具记录，业务chronology校验正确；改为原updated_at后1秒。
- 修正后maintenance_flow全部7通过（与下项合跑49.46秒）；新增断连专项暴露真实问题：对端关闭pipe但进程仍活时OS仍返回旧peer PID。windows_pipe_peer.py新增零字节PeekNamedPipe，不消费帧，失败拒绝。生产端点为OVERLAPPED、原线程独占，不在并行IO中调用。依据[Microsoft PeekNamedPipe](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-peeknamedpipe)，同步多线程句柄不在生产调用前提内。
- 修正后原10文件通信／身份／控制方组合178通过、1条既有Starlette弃用警告，7.77秒；包含新断连但进程存活用例。220个app文件Ruff格式及受影响模块lint通过。此前丢失结果的一次回归未推断为通过，以本记录可见回执为准。

## 证据边界

普通同用户Native链路及新建合成SID ACL结构不等于真实SYSTEM Guard／跨用户有效读取证明；未安装、未修改既有ACL／WFP，完整保护运行包、Guard动作生产派发和LPAC-WFP仍待实施／准入。无新增HTTP或UI验收，ready=false。所有本轮进程／文件由原owner及临时上下文退出清理，不保留原始JSON、日志或图片。
