# OpenAI单次技术观察

状态：PREPARING。仅合成样本，最多1模型请求/3必要整请求计数，0重试；不使用真实用户数据，不切服务。

Release-SHA256: 32999ee29f7253d93104e42801d0c55e98d4ca13815e6d9ebe2be2bd872a1df7
Profile-SHA256: 435677eaccadab44180c852a2e1fdfac5b0ec390bfdddbc17b78e3c72ab867cf
Input-SHA256: 8f57298dfd37bc85cbb759b0e1a7eb3869865edce8ee6307b4eef09b607fcaf5

COUNT_INTENT 6ca5478e15c64f896f0fd113d060db601eefb7ce2921f019018616e73f3f2a04

结果：NOT_PASSED；不得重跑该槽/自动补发，保留正常审计核对。

实际计数尝试=1；实际模型尝试=0；SDK请求SHA=None；正常数据库及计数审计保留在本槽。

## 2026-11-20事后核对与代理修复

session25538已结束exit1；原生审计记录计数1次、模型0次、0重试。计数finished.phase=INTERRUPTED、failure_reason=TRANSPORT_ERROR、http_status=null；Run1 FAILED/CONFIG_INVALID，尚无LLMUse。没有收到HTTP状态，不能推断为密钥无效、模型无权限或配额不足；没有导入正常LIVE/切服务。失败槽和正常审计保留，不再次运行该槽。

仅只读检查网络配置：无通用代理环境变量，Windows系统代理开启，指向127.0.0.1:7897；7897监听PID9260。现实现trust_env=false为直连，该路由差异可能相关，尚未通过真实新路由验证，不冒充根因已实测确认。

已先在独立迭代追加规则，再新增openai_transport.py及显式OPENAI_HTTP_PROXY/CLI --proxy。默认直连；仅允许无认证/路径/查询/片段的HTTP回环IP+端口；不自动继承Windows/PAC/通用HTTP代理，不改DeepSeek。固定官方HTTPS目标、TLS证书验证、无重定向、0重试；计数和Responses同工厂，不改变原生请求/计数/Profile/冻结资源/准入证据。安全诊断只记异常类型，不输出异常自由文本/正文/密钥。quality_gate.environment额外移除新代理变量，避免离线运行继承路由。

离线实际命令：固定SQLite + quality_python，test_openai_transport.py（当时5项）、test_openai_primitives.py、test_openai_counting.py、test_openai_service.py，-q -p no:cacheprovider --tb=short --basetemp临时目录。29 passed，14.31秒，cleanupTrue；另新增DeepSeek代理隔离单项1 passed/5 deselected，1.20秒，cleanupTrue。工具环境隔离专项1项通过。595 app格式、受影响文件Ruff F/I/B及diff检查通过；准备检查--proxy输出OFFLINE_READY/0凭据/0调用/0启动/transport=local_proxy。前端本批未改，无必要重复页面检查。

正常服务仍8001/PID28476、5174/PID311404；正常库读取1需求/1文档/1Revision/6Run/3Use、在途0。没有修改真实用户正文、重放Run或迁移数据库。准备的OpenAI宿主增加显式本机代理，但未执行。第一轮失败许可结束；新候选槽data/openai-compat-02、报告openai-compatibility-2026-11-20-v2.md尚未执行，须单独确认经本机代理的同目的地/同合成载荷/1模型/最多3计数/0重试范围，不追加费用预算。通过后的2.1服务切换授权仍保留。

技术依据：[HTTPX代理](https://www.python-httpx.org/advanced/proxies/)、[环境变量](https://www.python-httpx.org/environment_variables/)。官方资料仅说明路由机制，不是本机代理到OpenAI的实测成功证据。
