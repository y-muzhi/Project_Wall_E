# V2.0 用户服务启动（2026-11-13香港00:50）

用户本轮明确要求打开前后端供使用；仅启动、独立新库初始化及只读可用性检查。保留既有修改与旧库，不迁移151／旧版库、不提交推送、不调用模型／计数，不安装SYSTEM／WFP或伪造资源准入。

## 启动与数据

起点8000／5173无监听。旧data/wall-e-v1.5.sqlite元数据151，wall-e.sqlite为1—4；未修改。独立新建data/wall-e-v2.0.sqlite（Schema200／当前db20-r44）。正式初始化包data/v20-initialization-20261113-user-service保留，禁止作为测试垃圾清理。首次沙箱调用被项目工具以APPCONTAINER_OPERATOR_REJECTED拒绝；无目标落盘，改用获批的当前Windows用户调用成功。

命令（项目根目录；DB与package传入实际绝对路径）：

```powershell
.venv/Scripts/python.exe -B -X utf8 tools/python-v20.py tools/db-v20.py init-v20 --database <项目绝对路径>\data\wall-e-v2.0.sqlite --package <项目绝对路径>\data\v20-initialization-20261113-user-service --maintenance-window-confirmed
.venv/Scripts/python.exe -B -X utf8 tools/python-v20.py tools/db-v20.py check-v20 --database <项目绝对路径>\data\wall-e-v2.0.sqlite
```

实际分别INITIALIZED／CHECKED。今后复用现有库，不能重新初始化或覆盖。

当前用户服务通过Start-Process -WindowStyle Hidden后台启动并保留：后端启动器PID440356、实际监听PID391372，127.0.0.1:8000；前端node PID440368，127.0.0.1:5173。此轮归属为用户明确授权的常规服务，不是应在检查后清理的测试进程。启动时仅子进程继承绝对WALLE_DATABASE_PATH，后端`.venv/Scripts/python.exe -B -X utf8 -m backend.app`；前端cwd=frontend，`node node_modules/vite/bin/vite.js`，默认代理8000。data/service-runtime-20261113/*.log为服务运行日志，非测试报告。后续启停前重新核对端口归属和在途任务，不能仅凭历史PID停进程。

## 实际检查

后端日志startup complete；当前用户Get-NetTCPConnection证明上述两个监听。隔离沙箱连接用户localhost出现WinError10013，改为获批当前用户只读检查：前端首页200，实际main.tsx转换9691字节、application/app.tsx转换28903字节且有关键导入／导出；后端`GET /api/v1/requirements`与前端同路径代理均200，成功空列表。未以HTTP200代替页面检查。

按Playwright skill使用已安装CLI及独立Chrome：需求工作台成功空态“暂无需求”，主导航“代码开发”点击后显示“选择需求和文档以进入代码任务”；控制台Errors0／Warnings0。首次脚本误找英文Coding标签，关闭清理后按实际中文按钮重验通过，没有产品源码修改。两次临时浏览器、配置、快照和日志均finally关闭／清理，只保留本Markdown。

## 可用范围

用户访问http://127.0.0.1:5173/，代码入口为左侧“代码开发”；新库无需求，需要用户创建需求／文档后进入任务。后端API基址http://127.0.0.1:8000/api/v1。当前未导入.env.local凭据、未获得新库协作模型真实准入，AI调用不可用；Coding原生执行同样受未完成资源／安装准入限制。页面与手工能力启动不代表真实模型、仓库注册、受管执行或完整产品验收通过。没有创建演示业务数据或替用户触发请求。
