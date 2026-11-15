# V2.0精确页面直达壳验证

日期：2026-11-05；BE0.17-draft-17的BND-CODE-SPA；前端页内职责仍归FE0.16-draft-16。当前28a7c9e之后的未提交V2代码。

## 实现范围

backend/app/frontend.py只增7个明确GET／HEAD页面壳：需求文档代码任务列表、代码任务详情、代码设置、Testing入口／任务详情／计划及测试设置。仍只返回显式已配置构建目录的index.html，并仅开放assets子树；无通用catch-all、源码／环境／数据目录访问。旧需求壳、API-only工厂及缺构建拒绝行为保持。

页面壳不认定实体存在，也不代替ApplicationRouter的规范ID／query验证及真实API归属核对。因此非法页内参数仍先返回HTML，由前端负责明确失败；本轮没有新增页面组件或假业务对象，不把返回200当页面交互完成。

## 实际检查

项目Python3.13.5／固定SQLite3.54.1，quality_python阻断外网／正常用户数据与凭据读取；本轮专属临时151测试库及index／asset夹具，ASGITransport真实应用工厂／lifespan，无HTTP服务监听。夹具只验证服务器页面壳，不冒充实际前端生产构建或浏览器验收。

- 首次默认隔离环境运行360秒超时，无可用通过结果。只读CIM确认原命令与独有.tmp/w2-catalogue-4t4ephrl；一次人工清理脚本错误硬编码SID前置校验不匹配，因此在OpenProcess终止权限／TerminateProcess之前被拒绝，没有执行终止。随后原测试由超时结束，核对相关原进程不存在、该专属临时目录不存在；用户服务未动。
- 经正常审批用普通测试权限重跑同一受影响两个文件：test_v20_frontend.py及test_frontend.py，5通过／26子场景，16.32秒。没有改系统网络隔离或绕过审批，也未将默认环境超时笼统归为既有Node／Vite故障。
- 覆盖7条新页面壳及多组ID／query、GET／HEAD正文与Content-Length、no-cache、POST拒绝、真实原API JSON与assets、未知API／页面、数据／源码／环境／越界assets404；API-only模式无伪页面，旧3项同时通过。
- 新改源码采用项目锁定Ruff stdout格式／import修正后原子保存；最终181个backend/app格式、相关模块lint、git diff --check及r7 pin检查通过。前端src／依赖／dist未改，不机械重跑492项或构建。
- 原服务／正常数据／.env.local没有读写，未调用模型或计数；所有本轮临时页面／库已清理，不留JSON／日志／截图。未执行用户服务启动或更新。

## 未完成范围

ApplicationRouter尚须接完整V2页面、真实实体和严格query；本轮不算代码／测试设置、任务或计划页面完成。浏览器空态／状态／按钮／布局检查应在相应真实前端单元完成，不能拿后端壳检查替代。V2实际业务API仍仅8条；7条页面壳另计，不混为业务入口。
