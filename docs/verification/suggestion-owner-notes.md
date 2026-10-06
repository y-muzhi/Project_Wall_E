# 2026-10-06 建议批次控制器与正式事务联调

来源已重新核对 FE 584–612、DT-OP12–14、5.5批次失败/未知、BND-SUGGESTIONS，BE OBJ-BATCH/SHR-PATCH、APP-BATCH-QUERY-C01完整读取模型、CMD-C01–03和I20–23，以及批准D-004的补丁/错误详情/定位。完整设计原文没有修改。

`frontend/src/suggestions/batch-owner.ts` 持有一个批次的完整实际读取、每项原编辑文本、唯一不透明I21/I22/I23意图与确认回执。批次所有写入串行；单项尚未确认时不允许最终命令。EDITED原Markdown不trim，不合法Unicode仍留本地原稿；行编辑仅cells JSON及原列数，DELETE不能EDITED。实际状态/占用/正文版本控制许可，终态只读。PATCH_INVALID保旧成功决定及编辑内容；安全建议错误只对应所属条目。TARGET_STALE/版本冲突禁直接完成，保留放弃入口，不自动合并或重建。

未知先完整详情及原I20查询后原请求重放；GET相同状态不是本次成功证明。读失败/隐藏（包括读取结果通知期间隐藏）不重发。暂时STORAGE_UNAVAILABLE/INTERNAL_ERROR及REQUEST_IN_PROGRESS保原意图。正向回执核验不可变目标/来源/操作/原文、原编辑内容、批次/完整文档身份和版本；之后失败保CONFIRMED，重试只读。只有实际批次与完整父级采用成功才清对应编辑草稿，其余输入不丢。普通加载失败保整个旧批次，不伪造空批次。

12新增Node端口检查，最终 `frontend-2026-10-06T06-15-03-941Z.json` 为240前端检查/TypeScript通过，190候选输入不变。早期239项通过的 `frontend-2026-10-06T06-10-49-393Z.json` 保留；首次直接typecheck调用给了不存在的npm-cli路径，随后实际npm命令与完整验证成功，不当作产品失败或成功。

真实编译诊断 `suggestions-owner-browser-2026-10-06T06-14-55-847Z.json` 通过。私有 `SuggestionFixtureWorker` 仅 `--seed-suggestion-fixture` 生效，接受新鲜output/playwright/api-walle-*.sqlite，互斥其他前置且剥离真实模型配置。实际I02/I05/人工草稿保存完成得到CURRENT2/v2及表格26；命名I14 MODIFY前置利用实际冻结权限及真实基线，先正式验证全部五种补丁，再持久化完整批次/单项及已完成来源关系。不构造LLMUse/trusted_output，不调用C07，不能冒充真实建议生成或模型效果。其后I20/I21/I22/I23、幂等、正文/身份/来源与查询全为正式生产代码。

批次1：EDITED两块原文真实PATCH_INVALID，原稿/旧PENDING/正文保留；规范单块回执丢失，隐藏和真实读失败不重发，原键恢复。另一单项正向回执后采用失败仅仅读恢复。替换、前插、后插、删除、表格行编辑全部决定前CURRENT完整不变；I22丢200后实际正文v2→v3，原键恢复一次应用。未选表格行逐字同真实保存基线，未改区块完整元数据不变，替换保原ID和创建来源、删除原块7，新增两块27/28/next29来源AI/SUGGESTION_BATCH1，用户编辑块/表行来源USER/SUGGESTION_BATCH1。

批次2：五项全拒绝，I22丢200恢复COMPLETED/NO_CHANGE/applied=null，CURRENT全文/元数据/版本/时间逐字不变。批次3：一项EDITED后I23丢200恢复DISCARDED，保该编辑决定与4项PENDING，完整CURRENT不变。15次prepare/19次发送，包含一次真实422和4组同键/同输入200重放；complete只有base版本2或3，discard无Body/Content-Type。四组冻结data逐字段等价；其中两组字段顺序不同但完整数据相同。

原失败 `06-10-38-966Z` 将表格行空间写死，实际Crepe按列宽对齐，改比较真实基线原行而不是削弱保持原行要求。`06-12-22-507Z` 把JSON属性顺序当数据变化，测试代理require拒绝了已冻结的原回执，改为排序对象键的完整深比较并记录顺序差异；没有修改正式API字段/断言正文或事务效果。上述证据均保留。

正常关闭2需求/2文档/1版本/0评论/5Run/0LLMUse/3批次/15建议，服务退出0；生产后端未改，730后端仍是历史范围。此专项调用编译控制器及实际接口，**尚未证明产品SuggestionPanel、纵向Markdown/表格对照、目标DOM定位、确认弹窗/固定操作区、统一AI父级或根产品构建**。后续完整接入这些交互并另做浏览器证据。373/P8、Provider预算兼容和真实效果仍开放，未发生付费调用。
