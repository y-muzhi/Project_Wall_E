# V2.0 原生权限决定验证

日期 2026-11-09，master 28a7c9e 上的工作区增量。采用 BE APP-CODE-QUESTIONS、API45／47、7.4.3 及 FE 原生权限处理，设计原字节保持原摘要。

| 环境及命令 | 实际结果 |
| --- | --- |
| Windows 隔离 SQLite／ASGI、`tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider` | 首轮 API47／API46／原观察联合 22 项通过。采用新 db20-r30 私有观察字段后，含真实回环协议联合 35 项通过。核对同任务原键、完整派发意图、错误会话、超范围 403、部分拒绝、原请求再出现仍待核对、发送后进程中断不重放，以及原停止屏障。 |
| 同一命令运行 `test_v20_opencode_instance_control.py` | 13 项通过。实际本机认证 HTTP／SSE；拒绝订阅未就绪时无 POST，错会话／决定／未观察请求事件不计入，丢失 HTTP 时准确保留实际确认项。单次允许固定 `once`，绑定原实例工作区及现有具体 NTFS 文件，错误工作区和错误编辑目标不派发。 |
| 隔离 Chrome，`tools/verify-v20-command-recovery.py --probe tasks` | 360／1280 通过。超范围允许一次禁用、可核实对象进入单次允许确认、取消保留原状。会话拒绝显示范围与观察项，丢失 202 后重新打开查询原键，按实际逐项显示已拒绝及待核对。夹具只记录一次拒绝写请求，Job 和临时输出已清理。 |
| 前端 `npm run typecheck`／`npm run format:check`、后端 Ruff 格式及限定 F 检查 | 通过。 |
| 锁定 SQLite `tools/python-v20.py tools/schema-v20-release.py --release-id db20-r30` | 新建与旧版重建的目标结构一致。新增不可变 `db20-r30`，manifest SHA256 `a56ba9850291216e444aafc46b60c66c70dc37ef23a90cafb164081c52ab5ca6`。原 r29 保留。 |

私有 metadata／always 随原权限观察保存，公开列表、回执和操作详情仅投影安全字段。一次允许限于固定协议识别、原工作区中可证明的既有普通文件。未确认目录、通配、命令、网络及其他原生对象保持禁用。拒绝保留派发前观察集合；匹配原请求和决定的事件在最终事务逐项保存，断电前尚未落库的事件保守保留 UNKNOWN。权责与原模型窗口短队列分开，其他问题／预算等待独立保留。

固定原生行为核对见 [Permission.reply](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/permission/index.ts#L99)、[read](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/tool/read.ts#L215) 和 [edit](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/tool/edit.ts#L125)。

实际固定 OpenCode、系统保护部署、用户库升级及真实供应方待验。新清单绑定当前工作区源码，包含原先使 r29 核对失败的现有 `windows_local_paths.py` 版本。该来源文件在本轮保持原字节。
