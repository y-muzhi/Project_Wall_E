# 模板标题层级调整专项记录

日期：2026-10-18。对应TPL-003。最终规则为删除原首行H1，其余原H2→H1、H3→H2。下方首次结果保留为历史，更正后结果见末节；CTX-002仍为设计草案。

## 首次执行与结果（已被用户更正替代）

- 源文件先修改，发布采用副本new-requirement@v3，resources/v6仅包含模板、元数据和新建目录。源与采用副本均85914字节，SHA-256为db8274fd525d5da109aa46890bd6fd70f48f4941d812d34f689c4e6264eae235。
- 50个标题中H1=1、H3=9、H4=40；只改变49行的一个#标记，标题名称、顺序及所有其他行保持。214份既有resources/v1—v5、计数资源、原始设计与批准来源SHA-256与本轮前一致。
- 后端：.venv/Scripts/python.exe -X utf8 -m unittest backend.tests.infrastructure.test_full_template backend.tests.infrastructure.test_context_layout -q，12项通过。覆盖当前源与采用副本、新旧标题合同、历史模板、六任务v2／v3两版完整模板使用原预算、新资源篡改拒绝、隔离创建冻结及既有上下文往返／计数同文。首次组合即通过；asyncio输出两条慢任务诊断，非测试失败。
- 前端：node --test tests/requirements.test.mjs，7项通过。表单使用当前新建目录、校验、幂等／未知结果及读取行为保持。
- npm run build：TypeScript及Vite生产构建通过，1238模块，主资源index-Chci-7J3.js。保留既有大于500KB chunk提示；没有安装或升级依赖。
- .venv/Scripts/python.exe -X utf8 tools/ai-service.py，不带--start：离线准入和资源加载正常，完整模板预算仍65536／131072／8192；未读取密钥、未打开业务库、未请求Provider。
- git diff --check在直接改动源码及源模板范围通过。新增资源Manifest和目录按固定摘要加载；最终4份文档的21个本地链接和尾空白检查通过；214份历史文件哈希再次一致，新发布3份资源的Manifest条目一致。

## 服务与业务边界

检查时8000和5173均无监听进程。本轮更新源码和生产前端产物，没有额外启动或重启服务；服务下次正常启动即加载新目录。没有调用真实模型、代创建需求、提交答案、修改已有正文或迁移业务数据库。

新建NEW默认v3，历史NEW v1／v2及CHANGE v1保持对应资源。仅发布模板版本，不改Function／Prompt／计数资源；新模板继续使用现有完整模板初始化v7和其他任务v5。

## 未覆盖与留存

未进行真实浏览器／Crepe交互或实际用户库创建，未执行Provider token计数或模型效果评测，不恢复全项目验收。相关测试使用隔离临时库与临时资源副本，按用例清理；不留测试JSON报告、截图、录像或原始日志。生产dist属于正常应用产物，保留。

## 用户更正后重新验证

最终指令为删除首行、其余各级标题提高一级；从原始v2生成v4，而不是在此前已下调的v3上直接提高一级。保留冻结v6发布，新增resources/v7，当前新建目录切换new-requirement@v4；历史v1／v2／v3可精确恢复，用户正文不迁移。

- 静态核对：源与采用副本85752字节且摘要一致（7e73b764207aac74f43b70996c2b84ce68e8233f2ccf161a95f613e653e0bc66）；49标题为H1=9、H2=40，共321个区块；相对v2仅删除首行及49个#。新Manifest摘要6a505726af659b83659fa73aa4355b88477d2fe9040b06633102fd33c4142eda。
- `.venv/Scripts/python.exe -X utf8 -m unittest backend.tests.infrastructure.test_full_template backend.tests.infrastructure.test_context_layout -q`：12项通过，25.370秒；覆盖v4目录、源与锁定标题、历史v3保留、v2／v3／v4六任务预算、新发布篡改拒绝、隔离创建与上下文往返。两条asyncio慢任务诊断不影响通过。
- 前端目录下`node --test tests/requirements.test.mjs`：7项通过。
- 前端目录下`npm run build`：TypeScript和Vite通过，1240模块，主资源index-CCRBJ42y.js；保留既有大于500KB chunk提示。
- `.venv/Scripts/python.exe -X utf8 tools/ai-service.py`：离线资源准入通过，完整预算仍65536／131072／8192；未带--start，未读取密钥、打开业务库或请求Provider。
- `.venv/Scripts/python.exe -X utf8 tools/cleanup-test-artifacts.py --dry-run`：JSON=0、screenshots=0。

- 最终静态收尾：218份既有resources/v1—v6、计数资源、原始设计及批准来源SHA-256与本次更正前一致；新发布3份文件均匹配Manifest。4份导航／迭代／验证文档的23个本地链接及尾空白检查通过；直接改动范围`git diff --check`通过。

本次未启动／重启服务、未操作正常业务库、未调用真实模型或浏览器；仅使用自动清理的隔离临时库和资源副本。
