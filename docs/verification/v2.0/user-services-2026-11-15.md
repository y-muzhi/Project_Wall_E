# 用户前后端启动（2026-11-15）

用户明确要求“前后端给我启动一下”。本轮启动普通用户后台和前端供人工试用，不恢复此前暂停的SYSTEM Guard检查，不安装／启动Guard，不触发真实模型或计数，不提交推送。

启动前：8000／5173均无监听，没有现有项目Python／Node服务。按原入口使用既有data/wall-e-v2.0.sqlite，经.venv/Scripts/python.exe -B -X utf8 tools/python-v20.py tools/db-v20.py check-v20 --database <项目绝对路径>/data/wall-e-v2.0.sqlite，实际schema_version200／CHECKED。当前源码db20-r50；未初始化／升级数据库、未清空或替换用户数据。

## 实际启动

正常服务通过Start-Process -WindowStyle Hidden后台启动并保留。后端启动器PID153644，实际监听PID11356，127.0.0.1:8000；子进程设置绝对WALLE_DATABASE_PATH，入口.venv/Scripts/python.exe -B -X utf8 -m backend.app，单worker／无reload。前端node PID41048，127.0.0.1:5173，cwd=frontend，node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 --strictPort，默认代理8000。

本轮正常服务日志位于data/service-runtime-20261115-170926，backend／frontend的stdout／stderr各自文件；它们是用户要求保留的服务运行日志，不是测试报告或应自动清理的临时产物。不得按历史PID直接停进程；后续停止／重启前核对实际端口、进程归属与在途工作。

## 实际检查与可用入口

后端实际日志Application startup complete；Get-NetTCPConnection核对上述两个监听。只读HTTP检查：前端首页200；后台GET /api/v1/requirements 200；前端同路径代理200；实际Vite main.tsx模块200／9691字节，application/app.tsx模块200／28903字节，关键createRoot／Application导出存在。不是只检查磁盘文件或HTTP200。

内置浏览器实际打开http://127.0.0.1:5173/requirements，成功显示需求工作台及原有1条需求、代码开发／测试验收／设置导航。浏览器页已作为用户交付保留；未新建、编辑或提交任何业务内容，未触发模型。无截图、录像或原始测试JSON报告。

前端试用地址：http://127.0.0.1:5173/；后台API基址：http://127.0.0.1:8000/api/v1。本轮不读取或导入.env.local凭据，不导入模型或OS准入；实际AI资格依原门禁，Coding自动执行仍受未完成Guard／环境准入限制。页面可访问与人工试用不等于完整系统验收通过。
