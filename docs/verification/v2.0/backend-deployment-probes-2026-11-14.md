# 普通后台安装读者与Guard只读连接探针验证（2026-11-14）

## 代码与环境

本轮香港18:21开始的三小时任务，HEAD28a7c9e13c73a9d386081a6dd894244b51746a45，保留原517行工作区改动。正式BE0.17-draft-17／FE0.16-draft-16仍DRAFT；未改APP、Schema200、db20-r49或模型资源。Windows原普通用户、Python3.13.5／固定SQLite3.54.1；使用独占临时目录和原进程句柄，结束清理。原后台入口增加显式部署探针分派，正常端口模式保留。

## 实际检查

- 通过tools/python-v20.py及tools/quality_python.py运行test_v20_backend_guard_probes.py与受影响取消一项：19 passed，3.13秒，无skip。覆盖固定普通EXE限制、互斥参数、禁止业务导入、控制管道完整STOP／错误输入／EOF边界。
- tools/windows_backend_package.py采用锁定临时构建工具及--build-frontend，生成prepared-20261114-1900-probes，实际专用EXE探针／固定运行库／前端构建及全包读回通过。manifest39f6285a53eddffe71b3674fa55a3f794db637e8dff2c2bbf92f7d22adf577cf，sources94d0a454c9c62aa00c3607e36fccfb1156a5348573687e18d8a83b641f8a79cb；1799文件265796997字节。旧1818包不覆盖。
- v20_backend_guard_probe_worker.py实际运行上述后台--hold-installation-reader，核对原PID／创建时刻／image／普通非AppContainer Token，锁住完整程序包，以原Token核对Program Files目标祖先，STOP正常退出并验证全包锁释放。错误RUN、错误SHA、与--port混用分别拒绝。会话57351退出0。
- 同一worker另用--timeout-case实际等待固定300秒，不替换时钟；实际到期拒绝／进程退出／包锁释放通过，会话10914退出0。
- 实际冻结后台--verify-guard指向本轮尚未安装的ref，返回1／BACKEND_DEPLOYMENT_PROBE_REJECTED，会话23353结束。只证明未安装时拒绝，不证明正向SYSTEM连接或任务准入。

## 新启动输入与边界

guard-bootstrap-prepared-20261114-1905-probes绑定原Guard1810与新后台1900；计划5defd3d420054ad1e533f80c57ead6701b7d275e50b9978e4eccb6054330d3cf，部署5c4b3cda489d1c4f95ae920eaebc1a4decd22b54c3d3e8c150740f772a2e41cf，ref ffac49bed3200a391a19cf7b1480b67d9bc41f17899fc21e329957aced5d33e3。目标C:\Program Files\WALLE.RuntimeGuard.V2.Test.20261114-1905未创建，task／runtime／checks=null。

尚未执行SYSTEM安装／SCM启停、实际Guard正向连接、WFP或任务／报告交付准入；无用户库／用户服务更新、真实模型／计数、提交推送。正常后台及浏览器受影响回归待本轮续做。当前正式系统授权尚未请求，先完成专用安装工具及固定请求。

## 原因与修复

原普通读者只存在于Python测试进程，不能代表固定后台程序；现复用原专用后台入口、全包租约、Original Process／Token和注册Guard客户端，不另建业务链。五分钟固定寿命及独立STOP使安装读者不会长期运行。上述实际运行不产生正常业务记录，原始输出仅留工具会话，临时目录由finally清理；不留JSON测试报告／截图／日志。

 
## 本轮新包实际前后端回归

会话72288：v20_frozen_backend_http_worker.exercise使用新1900冻结后台、独占临时新库及43194端口，首页／实际JS字节与manifest逐项一致，requirements／code-execution-profiles／code-configuration-options三个实际GET均200。以原PID核对每次监听归属，不接用户服务。

同一实际后台由固定1650浏览器包经原CHECK_DRIVER独立真实LPAC／Job访问当前应用，application场景内层1 passed118.89秒／外层1 passed120.95秒，ACTUAL_ISOLATED_BROWSER_APPLICATION_CHECKED。临时库llm_uses／code_tasks均0，原进程退出和监听释放通过，临时资料清理。场景仍使用显式OS准入／WFP测试端口，不是正式SYSTEM、真实WFP或双LPAC SERVICE证明。正常启动改动的页面及接口回归已完成；未对无关页面重复全量验收。
