# Guard启动计划预核与目标父目录（2026-11-14）

## 基线与范围

三小时任务香港18:21:36／UTC10:21:36开始，HEAD28a7c9e13c73a9d386081a6dd894244b51746a45，开始默认Git脏状态517行，保留其他任务。BE0.17-draft-17／FE0.16-draft-16的既有SHA未变，Schema200／SQLite3.54.1／db20-r49不变。只改tools与相关测试／管理文档，未改APP／前端／正式设计、旧分发包或用户数据；没有SCM安装、ACL／WFP修改、真实模型／计数或提交推送。

源码内存完整准备、同目录临时文件fsync、原字节CAS和os.replace；格式同样原子保存。测试临时目录自动清理，结果仅Markdown。独立技术规则先登记pending《Guard启动计划只读预核与受信安装准备迭代V1》。

## 实现与专项

- tools/windows_guard_plan.py抽出原完整plan组装，原windows_guard_bootstrap.py复用；policy／schema1／required_steps及固定SCM参数保持。预核必须拿实际部署与两个ProgramPackageLease重组同一canonical plan，再比较原字节；program_ref／manifest／count、服务名／account／start／数组及image_path、目标布局、未知字段或参数不能独立漂移。
- tools/windows_guard_inspection.py只读持有原三个输入文件、两个完整源包、全成员／数据流／未来路径边界；固定plan SHA，SID与实际普通操作者对应。目标必须未创建且与输入／源不交叠；计划投影为原JSON独立副本，不可借外部dict改变owner。
- 父目录核验明确传入原外部ObservedProcess及其创建时刻，复用ControllerPrimaryToken／ControllerAccessQuery；不放宽原GUARD_SELF_TOKEN_REJECTED。结果只属这个原普通读者的权限，不当正式后台程序认证／SYSTEM证明。无原读者的CLI不得进入父目录检查。
- 未知构造／关闭保留整个owner，不重试；父查询未知后整个预核对象不能复用；取消的__enter__关闭原始输入，不遗失构造后已打开的资源。

首轮48通过2失败：源增长先触发原CONFIG_READ_BYTES_EXCEEDED，原测试过窄；后改为增长与等长变异分别断言不同拒绝，未放宽算法。父目录误用查询宿主自身Token被原安全规则拒绝，改为显式外部原读者；中间一次fixture未接完整controller依赖50通过1准备错误，补原fixture后实际父目录负例1通过。最终两文件53 passed13.87秒、无skip：test_v20_guard_bootstrap_inspection.py／test_v20_guard_bootstrap_preparation.py；新增owner进入／未知查询关闭两项亦覆盖。原53存在旧17准备专项，不与前轮总数累计。

命令由固定Python通过tools/python-v20.py tools/quality_python.py执行上述文件，-q -s -p no:cacheprovider --tb=short --basetemp <TemporaryDirectory>，quality_gate.environment与finally stop_owned／目录清理；具名升级仅普通完整非管理员测试身份，不是SYSTEM。相关五文件format通过；最后新增上下文写法触发SIM117排版，将按原子保存修正，未降低规则。

## 原1820真实资源与安装位置

新CLI实际读取guard-bootstrap-prepared-20261114-1820、plan SHA717fa81479f5fdf9b597f6a6435fad307dfcaf9957220c3524a6d4e80dae42dc，完整部署／1810Guard／1818后台原字节均通过，固定旧计划兼容；没有重新生成／覆写旧资源。

原目标C:\ProgramData\WALLE.RuntimeGuard.V2.Test.20261114-1820的父目录实际被拒绝，使用v20_guard_bootstrap_inspection_worker.py和本轮普通读者原Job，不创建目标。逐级原生有效权限：
- C:\：0x1200ad，所有者TrustedInstaller服务SID，通过原ANCESTOR规则。
- C:\ProgramData：0x1201bf，所有者SYSTEM；包括FILE_WRITE_EA／FILE_WRITE_ATTRIBUTES，原ANCeSTOR_MUTATIONS拒绝。没有改该父目录权限或放宽检查。

因此旧计划只具有源字节／结构有效性，不具备该位置的父目录准入；这是本轮新发现，不将前轮“准备成功”改写为安装通过。

新候选C:\Program Files\WALLE.RuntimeGuard.V2.Test.20261114-1845：
- C:\保持0x1200ad；C:\Program Files为0x1200a9，两个原祖先实际均通过。
- ACTUAL_ORIGINAL_READER_PARENT_ACCESS_CHECKED到达，原读者Job已停止、原根等待退出及成员为空，临时目录清理；不是SYSTEM／OS准入。
- 仍未创建Program Files安装目标，未启停用户服务。

新正常准备资源backend/distributions/windows/guard-bootstrap-prepared-20261114-1845-program-files，installation_ref8220b152f13371d6447c9ebb895d4cf2b9d7f2eff55a3a1ebb1bad7de01f60f6，计划SHAb3915bdc5193e23140ead776b255227f031d4991ae4779aa0f7261c188341c2a，部署SHA3099d61e7de7edc1e3941a47a954b4152efd1904173e2157708d4a687ef1858b。仍绑定原1810Guard和1818后台，task／runtime／checks=null，只为最小Guard启动。

## 尚未验证

安装新目录的实际所有者／完整DACL、受保护复制、SCM固定配置和SYSTEM进程、普通后台→原Guard进程／Token可读性、原来源赋值、WFP／双SERVICE与完整报告交付仍未验证。当前53项和父目录通过都不能打开ready或替代正式部署。下一步完成可审阅的受信安装与普通后台无业务库连接探针，再按本轮具体授权执行实际系统步骤。
