# CX · Codex / Claude Code 供应商管理

在同一个 VS Code 侧栏管理 ChatGPT 账号和第三方 Codex 供应商，兼容现有 `cx`、`cx status`、`cx-login`。
这个个人版扩展不是 OpenAI 官方产品，不通过代理转售模型，也不合并账号额度。

## Claude Code 第三方供应商（0.4.0）

CX 同一侧栏新增 **Claude Code · 第三方供应商**，本版先适配本机 VS Code 的 `Anthropic.claude-code` 插件。
Claude Code 的 **官方账号** 与 **统一历史** 区域仅为界面占位：不登录、不查询额度、不读取或迁移历史。已有 Codex 功能继续保留。

1. 打开 CX，找到 **Claude Code · 第三方供应商**。
2. 已在 CC Switch 配好：打开该区域标题栏菜单，执行 **从 CC Switch 导入 Claude 供应商**。只读 CC Switch 数据库，导入第三方地址、密钥和模型映射，跳过官方账号；不会自动切换当前接入。
3. 已在 `~/.claude/settings.json` 配好：点击下载箭头 **导入本机 Claude 当前配置**。导入不改写该文件；可与 CC Switch 导入去重。
4. 或点击 **+**，填写名称、Anthropic 兼容基础地址、默认模型、认证方式和 API Key。支持 `ANTHROPIC_AUTH_TOKEN`（Bearer）和 `ANTHROPIC_API_KEY`（x-api-key），可分别配置 Haiku / Sonnet / Opus / Fable / Subagent 模型映射，未填的分档在启用时使用默认模型。
5. 点击 **保存并启用** 或供应商行双向箭头，然后执行 **开发人员：重新加载窗口**，在 Claude Code 中新建会话。

Base URL 使用供应商的 Anthropic 兼容入口，例如 `https://gateway.example.com` 或 `https://api.deepseek.com/anthropic`。不要添加 `/messages`；CX 测试会使用 `/v1/messages`，基础地址已有 `/v1` 时不会重复追加。OpenAI Responses / Chat Completions 接口不能直接用作 Claude 接口。

供应商行的插头按钮是 **测试连接**：发送一个最多 32 个输出 token 的最小 Messages 请求，不读取或发送工作区文件。请求按供应商规则计费，成功结果显示在侧栏和 CX 输出日志中；这只能验证最小请求，不代表已验证所有工具调用和长会话能力。

密钥在 CX 的 `~/.codex-accounts/claude/providers/secrets/` 中使用当前用户加密存储（Windows DPAPI）。启用时按 Claude Code / CC Switch 的原生格式，把选中密钥写入 **用户级** `~/.claude/settings.json` 的 `env`；该用户文件和配置备份包含敏感内容，不应提交到仓库。CX 不会把密钥写到项目文件、侧栏、日志或 VSIX 中。

切换只更新接入、认证和模型字段，保留其他环境变量、permissions、hooks、MCP 和插件设置。标题栏菜单的 **恢复接入前配置** 恢复 CX 首次接管时的接入字段，保留此后新增的无关配置；这不是官方账号登录功能。CX 保存与启用、删除、恢复仍采用无常规弹窗的交互。

启用 Claude 供应商时，CX 通过 VS Code 设置 API 开启 `claudeCode.disableLoginPrompt`，恢复接入前配置时还原该设置。如果 `claudeCode.environmentVariables` 里已有接入覆盖项，CX 会阻止切换并说明需先清理覆盖项，以免显示的供应商和实际接入不一致。不要同时使用 CC Switch 与 CX 改写当前接入；发现外部修改后先导入当前配置或恢复。

默认读写 `CLAUDE_CONFIG_DIR` 或 `~/.claude`，可在 `cxAccounts.claudeHome` 指定目录（需与 Claude Code 实际配置目录一致）；CC Switch 目录可通过 `cxAccounts.ccSwitchHome` 指定。Claude 与 Codex 的供应商记录、密钥和运行配置分开保存。

