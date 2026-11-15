# V2.0独立检查资源设计静态核对

日期：2026-11-03（Asia/Hong_Kong）；M20-CHECKS-01／Q20-CHECKS。状态：文档与静态核对完成；未发布资源或运行产品检查。

## 范围与基线

起点后端0.8-draft-8／前端0.7-draft-7，现为0.9-draft-9／0.8-draft-8，均DRAFT。先保存独立迭代且保留pending，不合并V1.5或原汇总；HEAD仍8c5df4c6683e10c265e2f719a4fdc09ba4210ea0。原V1.5与EV20-01等并行改动保留。

仅7份V2.0 Markdown及源码／锁／一手资料静态阅读。无产品代码、资源、真实配置／秘密／正文／数据、安装、检查运行／类型／构建／浏览器／模型／计数、服务启停、Git写入／提交推送。本轮无产品进程，服务／在途任务未查询。

## 已读与设计核对

已读两份草稿中配置／检查／候选／控制／Guard／查询／接口及前端相关完整规则；quality_gate／quality_python／quality_node及8项自检源码、check-v15-offline入口、项目package与Python两锁、run-v15-evaluation真实调用边界与相关分支。未运行这些工具，真实v15模型评测入口不进入默认检查。误定位BND-CODE-VERIFY已改读真实BND-CODE-CHECKS，未虚构组件。

CHECK20-CONTROL-1区分项目命令与受控断言；项目退出0或自报条数／PASS不替代独立功能项。已同步固定资源／覆盖、只读产品输入、CHECK_DRIVER／测试端点与专属管道、真实case集合、停止／清理及精确复用。检查改稿不自动采用，结果不可恢复但活动／收尾已核实可明确结束失败操作并由用户新检查，历史UNKNOWN不涂绿。

用例新增同任务／检查／Item归属只读分页，计数只取已记录事实。页面区分MANUAL／替身范围和收尾，缺实际资源／依赖时未就绪，不用现成WALL-E脚本或Codex工具冒充产品资源。来源及未读边界见[独立迭代](../../iterations/pending/v2.0/WALL-E.独立检查资源与结果准入迭代_V_2.0.md)。

官方pytest退出码、npm脚本、Playwright沙箱／已有服务、Python／Node启动只读相关段落，不是全文审计或实测。controller／driver及按固定设计准备的casepack尚未发布，ready=false。

## 实际静态检查

PowerShell here-string将只读Python（pathlib／re／hashlib）脚本传python，核对本轮7份文档，subprocess仅执行git diff --check／git rev-parse HEAD；无脚本／JSON报告／原始日志落盘。首轮发现前端未明确引用复用来源字段，已补reused_from_item_id后完成受影响复核。

| 检查 | 实际结果 |
| --- | --- |
| 链接／结构 | 113处相对目标存在，外部12处统计；围栏／表格／尾空白／替换字符及1—8章通过 |
| 稳定契约 | 62个稳定定义有来源，前后端版本一致；旧权威marker及检查改稿采用路径移除 |
| 客户端 | 37个规范化路由均有后端定义，新增1条严格归属的case分页GET |
| 检查字段 | 类型／资源／覆盖、case计数、复用来源、driver／端点、收尾、未知恢复及公开投影核对通过 |
| 未来场景 | 后端84项、前端52项无重复；执行0，不是136项测试通过 |
| 文档保护 | 34份起点保护文档全部SHA256保持，原设计／历史验证未改 |
| 源码资源 | backend/app 131、backend/resources 356、frontend/src 150、frontend/tests 121，共758份四组摘要与本单元起点一致 |
| Git／临时 | HEAD不变，git diff --check退出0，本轮原子临时文件0，无提交／推送／忽略修改 |

## 当前摘要

- 后端0.9-draft-9：3b1c54af72c8fd10e22621c818d89cfa93a125f4c16863e03905526a5f50efe6。
- 前端0.8-draft-8：e08f4fba66a6c322c1c1c06df3454c2d01d5928685510eced2beec5cbdfef59c。
- M20-CHECKS-01：94b17cf6753770923be43727e5506cbf455d81ccff598100b3cc00ad29afa2b9。

## 未覆盖与接续

未执行真实资源发布、检查、依赖准备、driver／浏览器、保护资源／进程／管道、端点占用／复用、ACL／Job、网络／真实模型／计数、只读副本／清理／取消／重启或产品浏览器。84／52项均未来目标，执行0。资料和静态复核不能替代这些证据。

Q20-CHECKS设计已定／待资源及真实边界验证。接续最后一项Q20-DB，仍只设计，不打开或迁移正常数据库。
