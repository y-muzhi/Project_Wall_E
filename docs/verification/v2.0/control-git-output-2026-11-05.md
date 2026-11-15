# 控制Git有界输出与创建端释放（2026-11-05）

基线master／HEAD28a7c9e，V2源码未提交。设计BE0.17-draft-17／FE0.16-draft-16（DRAFT）及摘要未变；本批完整复核7.7.1／.2／.5／.6／.7，相关7.7.3—.4仍沿前批阅读，不将本次截断段落标新全读。依据固定CONTROL_GIT、原STDIO／创建栅栏／停止与结果分离及输出限制，无新产品交互或正式设计合并。

输入为BackendStandardIO原对象、原LaunchScope和max_output_bytes；输出为原scope／io_nonce绑定的两路字节数、EOF／超限／故障事实及私有不可变字节快照。EOF只说明管道完成，不证明进程退出、Job为空、Git成功、业务完成或已经停止。

windows_stdio.py增加单一输出消费者lease：读端由原Backend持有，Guard仍只有子端复制；原PID／scope固定，活动借用禁止关闭，同一对输出一经消费不可换reader或退回裸读重放。输入端不受输出消费者占用影响。

windows_pipe_capture.py新增BoundedOutputCapture，使用PeekNamedPipe后按实际可读数量ReadFile，每轮最多两次32KiB读取、交替优先顺序，无无限drain／等待／读线程。零available不是EOF；仅Peek的ERROR_BROKEN_PIPE确认该路结束，读取错误／异常计数保留故障和原owner。两路共用原容量，最多保留容量内前缀、多读一个字节判溢出；超限或错误不称完整，require_complete拒绝。快照保留二进制／NUL／原换行，repr不包含原正文，不自动记录审计或杀进程。

runtime_control_git.py在原CREATE资源已记录、恢复前关闭Guard创建用STDIO副本。子进程已有继承端，关闭这些Guard副本才允许后端在子端真正结束后取得EOF。仍保留原进程／Job／token等控制对象；creation_stdio_closed为私有真实事实。关闭失败在任何ResumeThread派发前返回，原resume状态保持NONE，重试仅关闭原剩余端并恢复同一原进程，不创建第二个root。StdioBoundaryError纳入原资源错误集合。

移除测试peer专属read_small_available配置读函数，改用实际有界消费者；普通三字节方向／继承句柄测试仍保留其必要独立测试路径。原固定ConfigParseCommand、真实AsUser／Journal／Registry／Job与后端独立进程组合现在可在Git运行时持续读取，不先等退出。未放开任意Git argv或新增Git业务API。

检查在普通非提升测试环境，固定Python3.13.5／SQLite3.54.1／MinGit2.56.0.windows.4，tools.quality_gate.environment专属临时根，经tools/python-v20.py tools/quality_python.py，-q -p no:cacheprovider --tb=short和专属--basetemp：

- 首轮三文件46通过／1失败36.13秒：测试导入了不接受参数的scope夹具，已改复用带number参数的原STDIO scope，未放宽实现。
- 最终test_v20_windows_pipe_capture.py、test_v20_git_config_command.py、test_v20_windows_stdio.py、test_v20_runtime_control_git.py四文件66通过69.56秒。
- 实际原生二进制／EOF／空闲、合并容量与边界下一字节、单reader／关闭／读取故障；mock原生故障明确只作为错误分支证据。
- 实际SHA-1及SHA-256配置均包含512KiB值，经固定Git／独立Backend读管道完成，EOF及字节数核对；4096上限触发后保持不完整并终止原Job，核对退出及空Job。不是用户仓库、模型或Guard服务安装证据。
- 输出创建用端关闭故障注入验证不提前恢复、只复用原PID／创建时刻与Journal；原Registry／STDIO回归通过。
- 此后扩展回归及最终静态结果在本记录末尾追加，不提前填写通过。

SOURCE_NAMES未包含本批三个基础模块，实际db20-r10 load_release仍一致，manifest db6f8e3cade6dc30d37c9902d90b7afeb7bc2b37ce60fc2e72e2758c7d7156e9；未覆盖旧Schema release或维护正常数据库。正式设计SHA保持基线。既有httpx弃用提示未升级依赖。

源码及格式结果同目录temp＋flush／fsync、原字节复核和os.replace。临时源配置／私有副本、输出JSON／原生日志均只在本轮专属临时根，工具结束清理；未改正常数据、用户服务、系统权限或网络策略，没有真实模型／计数或V2提交／推送。没有前端改动，不伪称新增UI／浏览器验证。

剩余：固定元数据命令／仓库完整准入、业务OperationStep／GitReceipt生产者及完整业务输出适配、基线和内容／交付仍待推进；当前模块是实际原生读取组合，不是完整仓库准入或Git交付成功。

最终补充：poll在ReadFile可能已消费之后遇到取消／MemoryError／OSError等异常，标记OUTPUT_CAPTURE_INTERRUPTED并保留owner，禁止按空块继续；快照不承认完整。额外三种中断专项及最终八文件208通过110.03秒，包含原Native／Registry／控制方退出／STDIO回归，具体文件见[定位组合记录](repository-location-2026-11-05.md)。199文件格式、四个修改模块lint及diff通过；没有本轮前端变更或新浏览器结果。
