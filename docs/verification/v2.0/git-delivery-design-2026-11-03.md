# V2.0 Git交付设计静态核对

日期：2026-11-03（Asia/Hong_Kong）；M20-GIT-01／Q20-GIT。状态：本轮文档及静态核对完成；固定Git包、引用事务、Windows及用户分支运行验证未执行。

## 范围与现场

起点后端0.7-draft-7（25aa26c690c8e1398c15e7a2325731214f72d1da98b354c6c9470e803a819308）、前端0.6-draft-6（abdeff737db13dd3d5177ba261691cb8aabfe54531aac5ba7358427418f19e60）；现为后端0.8-draft-8／前端0.7-draft-7，均DRAFT。独立迭代先写、保留pending，不合并V1.5或原汇总。HEAD仍8c5df4c6683e10c265e2f719a4fdc09ba4210ea0，原V1.5及EV20-01等并行改动保留。

本轮只写7份V2.0 Markdown并静态阅读官方资料／源码；无产品源码、资源、真实配置、秘密／数据、用户Git对象／分支或系统修改。无Git写入、模拟／故障恢复、测试／类型／构建／浏览器／模型／计数、安装／下载、服务启停或提交推送。无本轮产品进程，未查询服务／监听与在途任务。

只读git --version --build-options实际返回2.51.2.windows.1、x86_64、来源bd2ecbae58213046a468256b95fc4864de25bdf5；files默认引用后端，sha1默认及sha256算法列出。不能据此推断新固定包兼容，未替换现有Git。

## 资料及架构核对

官方发布／标签指向v2.56.0.windows.4及提交581291682ad5a238c08c93d1f5bd4518382a3230；选定MinGit x64并记录发布方摘要，未下载、解包／签名或运行。同标签update-ref文档、builtin解析／report_ok、files-backend旧值／symref分支已核对；--create-reflog确实传入stdin更新标记。未全文审计全部Git或OS。

原方案缺少的边界已在实际链路同步：

- no-deref可覆盖symref，协议采用prepare取得锁后再核对直接引用，而非一次把commit写入stdin。
- 本地config也属于来源，独立HOME不等于隔离；固定副本禁include解析、窄白名单及CLI边界，不执行用户程序或自动修改配置。
- Plan保存完整私有目标包，旧用户对象被GC不改变预览；固定包损坏则不可用，不回读最新源。
- 原提交payload及唯一Delivery尾注固定；reflog身份显式重建，作者时间／派发观察／delivered_at不混同。
- worktree别名链及prunable／locked不被忽略；合作式交付窗口不被包装成外部全仓库锁，排队／重启／过期需要本次重确认。
- commit可能派发后的ABA不能凭旧目标值或单条log判定未写；Git写成功、仓库后核对及任务完成分开。
- CONTROL_GIT按真实后端非提升用户令牌及Job管理，任务前挂资源步骤；AI执行仍TASK／LPAC，控制Git不能伪造模型身份。

共同字段／外键、原操作／RESUME输入、Guard、HTTP／公开投影、前端确认和恢复沿对应职责同步，不以排版检查代替这些架构核对。完整一手来源及未读边界见[独立迭代](../../iterations/pending/v2.0/WALL-E.Git交付协议与并发恢复迭代_V_2.0.md)。

GitHub插件后续读取发生传输错误、一次Git官网打开失败，按可用官方资料继续，失败请求不算已读全文或运行失败；未升级权限。静态搜索误指不存在lease.py，已定位现有ProcessLock／步骤规则，不运行／创建该文件。全文输出受限时只核对实际取得的相关分支，不称完整源码审计。

## 实际静态检查

使用PowerShell here-string将只读Python脚本传python，以pathlib／re／hashlib检查本轮7份文档，subprocess执行git diff --check／git rev-parse HEAD；不留下脚本、JSON报告或原始日志。新增协议及恢复细节后复核受影响契约，未执行产品试验。

| 检查 | 实际结果 |
| --- | --- |
| 相对链接 | 103处目标存在；外部18处只统计并按本轮所需一手段落阅读，不称全部网络可用性检查 |
| 文档结构 | 围栏／表格列数／尾空白／替换字符及前后端1—8章核对通过 |
| 定义／版本 | 62个稳定定义有来源；后端0.8-draft-8、前端0.7-draft-7及共同契约一致 |
| 客户端绑定 | 36个规范化路由均有后端定义，无新增任意Git／删锁／Shell入口 |
| Git契约 | 固定包、窗口／外键／状态、持锁协议、原提交／Plan包、CONTROL_GIT／私有回执及旧占位清理核对通过 |
| 目标场景 | 后端76项、前端49项编号无重复，本轮执行0；不是125项测试通过 |
| 保护文档 | 本轮起点32份全部摘要不变，含规则／模板／正式V1.5／原来源及既有V2.0资料／历史验证 |
| 源码资源 | backend/app 131、backend/resources 356、frontend/src 150、frontend/tests 121，共758份四组摘要与本单元起点一致 |
| Git／临时文件 | HEAD未变，git diff --check退出0；本轮原子临时文件0，无提交／推送／忽略规则修改 |

本单元前已有的V1.5代码／文档及EV20-01资料变化继续保留；摘要一致只相对本单元起点，不覆盖其历史记录或接管其验证。

## 当前摘要

- 后端0.8-draft-8：32e5fb2c5ed14a78910dbfbe7ec7640bfc6e823460198105e1d4170628aa8a96。
- 前端0.7-draft-7：7cee8cf823051b34a89ab191c3d6222f2bdad98c4c8cee1328cb11dbcd512d57。
- M20-GIT-01：7c9f044046189918bac43f280bd191e6d065071ec568e98cb542ba409214d7d4。

## 未覆盖及接续

未执行固定包／敌对配置／include／hooks／metadata、对象及raw commit、prepare／symref、worktree／ABA、窗口超时／重启、真实ACK／SQLite补记、CONTROL_GIT令牌／Job／崩溃、Git残留锁、原目标包损坏或浏览器。后端76项、前端49项均为未来验收，本轮执行0。资料／静态核对不能代替这些运行证据。

GIT20-LOCAL-1设计已定／待固定包、协议及故障验证，ready=false。下一项Q20-CHECKS，再接Q20-DB；本记录不授予安装、运行、付费或用户仓库试验许可。
