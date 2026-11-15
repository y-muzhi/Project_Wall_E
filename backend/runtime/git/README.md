# 固定Git资源

MinGit v2.56.0.windows.4，项目本地win-x64包。官方原ZIP、375文件及确定manifest已准备并核验；来源及实际证据见docs/verification/v2.0/git-bundle-bytes-2026-11-05.md。

`tools/prepare-code-git.py --verify`仅检查固定源ZIP与每文件字节、路径、目录及PE入口。不会运行Git或把expected_version当实际版本；manifest的runtime_admitted保持false。首次准备使用--download，已有正式目标不可覆盖。

Guard、实际程序身份／版本、受控环境／配置、命令协议及失败恢复通过前不提供可执行Git配置。用户个人PATH Git和系统安装保持独立，原仓库／分支没有被此准备动作操作。

2026-11-05补充：固定包已在本轮自有Job及全新临时sha1／sha256 bare库完成--version、原blob／tree写读向量，详见docs/verification/v2.0/content-manifest-git-vectors-2026-11-05.md。此为CLI组件证据，未完成生产Guard／配置白名单／签名与完整Git准入；manifest的runtime_admitted=false保持。

2026-11-05补充：固定Git向量现已覆盖交付commit：两个对象格式的原父提交与交付payload经hash-object计算／写入及cat-file原字节往返，生产算法组合55项通过，见docs/verification/v2.0/git-commit-input-2026-11-05.md。普通Guard测试宿主的真实AsUser／原资源／退出链路亦已专项核对；仅登记--version，无安装服务／Pipe认证／完整配置或交付协议准入，runtime_admitted=false保持。
