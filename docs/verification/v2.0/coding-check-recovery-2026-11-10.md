# V2.0 Coding 原开发自检恢复验证

2026-11-10 香港时间，master 28a7c9e 的实施工作区。依据 BE 0.17-draft-17 的 7.3.3、7.6.6—7.6.7、APP-CODE-CAPTURE／VERIFY，FE 0.16-draft-16 的 BND-CODE-CHECKS。只用测试进程和临时 NTFS／SQLite，受保护程序准入及 WFP 数据面用测试夹具。

| 专项 | 实际结果 |
| --- | --- |
| test_authenticated_project_check_transfers_input_runs_and_releases_original_job 的 PROJECT_CHECK／PROJECT_CHECK_REJECT | 2 项通过。实际 Guard 管道、Windows LPAC／Job；正常原检查及破损输入保护。 |
| 同专项 PROJECT_CHECK_RESTART | 1 项通过。七项候选 Git 命令及原项目检查完成，注入私有终态凭据后 SQLite 写回丢失。新调度器在准入列表为空、禁止再次连接 Guard 的条件下只补原记录；重复写回无额外改动，原候选和两条只读 HTTP 投影保留。 |
| 同专项 PROJECT_CHECK_CONTROLLER_LOST | 1 项通过。原后端进程真实退出，第二进程通过实际认证管道和原控制方恢复门槛只观察／封闭旧 scope，原 WFP 规则夹具、LPAC profile、Job 及独占目录收尾。无原输出时记 EVIDENCE_INCOMPLETE，退出码和输入完整性仍保留。 |
| PROJECT_CHECK 最新分支与 test_v20_check_runner_bundle.py | 22 项通过。重新验证正常项目命令、私有凭据及 Runner 原闭包。 |

运行入口为 tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider，临时目录由作用域自动回收。原 Guard 进程也已丢失、原资源归属无法证实或外部结果不可核实时继续保留 UNKNOWN。无原派发的本地回收分支另需覆盖故障专项。实际 SYSTEM 部署、业务库和真实模型未执行。
