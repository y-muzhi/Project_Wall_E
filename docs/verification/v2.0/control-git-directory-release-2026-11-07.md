# Control Git 原目录释放验证（2026-11-07）

在项目锁定 Windows／Python／SQLite 下，用 NTFS 临时包和测试自有进程验证。释放沿原技术动作、原 nonce、原准备资源及实际 FileID；先核对无活动，再关闭原句柄与私有包。私有复制文件沿既有删除路径，目录只用原 FileID 的删除句柄并核对原路径消失。

- 原动作 RELEASE 清理实际配置副本、空 hooks、预留 nonce 的私有读包。重放保持原回执。原 Guard 根与实际源配置均可继续核对。
- 非空目录删除拒绝，内部文件完整保留。替代对象与移开的原目录均保持。已标记删除时注入原句柄关闭失败，保留同一句柄，后续核对后才完成。
- 设计依据为实际目录句柄及 DELETE 权限下的文件处置接口。[Microsoft 目录句柄](https://learn.microsoft.com/en-us/windows/win32/fileio/obtaining-a-handle-to-a-directory) [Microsoft 文件处置接口](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-setfileinformationbyhandle)

使用 `tools/python-v20.py tools/quality_python.py` 及自动清理临时目录。目录释放、读包、准备资源转移、实际本机管道、版本探针、配置和两种对象格式元数据共 7 文件 **62 项通过**（201.38 秒）。只有既有 Starlette 依赖弃用提示。Ruff 格式（233 个 app 文件）、受影响模块 lint、Git 差异检查通过。原配置文件的生产后端交接、仓库读取固定命令派发、实际 SYSTEM／跨用户运行仍待接入。
