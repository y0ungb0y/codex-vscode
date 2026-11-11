# 验证记录

版本：0.4.0；日期：2026-11-11。

## 本次 Claude Code 供应商接入

- Node 测试 11 项、Python 测试 36 项通过，包含原有 Codex 回归检查和新增 Claude 表单、独立命令、模型分档、Token / x-api-key、密钥更新、CC Switch 只读导入、配置恢复、外部修改拦截、失败回滚及 Messages 请求检查。
- Windows 本机从 CC Switch 导入两个第三方 Claude 供应商（DeepSeek、0.37），跳过官方账号占位；导入和测试时本机 Claude settings.json、Codex config.toml 和 auth.json 字节保持不变。
- 当前 0.37 网关的 claude-fable-5-2 通过真实 Anthropic Messages 最小请求；连接测试最多请求 32 个输出 token，不发送工作区文件。
- 安装 Anthropic 官方 Claude Code VS Code 扩展 2.1.322，调用该扩展自带的真实 claude.exe 后端，以用户配置中的网关和 claude-fable-5-2 返回 OK。测试使用临时工作目录、禁用工具和自定义 hooks / MCP，不保存测试会话。请求按供应商规则计费。
- 清理 VS Code 用户设置中残留的占位接口与令牌覆盖，保留无关设置和 JSONC 注释；原文件备份在用户私有的 ~/.codex-accounts/claude/vscode-backups/。启用 disableLoginPrompt，使扩展读取 Claude 用户配置。
- 本机通过 CX 的同一 JSON 桥接启用 0.37，保留 CC Switch 导入的模型分档；DeepSeek 已导入，未对其发送真实付费推理请求。
- Claude 官方账号和统一历史仅保留前端占位；未实现登录、额度查询或历史迁移，不承诺所有第三方网关的完整工具链兼容性。
- 新增真实 VS Code Extension Host 检查脚本，验证 Claude 命令注册和快照；本机启动该检查被 VS Code 更新锁阻止，未完成真实侧栏点击验证。现有窗口重载后可加载新版；未绕过更新锁或关闭用户窗口。

## AMAX 与 GitHub 同步

- AMAX 使用实际 VS Code Server 的 code-server 安装 0.4.0；安装包保存在 `/data1/xinwang/cx-codex-accounts-0.4.0.vsix`，使用说明同步至同目录的 `CX-VSCode插件使用说明.md`。
- 在 AMAX 临时目录运行全部 36 项 Python 3.8 测试与 11 项 VS Code Server Node 测试，全部通过；未使用服务器生产凭据进行付费推理。
- GitHub 源码、中文说明和 v0.4.0 VSIX 使用同一版本；仓库保持私有。运行时令牌、供应商密钥、用户配置与本机备份不包含在提交或安装包中。
- AMAX 与本机分别管理 Claude 供应商；本次未复制本机 Claude 用户配置或密钥，不表示服务器上已完成真实 Claude 接口或会话验证。

## 本次历史与模型修复

- Node 检查 10 项、Python 检查 26 项全部通过；涵盖统一历史视图、原生分支、模型发现、目录生成和 0.2.0 状态升级。
- 本机与 AMAX（Python 3.8）的真实 Codex 后端均在隔离配置中验证：`model/list` 显示自定义模型、凭据脚本、Responses 回复、跨供应商历史列表和原生分支读取。
- 原生分支保留原会话，且分支中能读取复制的可见消息。某些后端要在分支首次继续对话后才将其列入历史。
- 本机生产会话只调用本地原生读取接口，确认同一页包含官方与第三方记录；没有直接改写会话数据库或批量更换会话供应商。
- qwen 网关 `/models` 返回 182 个名称，包含保存的 `deepseek-v4.1-flash-1017`。
- 使用该模型、现有密钥和临时配置执行真实 Codex 最小请求：模型出现在原生 `model/list` 中，CLI 正常退出并回复 `OK`；生产 `config.toml` 与 `auth.json` 在测试前后逐字节相同。该推理请求由供应商正常计费。
- 尚未逐一验证所有发现的模型，也未对该真实 DeepSeek 接入执行完整工具链或长对话测试。生成目录不是对供应商全部能力的认证。
- 界面与命令行为使用隔离的 VS Code API 夹具检查，没有自动点击真实 Codex 插件界面。

## 0.2.0 已有验证记录

## 本次供应商功能

- Node 检查：9 项通过，包括侧栏表单、保存后启用、密钥不回显、原有账号功能、真实 JSON 桥接及密钥通过标准输入传递。
- Python 检查：18 项通过，包括原有账号行为、供应商增删改、Windows 加解密、凭据获取脚本、配置往返切换、失败回滚、外部修改检测和 CC Switch 导入。
- 使用本机已安装的真实 Codex 后端和隔离的测试配置，完成“凭据脚本读取测试密钥 → 请求本机模拟 Responses API → 返回完整回复”。
- AMAX 的 Python 3.8 和真实 Codex 后端也通过隔离模拟接口验证。无生产密钥参与，无付费请求。
- CC Switch 兼容测试覆盖 `requires_openai_auth = true` 加内联令牌的现有配置：导入不改写原配置，密钥不出现在返回元数据，切回官方接入后可再次启用。
- 模拟 VS Code API 检查表单与命令行为，没有自动点击真实 Codex 插件界面。尚未用真实第三方 API Key 进行付费模型请求；供应商对工具调用等功能的完整兼容性仍取决于供应商实现。
- 运行时额外包含 tomlkit 0.13.3（MIT），安装时不需联网下载依赖；下载包的 SHA-256 已核验。

## 0.1.0 已有验证记录

- Node 检查：6 项通过，包括账号树、命令绑定、授权任务参数、切换后重载选择、额度格式、超时与错误输出。
- Python 桥接检查：5 项通过，包括跨进程锁、账号选择、误选保护、查询不切换账号、重复读取不重写凭据、元数据不输出令牌。
- Windows 本机：通过插件自带桥接查询三个真实账号的额度，当前选择保持不变。
- AMAX：同一桥接通过 28082 隧道查询三个真实账号的额度，当前选择保持不变。
- 本机 VS Code 安装：CLI 报告成功；实际 extension host 日志报告激活；CX 输出记录账号状态读取成功。
- AMAX VS Code 安装：code-server 报告成功；remote extension host 日志报告激活；CX 输出记录账号状态读取成功。
- VSIX 检查：仅含清单、源码、图标及说明，不包含 auth.json、JWT、测试凭据、构建依赖或 node_modules。

独立的 VS Code 扩展宿主测试启动被已存在的编辑器更新互斥锁阻止；没有绕过或终止更新。
改用实际已运行窗口的加载日志确认激活。没有自动点击真实账号的切换、重新授权或重载按钮；
对应处理逻辑通过隔离夹具检查，实际使用时仍需用户选择并完成浏览器授权。

打包工具 npm 依赖审计报告 3 个 moderate 问题，仅属于开发 / 打包依赖；VSIX 不包含这些依赖。
运行时只使用 VS Code API、Node 内置模块、Python 标准库以及已安装的 Codex 后端。
