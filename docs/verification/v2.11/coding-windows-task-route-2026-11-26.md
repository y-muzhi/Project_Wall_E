# 实际 Windows 任务回环验证与收尾

2026-11-26，香港时间。V2.11 事项 22 修订 8。目标为查清正式 TASK 的网络边界。在独立任务身份与空白工作区运行固定 Python 探针，全部规则仅匹配该次任务的唯一 SID。

| 原生验证 | 实际结果 |
| --- | --- |
| 在 Windows BFE 的临时事务中创建已绑定的 provider 和 sublayer | 六个所需过滤层可读。对象从同一事务读回，回滚后再次确认两者不存在 |
| 对只有 `registryRead` 的原 TASK 类型令牌加九条精确 WFP 规则 | IPv4、IPv6 socket 创建、出站和监听均为 Windows 10013 |
| 同一范围，加临时测试令牌的私有网络 capability | 两种 socket 及控制端口监听调用成功，指定模型端口出站超时，未获准端口出站为 10013 |
| 再为唯一测试 SID 加出站回环例外 | 指定模型端口完成字节往返，未获准端口仍为 10013。宿主到控制端口的连接未取得响应 |
| 增加该 SID 的入站回环助手 | 助手确认运行，控制端口的收发测试仍超时。模型端口可通，未获准出站端口为 10013 |

按原停止指示结束最后一轮验证。退出时撤掉测试 SID 的回环例外，关闭动态 BFE 会话并复查该对 WFP 对象不存在。测试令牌的 capability 与例外未进入产品配置。没有外部推理或计数调用，正式 8001 未切换。入站链路及真实进程持久规则仍缺准入证据。Windows 原生操作的范围见[微软回环排障文档](https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/troubleshooting-uwp-firewall)。

修订 8 在 `GuardDeploymentOwner` 的原任务网络检查阶段接入 `ensure_admitted_task_wfp_namespace`，先核对固定环境证据，再由 SYSTEM 确认或创建与原安装绑定的持久对象。普通账户、半对对象、异主信息或独立读回事实缺失均拒绝。88 项 WFP、部署组合、任务证据及失败回归通过。原生 rollback 验证使用临时管理员事务，生产 SYSTEM 权限和整条启动未验收。
