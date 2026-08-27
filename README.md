# EZCode

一个在终端运行的编程智能体（Coding Agent）。

它通过与大语言模型交互，自主地读写文件、执行命令，完成交给它的编程任务——类似一个简化的 Claude Code。核心逻辑（agent 循环、对话历史与上下文管理、工具定义与本地执行、模型输出解析、循环终止条件、错误处理）全部自行实现，不依赖任何 agent 框架。

## 技术栈

- Python 3.11+
- Anthropic Messages API（原生 tool calling）
- [`anthropic`](https://github.com/anthropics/anthropic-sdk-python) 官方 Python 客户端
- `python-dotenv` 读取环境变量

## 功能规划

见 [TODO.md](./TODO.md)。

## 快速开始

> 尚未实现，待补充。

## 目录结构

> 尚未实现，待补充。
