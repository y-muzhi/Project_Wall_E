# V2.0 CommandRecoveryStore v4事务及浏览器

日期：2026-11-05，HEAD 28a7c9e，V2未提交。仅隔离浏览器／随机127.0.0.1端口／临时编译产物及walle-v20-idb-probe-*数据库；无正常业务库／用户资料／真实模型调用。

command-recovery-model.ts及command-recovery-store.ts实现技术库version=1的两个store／origin+key和唯一origin+intent，v4元数据／摘要／模块路由核对、原体8MiB／元数据64KiB／pending100与总128MiB限制，明确详情才返回body。prepare／dispatch／close均以实际readwrite oncomplete返回；dispatch按revision及原冻结字节CAS，close保存REQUESTED后禁止派发。原关联只由已解码回执补齐；202保留至原operation终态。终局摘要与删pending同事务，旧回复不能复活，显式未派发取消也受同事务门槛；只维护30天已终局摘要，pending永不按年龄删除。body损坏保留安全元数据查询／关闭，CLOSED摘要允许body_sha256=null。此层不发送HTTP，实际owner继续接入。

Node元数据／故障专项4通过。真实Chrome专项由tools/verify-v20-command-recovery.py运行，CLI0.1.23使用本机既存入口；Python外层持有匿名KILL_ON_JOB_CLOSE Job，浏览器／CLI／本机服务全部在本轮Job。临时根限定output/playwright/v20-idb-*，结束后先核实Job无成员再精确清理。无截图／录像／原始日志或JSON报告留存。

命令：.venv/Scripts/python.exe -u -B -X utf8 tools/verify-v20-command-recovery.py --cli-entry <本机已安装playwright-cli.js>。实际最终worker退出0／V20_IDB_BROWSER_PASSED／OWNED_BROWSER_CLOSED／OWNED_JOB_EMPTY_AND_BROWSER_OUTPUT_CLEANED，约4.44秒。

8组实际存储检查通过：唯一intent／两个连接CAS、DISPATCH计次及关闭屏障、原子墓碑／迟到回复／重开及pending不老化；纯未派发取消；损坏body可安全关闭；202原关联／原Operation终态及不降级已接收事实；真实put成功后transaction.abort仍不授权发送；100条真实未决／第101条拒绝且不淘汰；注入QuotaExceededError无幽灵记录；真实versionchange关闭本owner。另两个真实浏览器标签并行准备／派发，仅一个原key及一次门槛成功。

首轮发现QuotaExceededError在回调中被误分类CORRUPT，已按实际DOMException修复；另测试工具项目导入路径与CLI紧凑JSON解析已修，旧失败不记通过。默认AppContainer不能启动Chrome，获准非AppContainer测试进程后完成；未关闭生产安全边界或安装依赖。门槛断言不是TCP业务／页面或真实供应方验收；128MiB总量尚仅代码及边界核对，未实际灌满；blocked及真实掉电未执行。尚需发送owner／原终局核对、48业务DTO、设置／任务UI接入。

一手依据：[W3C Indexed Database API 3.0](https://www.w3.org/TR/IndexedDB-3/#transaction-finished)要求用transaction complete核对成功，单request success仍可能后续失败；strict durability为提示，不以其承诺真实掉电必然恢复。

后续真实128MiB／blocked已在最新8＋4＋2组及双标签组合通过，见frontend-command-owner-2026-11-05.md补记；真实掉电仍未执行。
