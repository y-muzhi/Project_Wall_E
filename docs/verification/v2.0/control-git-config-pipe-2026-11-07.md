# Control Git 原配置句柄与固定解析验证（2026-11-07）

Windows 隔离仓库、项目锁定 Python／SQLite 与实际 MinGit 2.56.0.windows.4。后端原位置租约单独打开只读导出，Guard 从原普通控制方复制相同访问权的实际文件句柄。核对 NTFS FileID、规范路径、原 SHA256、长度及实际只读授权。Guard 解析命令的文件上限为 1 MiB。导出与后端原位置复核分别打开文件，避免复制句柄共用文件指针影响另一方。[Microsoft DuplicateHandle](https://learn.microsoft.com/en-us/windows/win32/api/handleapi/nf-handleapi-duplicatehandle)

- 真实双进程管道执行 GIT20-CONFIG-PARSE-1。原配置源在后端可继续核对，Guard 私有包中建立原配置副本和固定空全局配置；MinGit 以普通控制方令牌运行，后端由原 STDOUT 得到实际 SHA1 bare 格式。释放后私有包已移除，源文件字节保持，私有技术记录未包含测试配置字段值。
- 单独原文件交接覆盖错误 scope、FileID、SHA256。测试禁止通过传入路径重新打开源文件，仍能从实际复制句柄读原字节。
- 本次使用实际管道、原进程与 Git；后端程序包准入沿前批测试端口。真实 SYSTEM 宿主、业务调度、仓库元数据命令联调及 C01／C02 仍待接入。

使用 `tools/python-v20.py tools/quality_python.py` 和清理式临时目录。原句柄首轮 83 通过、1 失败，原因是 Windows 复用接口返回三值，调用误接两值。修正并加实际只读授权检查后 84 项通过（47.67 秒）。固定配置解析加入实际管道后 7 文件 113 项通过（57.22 秒）。共用准备模块更名的首次扩大检查另有测试引用误改，已修正并重跑。仅既有 Starlette 依赖弃用提示。234 个 app 文件格式及受影响模块 lint 通过。

最终统一准备模块命名和测试引用后，固定配置／管道／原句柄／私有释放／两种 Git 对象格式／原动作及窄恢复 10 文件 169 项通过（203.52 秒）。
