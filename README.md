# Codex Conversation Namer

为 Codex 本地会话自动生成中文标题，按项目、主题和日期找回讨论。

```text
项目｜主题｜具体问题或交付物｜开始日期

ExampleApp｜问题排查｜登录错误排查与输入校验｜2026-01-15
ExampleApp｜文档维护｜补充安装与配置说明｜2026-01-16
```

> 命名设计参考 NASA 配置管理与科学数据命名建议、欧洲航天 ECSS 配置与信息管理标准，以及 ISO/IEC 技术文档、系统标识和日期标准，将“稳定标识、固定字段、可读标题、可追溯记录”的原则用于 Codex 对话管理。

*以上为格式示例，实际标题根据会话内容生成。*

**Python 3.10+ · 无第三方 Python 依赖 · Linux / macOS / WSL**

[快速开始](#快速开始) · [常用命令](#常用命令) · [配置](#配置) · [工作原理](#工作原理) · [常见问题](#常见问题) · [文件说明](#文件说明)

## 功能

- **自动整理**：首条用户消息得到回复后生成标题，此后每新增 10 条用户消息重新评估。
- **按需调用**：只按新增用户消息数触发评估，支持冷却时间与每日模型调用上限。
- **手动可控**：检测到自动标题被手动修改后停止覆盖，也可恢复已记录的原标题。
- **沿用现有配置**：使用当前 Codex 的模型与认证，通过 App Server 更新标题。
- **可扩展词表**：在 JSON 配置中添加项目别名和主题关键词，无需修改代码。

## 快速开始

准备好 Python 3.10+，并确保已安装、登录 Codex CLI，且 `codex` 命令可用。工具管理的是 **Codex 本地会话**，不包含 ChatGPT 网页历史；原生 Windows 不支持，请使用 WSL。

### 1. 安装

下载或复制源码后，在源码目录执行：

```bash
python3 scripts/install.py --check
python3 scripts/install.py
```

安装器会检查所需命名接口，复制程序并注册 Stop Hook；已有 Hook 会保留并备份。全新安装默认停用，升级保留已有配置。

### 2. 启用

以下命令使用默认安装目录：

```bash
cd ~/.local/share/codex-conversation-namer
python3 scripts/namer.py enable
```

> 启用后，工具会按需向当前模型提供方发送有限的会话摘录，并自动修改标题。模型调用可能产生费用。

### 3. 信任 Hook 并检查

在 Codex CLI 中输入 `/hooks`，审核并信任自动命名 Stop Hook，然后重新打开会话。使用 IDE 时，可在 CLI 完成审核后重新加载 IDE。

```bash
python3 scripts/namer.py doctor
```

返回 `ready: true` 表示功能已开启，且 Hook 已注册、启用并受信任。之后正常使用 Codex 即可；标题是否更新取决于内容变化、冷却时间和调用额度。

<details>
<summary>自定义安装路径与环境变量</summary>

```bash
python3 scripts/install.py --install-dir "$HOME/tools/conversation-namer" --codex-home "$HOME/.codex"
```

安装器读取 `XDG_DATA_HOME`、`CODEX_HOME` 和当前 Python 解释器位置，生成适用于目标电脑的 Hook 命令。默认安装目录为 `${XDG_DATA_HOME:-$HOME/.local/share}/codex-conversation-namer`。

如果指定了其他位置，后续命令应在实际安装目录中运行。安装器不会更改模型、认证或 `config.toml`，也不会自动写入 Hook 信任记录。

</details>

## 常用命令

在安装目录运行：

| 操作 | 命令 |
| --- | --- |
| 查看配置、会话数量和近期调用 | `python3 scripts/namer.py status` |
| 搜索本工具记录的会话 | `python3 scripts/namer.py search --query 文档` |
| 检查开关与 Hook 状态 | `python3 scripts/namer.py doctor` |
| 停用自动命名 | `python3 scripts/namer.py disable` |
| 重新启用 | `python3 scripts/namer.py enable` |
| 恢复已记录的原标题，并锁定自动修改 | `python3 scripts/namer.py restore --thread 会话ID` |
| 解除指定会话的锁定 | `python3 scripts/namer.py unlock --thread 会话ID` |

`会话ID` 替换为实际 ID，可从搜索结果获取。恢复标题需要本工具留有该会话的原标题记录。

## 配置

编辑安装目录中的 [`config/config.json`](config/config.json)。下表列出全新安装的默认值；升级时保留现有开关和设置。旧配置未包含新增评估阈值时，也会使用下表默认值。消息数阈值请设为正整数。

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `enabled` | `false` | 自动命名开关，也可通过 `enable` / `disable` 修改 |
| `cooldown_seconds` | `600` | 同一会话两次模型尝试之间的最小间隔，单位为秒 |
| `reevaluate_after_messages` | `10` | 上次成功评估后，累计新增用户消息达到此数量时重新评估；助手回复不计数 |
| `daily_model_calls` | `500` | 每个安装每天的模型调用上限，失败和超时也计入 |
| `max_context_chars` | `4000` | 发送的业务上下文字符上限，不是总输入 token 上限 |
| `max_title_chars` | `60` | 标题最大字符数 |
| `model_timeout_seconds` | `90` | 等待模型结果的超时时间，单位为秒 |
| `timezone` | `Asia/Shanghai` | 标题日期和每日调用额度使用的时区 |
| `project_patterns` | `{}` | 项目名称与匹配正则表达式 |
| `topic_patterns` | `{}` | 额外主题与匹配正则表达式 |

如需调整每日调用上限，修改安装目录中 `config/config.json` 的 `daily_model_calls` 字段，默认值为 `500`。该上限由所有会话共享，配置在下一次 Hook 调用时读取。

### 添加项目与主题

将以下字段合并到现有配置，保留其他配置项：

```json
{
  "project_patterns": {
    "ExampleApp": "exampleapp|示例应用"
  },
  "topic_patterns": {
    "性能优化": "性能|performance"
  }
}
```

内置主题包括功能开发、问题排查、测试验证、文档维护、环境配置和对话管理。词表用于辅助模型统一项目和主题名称，不决定是否触发重命名；未命中任何词表的对话也会正常评估。

## 工作原理

```text
一轮对话结束 → Stop Hook → 检查新增内容 → 冷却与额度检查 → 模型重新评估
                               ↓                            ↓
                       尚未达到阈值，继续累积          标题变化：更新并回读验证
                                                   标题相同：保留标题
                                                           ↓
                                                   保存摘要与处理进度
```

### 首次命名与后续更新

| 阶段 | 触发条件 | 行为 |
| --- | --- | --- |
| 首次命名 | 尚无本工具生成的标题，且已收到首条用户消息 | 第一轮回复结束后评估，不要求特定关键词或最小问题长度 |
| 后续更新 | 上次成功评估后，累计新增 10 条用户消息 | 综合旧摘要、首次请求、新增消息和最近回复，重新判断标题；助手回复不计数 |
| 等待与重试 | 内容尚少、冷却中、额度不足或调用失败 | 不推进处理进度，下一次 Hook 继续检查已积累的内容 |
| 评估完成 | 新标题校验通过，且需要修改时已回读确认 | 保存累计摘要和处理进度；标题没变也记为一次成功评估 |

例如，第 1 条用户消息得到回复后生成初始标题；新增的第 2～10 条用户消息累计等待，第 11 条触发重新评估。若评估成功，再累计 10 条，到第 21 条时再次评估。项目和主题可以保持不变，具体问题或交付物随讨论深化而更新。

简短确认和经过代码／凭据过滤的用户消息也计数，空白、环境上下文和页面上下文元数据不计数；元数据与真实请求混排时保留请求。旧版本误计的页面元数据会在该会话下次处理时自动从已处理计数中扣除。字数、关键词和主题变化不会提前触发。重新评估不等于强制换标题：原标题仍准确时保留，但成功评估后仍从零累计新增消息；失败或限流时保留进度。

冷却默认 600 秒，每个安装默认每天最多 500 次调用；因此达到内容阈值并不意味着立即调用。等待期间不会丢弃新增内容，冷却到期或额度恢复后，需要下一次 Hook 才会继续，没有后台定时重试。重复收到已处理轮次的 Hook 不会重复调用模型。

标题日期始终取会话开始时间。历史会话也只在之后触发 Hook 时处理，不批量扫描重命名。

<details>
<summary>调用、数据存储与手动标题保护</summary>

**模型调用**

使用 App Server 临时会话生成结构化 JSON，推理强度为 `low`。临时会话不持久化到对话列表，其中关闭 shell、apps、多代理和联网搜索，并设置环境变量防止递归触发命名。

**标题更新**

通过 `thread/name/set` 写入标题，写入前再次检查当前标题，写入后回读验证。不直接修改 Codex 的 `session_index.jsonl`、rollout 或数据库。同一安装记录中的重复自动标题会添加 `#2` 等后缀。

**手动保护**

成功自动命名后，如果当前标题不同于上次自动标题，就锁定该会话；模型推理期间发现标题变化也会锁定。首次接触会话时，工具无法可靠区分默认标题和先前手动设置的标题，因此保留已有包含 `｜` 的标题，其他标题仍可能被更新。

**本地记录与内容处理**

`data/index.sqlite` 保存摘要、标签、原标题、自动标题、锁定状态、调用用量和变更记录。接口未提供用量时记录为 `null`。审批副本、子代理、分叉、内部命名会话及未知来源会跳过；日志不兼容时跳过或记录失败，Hook 失败不会中断正常对话。

摘录会过滤部分常见凭据模式，但这不是完整的脱敏系统。模型调用沿用现有提供方。

</details>

## 常见问题

**为什么标题没有更新？**

先运行 `python3 scripts/namer.py doctor` 检查开关和 Hook 信任状态，再用 `python3 scripts/namer.py status` 查看近期调用和 `recent_events`。

| 事件或原因 | 含义 |
| --- | --- |
| `hook_received` | 脚本已收到 Hook 调用 |
| `hook_result` | 本次处理结果，包含执行或跳过原因 |
| `hook_error` | 异常类型；检查运行文件、环境及接口兼容性 |
| `awaiting_more_context` | 新增内容未达阈值；`pending_messages` 显示当前累计新增用户消息数 |
| `cooldown` / `daily_limit` | 等待冷却或调用额度恢复，处理进度保留 |
| `manual_title_locked` | 会话已被手动标题保护锁定 |

没有 `hook_received` 时，检查客户端是否重新加载并信任了此 Hook。`doctor` 的 `ready: true` 仅说明配置与信任就绪，不能证明客户端实际发出过 Stop，也不验证模型网络。源码配置不要覆盖已经启用的运行配置。

程序无法启动时，可用 `python3 -m py_compile scripts/namer.py` 检查语法；安装器也会在写入前检查 Python 文件语法。

**每天 500 次意味着固定费用吗？**

不是。它限制调用次数，不限制 token 或费用。Codex 运行时可能附加额外上下文，4000 字符也不代表总输入大小。实际用量取决于消息长度、附加提示、缓存和模型。

**可以换电脑使用吗？**

可以。复制发布源码，在目标电脑安装并登录 Codex CLI，再执行安装步骤。每个安装独立保存摘要、手动锁定状态和调用额度；迁移源码不会迁移这些记录。保持相同时区可保持标题日期的计算方式一致，模型配置不同则措辞可能不同。

**可以删除 `data/` 吗？**

删除会丢失原标题恢复信息、手动锁定状态和用量账本，不应作为常规清理操作。对外分发源码时则应排除该目录。

## 文件说明

```text
codex-conversation-namer/
├── scripts/
│   ├── namer.py        # 核心命名程序，包含原有逻辑
│   └── install.py      # 安装与 Hook 注册
├── tests/
│   └── test_namer.py   # 原有回归测试
├── config/
│   └── config.json     # 开关、调用上限及命名配置
├── README.md
└── .gitignore
```

目录调整只涉及文件位置和路径引用，命名规则保持不变。已有安装升级后需重新运行 `python3 scripts/install.py` 注册新 Hook 路径，并在 Codex `/hooks` 中审核信任。安装器保留已有配置和运行数据。

### 源码文件

| 文件 | 作用 |
| --- | --- |
| [`scripts/namer.py`](scripts/namer.py) | 会话提取、变化检测、模型调用、标题更新及管理命令 |
| [`scripts/install.py`](scripts/install.py) | 环境检查、文件安装、Hook 注册与备份 |
| [`config/config.json`](config/config.json) | 开关、限额、时区及自定义词表 |
| [`tests/test_namer.py`](tests/test_namer.py) | 使用虚构样例、临时目录和模拟 RPC 的单元测试 |
| [`README.md`](README.md) | 安装、使用与维护说明 |
| [`.gitignore`](.gitignore) | 排除运行数据、本机记录、缓存和本地凭据等文件 |

### 本地生成文件

以下内容不随源码发布：

| 路径 | 作用 |
| --- | --- |
| `installation.json` | 本机安装路径、Hook 命令与备份位置；重装时用于识别旧 Hook |
| `data/index.sqlite` | `threads` 保存会话状态，`calls` 保存调用和用量，`events` 保存变更及失败记录 |
| `data/<session-id>.lock` | 会话级进程锁，避免多个 Hook 同时处理同一会话 |
| `data/runtime/` | 模型临时命名会话的工作目录 |
| `__pycache__/` | 可自动重建的 Python 字节码缓存 |

## 开发与发布

当前版本：`1.1.1`。在源码目录运行测试：

```bash
python3 tests/test_namer.py
```

测试覆盖首次命名、第 10 条新增用户消息触发、长消息不会提前触发、冷却与失败重试、额度恢复、标题未变时的进度更新、手动保护、重复轮次，以及安装和 Hook 入口。`scripts/install.py --check` 仅检查运行环境与所需命名接口，不等同于完整端到端兼容性验证。

发布前，将 `config/config.json` 恢复为默认配置：`enabled=false`，自定义词表为空。按文件白名单打包：

```bash
tar -czf codex-conversation-namer-portable.tar.gz \
  scripts/namer.py scripts/install.py config/config.json tests/test_namer.py README.md .gitignore
```

`.gitignore` 不会移除已跟踪的文件，也不会影响手动复制整个目录。发布包应排除运行数据、安装记录、日志、凭据，以及 `.git/`、`.agents/`、`.codex/`、`.aws/` 等本地目录。

## 相关文档

- [Codex Hooks](https://learn.chatgpt.com/docs/hooks)
- [Codex App Server](https://learn.chatgpt.com/docs/app-server)
