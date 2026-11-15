# V2.0 独立 Testing 配置及明确授权

2026-11-10，master 28a7c9e 的工作区增量。正式 BE OBJ-TEST-POLICY、APP-TEST-ASSETS、SHR-TEST-ERROR、API01—05；FE BND-TEST-SETTINGS。Schema200 最新不可变源清单 该单元独立资源 db20-r34，摘要 2cfd9a3019435a47674642466ff94c4116e51ceb919a560e9e776d4daff17c04。计划单元后当前 pin 为 db20-r35，r33／r34 保持原字节。

- `tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider backend/tests/test_testing_policy_api.py backend/tests/infrastructure/test_v20_command_http.py`。隔离真实生产 ASGI 工厂、私有 SQLite、实际本机批准者解析，资源目录使用已登记身份形状夹具。9 项通过，35.81 秒。核对同名并发分配、正安全整数、资源归属、原成功／失败／关闭／冲突回执、原请求不随目录变动重算、空页和分页、批准注入、PACK_VALIDATION 零预算与没有任务／LLMUse／运行记录副作用。首次专项发现缺失配置的原 404 未传显式 null details，修正后重跑通过。
- 当前生产目录没有已发布的独立执行器、受测目标或 Testing driver，因此返回实际阻塞原因。测试目录只在隔离夹具内提供，不能用于正常服务、执行授权或部署验收。独立测试计划、测试包、首次绑定和执行仍待完成。

- Chrome 隔离 SPA，`tools/verify-v20-command-recovery.py --probe testing-settings` 在 360／1280 视口覆盖成功空、缺登记选项、完整选择／限制、取消后保留输入、发布版本、实际读错保留旧内容、筛选无结果、包验证零预算及授权响应丢失后的原结果。请求计数为一个配置和一个授权，临时浏览器及输出已回收。早次发现窄屏公共设置分区类隐藏入口，改用可换行操作条后复跑通过。生产未发布独立 Runner；创建流程使用隔离 HTTP 目录夹具。
- 页面入口 /settings/testing，采用同源原回执账本，配置草稿和所选 ID 在会话内恢复；授权／资源未就绪与空态分别展示。无模型配置可直接编辑，复制已有版本时可保留或移除其固定模型绑定；新增模型绑定选择器待真实模型／价格资源和 UI 续批。
- 同一浏览器专项扩展到草稿刷新恢复以及 1024／1920 宽度的计划目录布局，隔离运行通过，原计划生命周期另见计划专项。
