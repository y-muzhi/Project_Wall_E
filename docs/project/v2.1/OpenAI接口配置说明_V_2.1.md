# V2.1 OpenAI官方接口配置

当前状态（2026-11-20）：2.1本地文档协作已切OpenAI，gpt-6.2-sol/medium、openai-v2，8001/5174，显式代理http://127.0.0.1:7897。单次真实计数/模型/结构通过，DeepSeek保留。见[启用结果](../../verification/v2.1/openai-enabled-2026-11-20.md)。

本接入独立于DeepSeek。现有DeepSeek默认Profile与资源保持，不会因OPENAI_API_KEY存在而自动切换。OpenAI目前支持2.1需求文档协作，未扩展Coding/Testing模型部署。

## 本地密钥

工作区根目录已建立被Git忽略的.env.openai.local：

```text
OPENAI_API_KEY=在本地填写你的密钥
```

只在本地编辑，不发到聊天、不写入项目文档、不传前端。该文件与DeepSeek原有凭据源分开，缺失OpenAI密钥时不会借用DeepSeek密钥。

推荐Profile openai-sol-v1，官方模型gpt-6.2-sol，reasoning medium，官方Responses接口。该模型ID当前是供应方别名，不能称固定日期快照；每次实际返回仍校验批准模型身份。

## 只读准备检查

从工作区根目录运行：

```powershell
.venv/Scripts/python.exe -B tools/openai-service.py
```

默认只核对冻结资源/模型，不读密钥、不发请求、不初始化数据库、不启动或停止服务。可加--database指定现有Schema210数据库只读检查该库OpenAI技术准入。

## 独立真实兼容观察

工具提供--observe分支，一次新槽仅允许1模型请求、最多3个必要整请求计数、0自动重试；不设置额外费用预算。输入输出容量保留程序原生限制。执行前应明确该次真实验证范围及外发载荷，工具默认不执行。

```text
.venv/Scripts/python.exe -B tools/openai-service.py --observe
  --credential-file <本地.env.openai.local路径>
  --slot <工作区data下全新直接子目录>
  --report <docs/verification/v2.1下全新Markdown>
```

仅使用固定合成电影推荐样本及项目通用系统指引/模板结构/输出Schema，向https://api.openai.com/v1/responses/input_tokens和https://api.openai.com/v1/responses发送，不使用正常用户需求或正文。OpenAI计数覆盖整个实际请求含输出Schema，正常计数审计保存真实原文，不伪造8项Token计数。

未知/计数失败/结构拒绝即停止。失败槽、正常input.sqlite及count-audit保留，不重新运行或退款补发；不把原始响应另外导出成测试JSON/日志。观察成功只取得隔离release技术证据，不自动切换当前用户服务或声称产品正式验收。

## 显式服务启用

新供应方同release真实证据获准导入用户库后，--start才可在require_live通过后读密钥并启动原生Schema210。独立命令不负责停止其他服务，端口/锁已占用时拒绝；不要在当前DeepSeek服务占用正常库时重复启动。

```text
.venv/Scripts/python.exe -B tools/openai-service.py --start
  --database <现有Schema210正常库绝对路径>
  --credential-file <本地OpenAI配置路径>
  --port 8001
```

切换服务前核对在途任务并保留同一数据库/用户正文/版本及失败记录；凭据仅加载后端进程。未通过真实兼容不得绕过技术准入。DeepSeek启动方式及旧资源仍保留，可按明确服务维护任务切回，不将供应方切换当作数据库迁移。

## 实现和证据

设计：[独立接入迭代](../../iterations/pending/v2.1/WALL-E.OpenAI官方接口独立接入迭代_V_2.1.md)。
当前代码、实际检查和未验证事项见[实现进度](实现进度_V_2.1.md)与[需求映射](../../traceability/v2.1/需求实现映射_V_2.1.md)。OFFLINE_READY不能当成用户Key权限或官方真实兼容已经通过。

离线实现证据：[2026-11-20检查](../../verification/v2.1/openai-integration-offline-2026-11-20.md)。配置文件位于本聊天独立2.1工作区；同名原项目目录不共用该文件。

## 显式本机代理

若本机连接OpenAI需要已有HTTP代理，在OpenAI命令追加 --proxy http://127.0.0.1:7897。也可为OpenAI后端进程显式设置OPENAI_HTTP_PROXY；.env.openai.local当前只加载Key，不自动加载其余变量。默认直连，不自动继承Windows系统代理/PAC或通用HTTP_PROXY。仅支持无认证的HTTP回环IP和明确端口，计数与Responses同路线，DeepSeek不使用此配置。保持官方HTTPS目的地/TLS验证与0重试，失败不自动换路线。

第一轮直连仅计数连接失败、0模型，不能说明Key无效；修复和离线证据见[本轮观察](../../verification/v2.1/openai-compatibility-2026-11-20.md)。通过代理的新一次真实验证仍需当前授权，不重用旧失败槽。

默认无--database命令显示冻结资源OFFLINE_READY初态。查本机有效准入：

    .venv/Scripts/python.exe -B tools/openai-service.py --database data/v2.1-local/walle.sqlite --proxy http://127.0.0.1:7897

当前返回LIVE_VERIFIED，不读密钥、不发请求。后台宿主data/service-runtime-v21/backend-openai-host.ps1已运行，不要重复启动；维护先核对进程/在途。DeepSeek原宿主backend-ai-host.ps1仍保留。
