# H11代码规范与旧流程清理

日期2026-10-30；HEAD8c3f025加已有H08／H10及本轮改动。用户授权代码整理、持续规则及无必要旧流程删除；没有真实调用、用户数据／服务、提交推送。

## 实现

- AGENTS新增持续开发规则；前端Prettier3.9.10锁定开发依赖，src的TS／TSX／CSS统一格式；现有strict／unused类型检查保持。
- Python新增独立requirements-dev.lock固定Ruff0.17.3及ruff.toml，仅backend/app格式化；125文件AST前后完全相同，115文件排版变化、10不变。此等价核对在旧确认模块删除之后进行，不将删除冒充格式等价。
- 统一检查新增format及python-format步骤，CI安装独立开发依赖；旧业务依赖版本未升级。资源、来源、用户数据库与生产dist不格式化。
- 删除无生产调用的confirmed_response.py及专属test_confirmed_response.py；历史test_output_evidence去掉该废弃对象的无效mock，当前事实确认仍走card_commands.submit→fact_confirmation.apply_confirmed_action。正式BE实现定位及旧服务路由数注释同步。

## 路径核对与保留原因

生产入口service→GuideWorker→orchestrator.execute_guide_run→collaboration_execution；后者使用orchestrator._transport／_parse，因此这些函数不是死代码。执行入口明确拒绝非collaboration_v1，不存在因文件共存而自行回落旧AI执行流程。

静态AST导入闭包以service及__main__为根，删除前126模块中113可达；未达模块除包初始化外，confirmed_response确无业务调用，已删除。local_credentials由启动工具调用，framing_probe由技术观测工具调用，保留。context_builder／counted_context仍由audit_repository、counting_journal、production_ai、practical_usage和保存快照投影调用，不能按年代删除；固定模型资源及历史来源保持。这是静态核对，不声称证明所有动态路径无冗余。

## 验证

1. [前端整理检查](quality-gate-2026-10-30-202632-169994.md)：8自检、前端格式、420测试、类型及临时构建通过。
2. [双格式门禁](quality-gate-2026-10-30-202907-443013.md)：8自检、前后端格式通过。
3. backend/app／tools／backend测试及正式V1.5设计内已无confirmed_response引用。全部Python整理前后AST相同；旧模块的删除依据调用关系及当前业务专项，不按AST等价证明。
4. [当前卡片、执行和服务生命周期专项](quality-gate-2026-10-30-202938-124711.md)33项通过，172.92秒，临时根清理成功；实际覆盖三个当前V1.5文件，未全后端重跑。旧V1.0历史输出测试未整套重跑，不称全部历史测试通过。

未执行真实供应方、浏览器或远程CI；格式化不能证明语义效果或易用性。工具依据：[Prettier安装及检查](https://prettier.io/docs/install)、[Ruff格式化](https://docs.astral.sh/ruff/formatter/)。

143个前端源文件纳入格式检查；现有275个npm依赖包条目逐项对比保持，只新增固定Prettier。后端运行依赖锁文件不改，Ruff放独立开发锁文件。git diff --check通过（换行提示不是检查失败）；清理结果与链接检查追加在后。既有Starlette/httpx弃用提示保留，未升级业务依赖。

最终文档本地链接检查：当前改动／新增Markdown共456条，缺失0（不验证远程URL及标题锚点）。
