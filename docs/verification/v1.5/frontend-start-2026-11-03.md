# 最新前端启动与地址核对

日期：2026-11-03（Asia/Hong_Kong）。用户要求提供可用前端地址，授权启动最新前端。初查5173未监听、8000在监听；保留后端，使用现有Node及锁定Vite依赖，在frontend目录以Start-Process／WindowStyle Hidden启动node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 --strictPort，PID14052。该进程是用户要求持续访问的前端，不属于应清理的临时测试服务；停止前须重新核对PID与归属。没有后端重启、静态dist构建、业务写入、模型／计数或提交推送。

可用地址：http://127.0.0.1:5173/requirements。页面HTTP200、当前navigation.tsx／router.ts有效导出及source map内容等于磁盘，最新固定图标及直接返回逻辑已加载。独立Playwright实际工作台显示W品牌、主导航图标、真实需求1列表及分页，没有启动占位或页面错误。现有列表代理/api/v1/requirements HTTP200；首个手写page_size探针违反接口参数契约返回422，核对现有调用后使用正确接口确认成功，不据探针错误修改产品。

验证浏览器walle-frontend-access-20261103已close，专属临时快照及Console在已校验绝对路径下清理。未新增全量测试、业务交互验收或供应方证据；前轮43项／浏览器等仍按原日期。5173前端保留运行，8000正常服务及数据保持。
