# OpenAI单次技术观察

状态：PREPARING。仅合成样本，最多1模型请求/3必要整请求计数，0重试；不使用真实用户数据，不切服务。

Transport: http://127.0.0.1:7897

Release-SHA256: 32999ee29f7253d93104e42801d0c55e98d4ca13815e6d9ebe2be2bd872a1df7
Profile-SHA256: 435677eaccadab44180c852a2e1fdfac5b0ec390bfdddbc17b78e3c72ab867cf
Input-SHA256: 8f57298dfd37bc85cbb759b0e1a7eb3869865edce8ee6307b4eef09b607fcaf5

COUNT_INTENT 6ca5478e15c64f896f0fd113d060db601eefb7ce2921f019018616e73f3f2a04

结果：NOT_PASSED；不得重跑该槽/自动补发，保留正常审计核对。

实际计数尝试=1；实际模型尝试=0；SDK请求SHA=None；正常数据库及计数审计保留在本槽。

## 2026-11-20事后核对及诊断修复

本轮命令已exit1：经显式本机代理，计数1次、模型0次、0重试。正常计数审计phase=FAILED/failure_reason=HTTP_STATUS/http_status=400/provider_error=null；没有导入LIVE或切换用户服务。400响应体在当时适配器未留存，既有记录无法恢复具体拒绝参数，不把推断写为根因。

已先在独立迭代写清诊断规则，再修复openai_counting.py：非2xx复用既有有界_http_error脱敏投影，OpenAI分类，原计数Journal保留code/param/有限脱敏message/request_id；消息不输出控制台或验证报告。最多16KiB响应、全量脱敏后截断2048字符，非JSON/过大/流读失败仍保留已收到HTTP状态。没有改变计数请求、模型请求、Schema或冻结资源。工具--count-limit允许只降低为1/2/3，用于以后明确授权下的剩余次数限制，不自动补发或复用旧槽。

离线命令：固定SQLite/quality_python + test_openai_errors.py、test_openai_primitives.py、test_openai_counting.py、test_openai_service.py，-q -p no:cacheprovider --tb=short --basetemp临时目录。30 passed/15.55秒、cleanupTrue，覆盖错误code/param/请求ID、凭据跨截断边界、quota分类、非JSON/过大/读失败状态保留、原C01停止并落正常Journal。新增工具上限后CLI三项再通过10.58秒、cleanupTrue；Ruff F/I/B、595 app格式与diff通过。没有第二次发送本轮请求。

已复核[官方计数参数](https://developers.openai.com/api/reference/resources/responses/subresources/input_tokens/methods/count)：当前reasoning/text/truncation均有登记；只作字段名静态依据，不代表具体Schema/模型权限已通过。没有凭猜测删除reasoning、替换模型或放松结构规则。

当前两轮累计计数尝试2/模型0；首轮TRANSPORT_ERROR、次轮HTTP400，均结束。下一步需新的明确诊断验证授权，仍只同官方目的地/固定合成载荷/本机代理、最多合计3计数/1模型/0自动重试；可由用户另行明确允许“计数明确参数错误→修复后在剩余次数内复验”，其他失败未知即停止。未获该新边界前不再请求，原成功后切服务授权保留。候选新槽compat-03；不得重跑compat-01/02。现有DeepSeek服务保持。
