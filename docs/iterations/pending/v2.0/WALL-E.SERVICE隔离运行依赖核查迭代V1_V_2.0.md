# SERVICE隔离运行依赖核查迭代V1（V2.0）

2026-11-14香港17:14，承接两小时实施及原HTTP／Git原生复核。已有TESTING_HTTP_CHECK的pytest允许verified或endpoint_unavailable，本轮明确打印实际结果为endpoint_unavailable；这不等于正式双SERVICE或完整前后端联通。

先确认同一原主LPAC中运行依赖和套接字初始化的实际拒绝，不用普通账户成功替代。复用已固定本地Python／Node归档及原LpacProcessToken／Job／精确SID核验，诊断仅创建未连接IPv4／IPv6 socket和尝试导入_overlapped，不connect／bind／listen／发包，不调用用户端口、模型或计数。不修改WFP、系统目录或用户服务。

对照的能力名限定已知系统非网络能力registryRead／lpacCom／lpacAppExperience／lpacSessionManagement／lpacCryptoServices／lpacIdentityServices，逐一组合；不包括internetClient、privateNetworkClientServer等网络能力。临时测试角色仅将这些固定枚举送入原能力SID派生及实际令牌核验，生产白名单保持不变，工具显式WALLE_TEST_RUNTIME_DIAGNOSTICS=1才运行。诊断结果只说明该组合的原生现象，不发布资源或修改ready。

如仍拒绝，继续定位原实际SERVICE的退出／异常及所需机制，记录下一真实依赖；任何生产能力政策／loopback或网络策略变化须先补独立技术规则及实际拒绝边界，不能为了启动放宽隔离。本项不授权SYSTEM安装、WFP或网络连接；正式部署仍待明确授权。


## 本轮实际结论

六项固定非网络能力组合实际诊断均完成，IPv4／IPv6未连接socket和_overlapped三个初始化结果均10013（8.65秒）。未connect／bind／listen／发包，未改生产白名单、WFP或ready；没有证据把任一额外非网络能力引入生产。现象只能说明本机这些组合没有解决初始化，不能据此宣称正式WFP／loopback准入的架构不可行。

当前停止猜测能力名；下一实施依赖是受保护Guard部署的真实来源赋值／进程只读身份、正式网络策略及最小原SERVICE的启动／拒绝／STOP／RELEASE证据，再进入双SERVICE与固定前后端转发。系统安装和策略改变仍未授权，本迭代保留pending。实现及本轮实际结果见[验证](../../../verification/v2.0/guard-program-package-2026-11-14.md)。
