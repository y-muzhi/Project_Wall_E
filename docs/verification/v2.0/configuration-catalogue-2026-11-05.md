# V2.0静态配置目录与实际API20验证

日期：2026-11-05（Asia/Hong_Kong）。基线BE0.17-draft-17／FE0.16-draft-16，DRAFT；V1.5提交28a7c9e之后的V2工作区，未提交／推送。本轮未启动／更新用户服务、未操作正常业务库／配置、未调用模型或计数API。

## 已实现与不变量

- ResourceCatalog复用原资源入口，新增冻结code20-r1目录：1个已核对官方ZIP及375成员字节的固定MinGit包引用、3个既有PROFILES身份。12类过滤值全部严格识别；其他10类尚无准备资源，如实为空。不读取ModelProfile凭据，不创建价格／执行器／runner或虚构就绪证据。所有首版项ready=false。
- prepare-code-catalogue.py采用显式新release_id，不覆盖资源目录；完整写回并校验manifest／options后才最后原子更新程序pin。失败保留既有pin；临时目录仅精确自有范围清理。目录数据无密钥、供应方访问路径或主机真实路径。
- code20-r1 manifest SHA256：e951be6534e5a97e5645524fc714afa435155aed7f75eb942d8888b587b74d61。条目来源、Git包manifest、实际Git入口摘要及Profile身份均受验证；确定JSON／未知字段／重复及排序／声明覆盖／格式版本严格检查。
- 实际GET /api/v1/code-configuration-options?kind=...&page=...：原HTTP boundary、空请求体、无幂等头，kind必传，每页20，保留真实越界空页，按option_id顺序。读取持有原数据库lease；151拒绝且不初始化200。资源失败返回503 CONFIG_NOT_READY／Q20-CONFIG，存储失败返回503 STORAGE_UNAVAILABLE／DATABASE，不伪装空目录。
- 前端实际WalleApi.codeConfigurationOptions及精确DTO。抽出原WalleApi分页为共用readPage，数字资源ID与目录字符串ID均复用同一计数／页码／唯一性核对；目录另验kind及顺序。其他尚无资源的类别无伪造DTO或通用秘密字段通道。
- service注册新增路径后另发布不可覆盖db20-r7，manifest SHA256 88dcb99509f6184f5289bffc403f6043130a43f9ada9fdb3f962c16604781860。r1—r6保留。实际V2路由现为8条。

## 实际检查

环境：Windows11 x64，项目.venv Python3.13.5／固定SQLite3.54.1、Ruff0.17.3；Node24.15.0及项目锁定TS／Prettier／Vite。隔离临时目录、脱敏环境及quality_python／quality_node阻止真实网络。测试产物已清理，只留本Markdown；正式JSON目录及Schema发布资源是产品资源。

- tools/python-v20.py tools/prepare-code-catalogue.py --release-id code20-r1及--verify：成功，真实源字节核对通过，无Git执行／原生探测／外部调用。
- tools/python-v20.py tools/schema-v20-release.py --release-id db20-r7：成功。
- 首次六文件组合：78项中65通过／13失败，231.19秒。失败均属新增夹具对现有契约的错误预期：canonical_input要求对象而非数组、V2外部错误码为INVALID_INPUT、版本记录在schema_migrations而非PRAGMA user_version。已修夹具，不改正确产品行为；该轮其他45项（身份、原键HTTP、启动、实际发布及Schema release）全部通过，包括当前r7实际CLI维护／发布路径。
- 修后仅重跑受影响test_configuration_options.py：33通过，66.74秒。覆盖真实目录、正确摘要但非法投影、秘密字段、假就绪、Profile来源、重复／顺序／漏项、损坏／缺失、不可覆盖发布、12种过滤／越界、非法参数前不读数据、空Body／幂等头、配置／存储失败及151不变。未将两次结果描述为一次78项全过。
- 新前端与既有身份两个文件：14通过；随后全套492通过，5.96秒，strict类型1.13秒、npm run format:check对应锁定检查1.91秒、临时生产构建1.03秒均成功。构建输出随临时根清理，正常dist未修改。
- 176个backend/app文件Ruff格式检查、新模块lint及git diff --check通过。既有httpx弃用警告保留；主包体积提示不当成功能失败。

## 边界

没有新增页面／按钮／布局，因此未重跑浏览器UI。前一身份批次Chrome15组及双标签证据仍为历史，只用于已有组件，不移作本批API20的端到端结果。本批通过是实际ASGI接口与前端离线调用验证；未称浏览器连接后端完整产品验收。

其他10类目录资源、配置版本发布与引用资格、授权、完整设置UI及任务链路尚待实施。Model／Git首版元数据并非完整Windows／执行器／模型价格准入；未将存在包文件或源码当可执行证据。正式两份设计未自动修改。