Windows 本机已完成当前供应商的真实接口与 Claude 官方后端验证。AMAX 已同步安装 CX 0.4.0，并通过 Python 3.8 与 VS Code Server Node 的 47 项隔离测试；未复制本机的供应商密钥或 Claude 配置。远程使用时，在 **SSH: amax** 窗口安装 Claude Code 官方扩展，再在 CX 的 Claude 供应商区域添加密钥或导入服务器已有配置。AMAX 安装包位于 `/data1/xinwang/cx-codex-accounts-0.4.0.vsix`。

配置依据：[Claude Code VS Code 官方文档](https://code.claude.com/docs/en/vs-code#use-third-party-providers)、[用户设置与优先级](https://code.claude.com/docs/en/settings)、[模型配置](https://code.claude.com/docs/en/model-config)。

## 功能

- 左侧 **CX 账号** 图标显示三个账号，当前选择用绿色标记。
- 每个账号显示邮箱、5 小时剩余比例、周剩余比例、北京时间重置时间和套餐。
- 鼠标移到账号行，点击 **双向箭头** 切换，点击 **钥匙** 授权。
- 顶部刷新按钮查询所有账号；状态栏显示当前选择及额度。
- 常规切换、授权和供应商操作不弹窗；结果显示在侧栏状态和“CX 账号管理”输出日志中。需要生效时执行“CX: 重载窗口”。
- Windows 本机窗口和通过 SSH 连接的 Linux 远程窗口，分别读取所在机器上的账号目录。
- 复用 `~/.codex-accounts/1/2/3`，兼容已经配置的终端命令。
- 同一侧栏的“第三方供应商”区域支持图形化添加、编辑、启用、删除供应商及更换 API Key。
- 切回 ChatGPT 账号时恢复官方接入；支持恢复启用第三方供应商前的模型与接入设置。
- “统一历史会话”跨供应商列出本机会话，支持预览、搜索、归档筛选和原生会话分支。
- 发现并勾选第三方模型，为 Codex 生成本地模型目录，支持 DeepSeek 等非 Codex 命名的模型。

## 安装

1. 在 VS Code 按 `Ctrl+Shift+P`，执行 **扩展：从 VSIX 安装…**（英文界面为 **Extensions: Install from VSIX...**），选择 `cx-codex-accounts-0.4.0.vsix`。
2. 本机窗口安装到本机。连接 AMAX 时，在该远程窗口再次安装，确认扩展位于 **SSH: amax**。
3. 在命令面板执行 **开发人员：重新加载窗口**（英文界面为 **Developer: Reload Window**），然后点击左侧 **CX 账号** 图标。

也可通过终端安装：

```powershell
code --install-extension .\cx-codex-accounts-0.4.0.vsix
```

扩展在当前工作区所在的机器上运行：本机窗口运行在 Windows，远程窗口运行在服务器。
侧栏标题会标明机器名。需要信任当前工作区才能使用。

## 三个账号

| 编号 | 默认邮箱 |
| --- | --- |
| 1 | wangxin031220@gmail.com |
| 2 | KadynLedue381417@outlook.fr |
| 3 | shuiwangsanjin@gmail.com |

可在设置中修改 `cxAccounts.emails`。扩展只打包程序和默认邮箱，不打包任何登录令牌。

## 图形化添加第三方供应商

如果已通过 **CC Switch** 跑通当前供应商，先点击“第三方供应商”标题栏的 **导入当前配置**（下载箭头），或在命令面板执行 **CX: 导入当前供应商配置（兼容 CC Switch）**。
导入会读取当前自定义供应商的地址、模型和 Bearer 密钥，将密钥保存到 CX 的受保护存储，并保留已有的本地模型目录路径；不会改写正在使用的 `config.toml` 或 `auth.json`，也无需重新输入密钥。
导入支持配置中的内联令牌，或当前扩展进程能够读取的密钥环境变量；自定义认证头、认证命令等复杂接入请继续保留原配置。
再次导入可更新 CC Switch 后续更换的配置和密钥。不要同时在 CC Switch 和 CX 中切换供应商；CX 检测到外部修改时会停止普通切换，避免覆盖。

1. 打开左侧 **CX 账号**，找到下方的 **第三方供应商**，点击标题栏的 **+**。
2. 在表单中填写供应商名称、接口基础地址、模型名称和 API Key。例如基础地址为 `https://gateway.example.com/v1`，不要在末尾添加 `/responses`。
3. 点击 **保存并启用** 或 **仅保存**。操作结果显示在侧栏中；需要生效时执行“CX: 重载窗口”。
4. 重新加载后，在官方 Codex 插件中新建对话验证。已有对话可能保留自己的模型选择。

模型名称使用供应商实际提供的模型 ID。接口必须兼容 **Responses API**，并支持 Codex 使用的流式响应、工具调用及会话续接；仅声明“兼容 OpenAI”不能保证兼容 Codex。
本版使用 `Authorization: Bearer <API Key>` 认证，不包含协议转换、自定义认证头或第三方余额查询。
除本机回环地址外，接口必须使用 HTTPS。

供应商行的按钮：

| 按钮 | 操作 |
| --- | --- |
| 双向箭头 | 启用供应商，随后重新加载窗口 |
| 铅笔 | 编辑地址、模型和名称，或更换 API Key；密钥留空表示保留原值 |
| 模型列表 | 从接口发现模型，勾选要出现在 Codex 模型菜单中的项目 |
| 垃圾桶 | 删除供应商及其保存的密钥；当前正在使用的供应商需先切走 |

修改正在使用的供应商后也需要重载。删除某条供应商只移除本机保存的密钥，不会撤销供应商平台上的密钥。

要切回 ChatGPT 订阅，直接在上方账号区域选择 **账号 1 / 2 / 3**，扩展会恢复官方接入并选择该账号，随后重载窗口。
供应商区域右上角的菜单提供 **恢复接入前配置**：恢复 CX 首次启用第三方服务前的模型和接入字段，同时保留其他设置的后续修改。
如果接入字段被外部程序修改，普通切换会停止，请检查后使用该恢复入口。

本机窗口管理本机的供应商，AMAX 窗口管理 AMAX 的供应商，密钥不会自动跨机器同步。
启用供应商会修改用户级 `config.toml`，使用同一 Codex 配置目录的其他客户端也会读取这些设置。
第三方 API 按供应商规则独立计费，不会合并或消耗 ChatGPT 账号的 5 小时与周额度。

## DeepSeek 等第三方模型与 Codex 模型菜单

1. 在供应商行点击 **发现 / 同步供应商模型菜单**，从接口返回的模型列表中勾选需要的模型；也可在编辑表单中点击 **从接口选择模型**。
2. 接口不提供 `/models` 时，可以手动在表单的 **Codex 模型菜单** 中每行填写一个模型 ID。模型列表接口被拒绝不代表推理接口也不可用。
3. 启用供应商时，CX 会在 `providers/catalogs/` 生成该供应商的模型目录，并设置 `model_catalog_json`。重新加载窗口后，官方 Codex 的模型菜单读取这份目录。
4. 展开 CX 的供应商列表，点击某个已保存的模型名称可设为默认模型；修改当前接入后需重载。

不同供应商的模型菜单分别保存，避免把其他供应商不可用的模型混入当前接入。
已有源模型目录中的匹配条目会保留元数据；未知模型使用保守的纯文本模板和 131072 上下文窗口，DeepSeek 模板提供低 / 高推理档位。未提供的能力不会自动推断为已支持。
第三方接入默认关闭内置网页搜索；非 GPT 模型会去除原先的服务档位，避免沿用不兼容的参数。切回官方接入时恢复原有设置。
发现模型只读取 `/models`，不会发送推理请求；出现在列表中不证明该模型兼容 Responses、工具调用或所有 Codex 功能。

本机保存的 qwen 网关中，`deepseek-v4.1-flash-1017` 已使用真实 Codex 后端、临时配置和最小回复请求完成验证。该结果只覆盖此网关与模型的基本接入，不代表全部模型均已验证。

## 统一历史会话

打开 CX 侧栏底部的 **统一历史会话**，点击刷新即可跨官方与第三方供应商读取当前机器的历史。默认显示未归档会话；菜单可切换已归档记录，搜索按钮按标题查找，列表底部可以加载更多。

- 点击会话行：打开文本预览，显示用户与助手消息、工具操作摘要；不修改原记录。长记录按页读取，可在标题栏菜单选择“加载更早消息”。
- 点击右侧箭头：同一接入直接在官方 Codex 中打开；不同接入会直接使用当前接入创建原生分支并打开，不再弹出确认框。请先完成供应商切换并重新加载窗口。
- 右键选择 **为当前接入创建会话分支**：保留原会话，通过 Codex 原生接口复制历史到新分支，再在官方插件中继续。某些版本在首次继续发送消息后才将新分支显示在历史列表中。

官方 Codex 自带的历史列表仍由其供应商筛选逻辑控制；CX 提供统一入口，不改写原生插件或批量重标记 SQLite 中的供应商。
跨接入继续时，后续请求可能把历史上下文发送给当前供应商；操作结果写入侧栏和输出日志。加密内容或原生接口无法读取的记录会报错，不会尝试绕过或手工解密。
本机与 AMAX 的历史分别读取，不会自动跨机器复制会话。

## 操作提示

0.3.1 起，账号切换、供应商启用/删除/恢复、授权完成、模型保存和历史分支等常规操作不再使用 VS Code 弹窗。状态会显示在对应侧栏，详细记录写入“CX 账号管理”输出频道；只有真正的连接、配置或操作错误仍会弹出错误提示。

## 授权

点击账号行的钥匙按钮。扩展在集成终端中创建一个授权任务，显示网址与设备码。
在**本机浏览器**中登录该邮箱，输入码并确认。不要关闭授权终端，等待它结束。
扩展会刷新额度。设备码过期时，再点一次钥匙即可。授权进度和结果显示在账号侧栏与输出日志中，不再弹出常规提示。

授权先在临时目录进行，验证邮箱正确后才保存；误登录、失败和取消均不覆盖旧登录。
授权其他账号不会切换当前插件账号；授权当前账号后需重载窗口，让官方插件读取新凭据。
每次只运行一个刷新 / 切换 / 授权操作，同一用户的其他扩展窗口会在侧栏显示稍后重试。
任务面板可以终止授权；退出后可重新开始。

## 与终端命令兼容

```text
cx 1 / cx 2 / cx 3    选择插件账号
cx status             查询所有账号额度
cx-login 1 / 2 / 3     指定账号授权
```

扩展直接操作同一套文件，不要求命令脚本必须存在。现有命令不被覆盖。
原有终端命令只负责账号凭据；启用第三方供应商后，请通过 CX 侧栏选择 ChatGPT 账号完成官方接入恢复。
不要同时在终端和侧栏操作账号；终端脚本不参与扩展的跨窗口锁。
插件本地历史和配置共用；切换不会将云端任务或工作区权限转移到其他账号。
同一个操作系统用户共用的 Codex 配置目录仍只有一个账号选择，其他窗口也要重载。
“当前选择”表示磁盘配置，官方 Codex 进程只有重载后才确定读取了该账号。

## 环境与设置

需要官方 Codex 插件或 Codex 后端程序，以及 **Python 3.8 或更高版本**。
扩展自带 Python 脚本和保留配置格式的 TOML 解析库，运行时不需要安装额外的 Python 或 Node.js 依赖包。

| 设置 | 用途 |
| --- | --- |
| `cxAccounts.pythonPath` | Python 解释器路径。Windows 自动查找已有的 Miniconda 或 Python，AMAX 使用 `python3`。 |
| `cxAccounts.codexPath` | 后端绝对路径，通常留空即可。AMAX 优先沿用 `~/bin/codex`。 |
| `cxAccounts.proxyUrl` | 指定代理；留空沿用原有设置。AMAX 启动脚本使用 28082 独立隧道，本机自动探测 7890。 |
| `cxAccounts.accountsRoot` | 默认为 `~/.codex-accounts`。 |
| `cxAccounts.codexHome` | 默认为 `CODEX_HOME` 或 `~/.codex`；应与官方插件实际目录一致。 |
| `cxAccounts.autoRefresh` | 侧栏可见时自动刷新，默认开启。 |
| `cxAccounts.refreshIntervalSeconds` | 默认每 300 秒刷新一次，最短 60 秒。 |

在本机和远程分别设置路径与代理，不能把 Windows 路径填到服务器的远程设置。
AMAX 仍需要本机代理与专用 SSH 隧道正常运行。该隧道的计划任务名称为 `AMAX Dedicated SSH Tunnel`；扩展不创建 SSH 隧道。

## 额度的含义

通过官方 `account/rateLimits/read` 接口读取，剩余比例为 100% 减去已使用比例（字段名为 `usedPercent`）。
按服务端报告的 300 分钟和 10080 分钟识别 5 小时和周额度周期，不依赖主、次额度字段（`primary`、`secondary`）的排列顺序。
接口未返回窗口时显示“未提供”，不代表无限额度；查询失败时单独显示原因，不当作 0%。
不会创建模型对话，不购买额度、不消耗免费额度重置次数。查询可能刷新登录令牌。
只有刷新动作得到新额度；文件变动扫描不会伪造额度更新时间。

## 凭据与限制

沿用现有 `auth.json` 文件方案，没有将既有账号迁移到 VS Code 的加密凭据存储，也不跨机器同步令牌。
Windows 选择账号时复制默认凭据；Linux 选择账号时链接默认凭据。较新的登录刷新结果会同步回账号目录。
旧凭据按需保存在 `~/.codex-accounts/plugin-switch-backups/` 或 `login-backups/`。
以上凭据及备份都含令牌，请勿提交 Git 或分享。
扩展输出仅记录操作结果，不记录令牌，不上传遥测；联网操作仅由 Codex 后端完成。
现有 ChatGPT 账号仍要求文件式凭据；系统密钥环中的既有 ChatGPT 登录需要另行适配。

第三方供应商保存在 `~/.codex-accounts/providers/`：

- `registry.json` 仅保存名称、地址和模型等信息。
- `secrets/` 保存密钥。Windows 通过当前用户的系统数据保护接口（DPAPI）加密；Linux（包括 AMAX）使用仅当前用户可读的文件和目录（0600 / 0700），不是加密文件。
- `credential_helper.py` 是稳定的凭据获取脚本，由 Codex 调用；密钥经进程标准输入传入保存程序，不放在命令参数、普通设置或 `config.toml` 中。
- `catalogs/` 保存各供应商生成的模型菜单及能力元数据，不含密钥。
- `config-backups/` 保存每次接入切换前的配置；`state-*.json` 保存待恢复的原始配置。原配置如果已包含其他服务的密钥，这些备份也可能包含密钥，请勿分享。

从 CC Switch 导入不会清理原配置里的内联密钥；它保留原先可用的接入。CX 自己启用供应商时，使用受保护存储及凭据获取脚本。

供应商密钥的读取不依赖 VS Code 保持运行；同一操作系统用户下的 Codex 可调用凭据脚本。不要删除该脚本、移动配置目录或卸载所用的 Python 解释器，除非已先恢复原接入配置。

## 开发与验证

在项目目录中依次执行以下命令，完成开发依赖安装、自动检查和安装包生成：

```text
npm install
npm test
npm run test:python
npm run package
```

生成的安装包位于 `releases/cx-codex-accounts-0.4.0.vsix`。

源码中的 `python/quota_status.py` 和 `python/login_account.py` 来自现有 CX 工具。
扩展没有复制 GitHub 第三方项目的实现。
随包分发的 `tomlkit 0.13.3` 用于保留 TOML 注释和其他配置，遵循 MIT 许可证，见 `python/vendor/TOMLKIT-LICENSE`。

- [Codex 应用服务器协议](https://learn.chatgpt.com/docs/app-server)
- [VS Code 远程扩展开发说明](https://code.visualstudio.com/api/advanced-topics/remote-extensions)
