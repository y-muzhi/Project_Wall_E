# V2.0固定MinGit包字节与安全解包

日期：2026-11-05；HEAD 28a7c9e，V2未提交。只准备项目本地运行资源；未安装／替换系统Git、改PATH／ACL、运行下载的git.exe或操作正常源仓库／引用。

来源：[Git for Windows官方v2.56.0.windows.4发布](https://github.com/git-for-windows/git/releases/tag/v2.56.0.windows.4)。实际下载MinGit-2.56.0.4-64-bit.zip，39846926字节，SHA256 e3bf78351fe777fba47ddee5950082f8a98bb0f02604fdc7ba3ee2cb68ffa877，与正式草稿和发布方一致。原ZIP保留；资源在backend/runtime/git/2.56.0.windows.4/win-x64/，manifest SHA256 4e888e998f1f08e8b78559c212d30c51aaa3cc30e85b9cdafcf7b44249a4e215。375个原文件，展开96237338字节，cmd/git.exe实际PE为x64；版本字段仅expected，不冒充程序版本实测或签名验证。

实现git_bundle.py及tools/prepare-code-git.py：
- 固定唯一官方URL／原字节长度／SHA，单次有界下载，无任意URL／隐式重试。预检全部ZIP条目、编码／NFC／父目录别名／file-dir冲突／特殊类型／容量，完整预检后逐新文件xb写入、flush／fsync，禁止覆盖；新同卷目录不覆盖发布。
- 全目录／文件、源ZIP、manifest独立重开核验。实际源ZIP是可信字节依据，重新解码ZIP重建每文件SHA和完整确定manifest，不信任可修改manifest自报摘要。检查所有文件及空目录，拒绝额外对象、链接／重定向、错大小／字节或metadata。读取源和metadata有界。状态ARCHIVE_BYTES_VERIFIED、runtime_admitted=false。
- ContentPathIndex增加显式目录的同一命名空间检查，仍不把空目录存成产品内容条目；与已有文件／父目录共享算法。
- 正常失败只清理已核对绝对路径下本次资源暂存，不删除正式包或正常维护资产。

实际过程：普通网络访问WinError10013未下载；经资源下载权限执行已取得包。首轮解包核验误假设普通Git的mingw64/bin/git.exe存在；官方MinGit实际使用cmd/git.exe，已按真实包修正且再次完整核验。失败暂存清理成功，没有不完整发布。最终prepare成功，随后--verify实际375文件／96237338字节与同manifest摘要通过，未执行Git。

专项：content_paths／git_bundle两文件61通过（1.50秒）；合成归档覆盖ZIP slip／别名／目录冲突、symlink、容量、原字节／不覆盖、PE格式、额外空目录／内容篡改、下载长度／摘要和无隐式重试。合成PE仅数据夹具，没有执行或作为真实准入；实际包字节核验另列上项。160文件Ruff格式及git diff --check通过。

测试权限过程：一次额外权限测试请求自动审批服务403，审查无法完成，操作未执行，不是“不安全”判定。采用项目内.tmp专属目录普通权限离线检查后61通过，目录自动清理；没有绕过原审批去做额外权限操作。无测试JSON／截图／原始日志保留。正式source.zip／manifest及375程序资源为实际依赖保留。

未验证：Authenticode链、真实git --version／配置／引用协议／故障、Guard CONTROL_GIT、LPAC／WFP／Job或产品起点登记；ready继续false。当前个人Git仍2.51.2，不采用。dotnet host无SDK，但只读核对发现系统.NET Framework64／Framework v4.0.30319 csc.exe存在；未运行编译器或安装任何工具。下一单元按Win32／Guard实际能力推进，不以当前字节资源代表Q20-GIT运行准入。
