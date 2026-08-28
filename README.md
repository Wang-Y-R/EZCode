# EZCode

一个在终端运行的编程智能体（Coding Agent）。

它通过与大语言模型交互，自主地读写文件、执行命令，完成交给它的编程任务——类似一个简化的 Claude Code。核心逻辑（agent 循环、对话历史与上下文管理、工具定义与本地执行、模型输出解析、循环终止条件、错误处理）全部自行实现，不依赖任何 agent 框架。

## 技术栈

- Python 3.11+
- Anthropic Messages API（原生 tool calling）
- [`anthropic`] 官方 Python 客户端库（异步 + 流式）
- `prompt_toolkit` 提供终端输入历史
- `rich` 提供流式 Markdown / 面板渲染
- `python-dotenv` 读取环境变量

## 功能规划

见 [TODO.md](./TODO.md)。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量
#    Windows:  copy .env.example .env
#    Linux/macOS: cp .env.example .env
#    然后编辑 .env，填入 ANTHROPIC_API_KEY 和 MODEL_ID

# 3. 运行
python -m ezcode            # 进入交互式 REPL（输入任务回车发送，q 退出）
python -m ezcode "你的任务"  # 单次执行
```

## 目录结构

```
EZCode/
├── ezcode/
│   ├── __init__.py
│   ├── config.py       # 环境变量、模型端点、系统提示词、shell 探测
│   ├── tools.py        # 工具定义与本地执行（bash / read / write / edit / glob）
│   ├── permission.py   # 权限规则：硬拒绝表 + 启发式规则匹配
│   ├── hooks.py        # hook 系统：事件注册 + 触发，扩展不侵入循环
│   ├── agent.py        # 核心循环：流式调用 + hook 触发 + 工具执行
│   ├── cli.py          # prompt_toolkit + rich 的终端交互界面
│   └── __main__.py     # 入口（python -m ezcode）
├── requirements.txt
├── .env.example
├── TODO.md
└── README.md
```
