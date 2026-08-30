EZCode —— 终端编程智能体

一个在终端运行、与 Claude 交互的编程智能体：它自主读写文件、执行命令，完成交给它的编程任务，类似一个精简的 Claude Code。

【仓库地址】
https://github.com/Wang-Y-R/EZCode

【运行方法】
1. 安装：pip install -e .
2. 配置密钥：复制 .env.example 为 .env，填入 ANTHROPIC_API_KEY 与 MODEL_ID
   （密钥只放环境变量或未提交配置，绝不写入仓库）
3. 启动：
   - 交互式：ezcode
   - 单次执行：ezcode "你的任务"
   - 或：python -m ezcode [任务]

【核心特性】
- 自研 Agent 循环：流式调用 + 工具执行 + 循环终止，全部自己实现，不依赖任何 agent 框架
- 对话历史与上下文管理：token 预算 + 四步压缩（截断 / 裁剪 / 微压缩 / 摘要）
- 本地工具：bash / read / write / edit / glob / grep / todo_write，路径沙箱防止越权
- 权限审批：可切换权限模式（auto / ask / bypass）+ 危险命令拦截
- Hooks 扩展点：PreToolUse / PostToolUse，不改主循环即可扩展
- 子 Agent：全新上下文执行子任务
- Skill 加载：技能目录按需注入
- 跨会话记忆：召回 / 提取 / 整理三个子系统
- 任务图：文件持久化的 Task + 依赖（blockedBy）
- 后台任务：慢命令丢后台线程，完成后注入通知

【权限模式】
REPL 输入 /perm auto|ask|bypass 运行时切换，环境变量 EZCODE_PERMISSION_MODE 设初值。

模式      bash普通   bash危险   write/edit   read/grep越界   硬拒绝表
auto      放行      询问       越界才问     询问           拦截
ask       询问      询问       询问         询问           拦截
bypass    放行      放行       放行         放行           拦截

说明：ask 模式对会改变状态的操作（bash / write / edit）一律询问；工作区内只读（read / grep）始终放行；硬拒绝表（sudo、rm -rf / 等）任何模式都不放行。

【项目结构】
EZCode/
├── ezcode/            核心包
│   ├── config.py      环境变量、模型端点、系统提示词、shell 探测
│   ├── tools.py       工具定义与本地执行
│   ├── todo.py        TodoWrite 任务列表
│   ├── tasks.py       Task 系统（持久化任务图 + blockedBy）
│   ├── background.py  后台任务
│   ├── skill.py       技能加载
│   ├── compact.py     上下文压缩
│   ├── memory.py      跨会话记忆（召回/提取/整理）
│   ├── permission.py  权限规则
│   ├── hooks.py       Hook 系统
│   ├── agent.py       核心循环
│   ├── cli.py         终端交互界面
│   └── __main__.py    入口
├── skills/            技能目录（skills/<name>/SKILL.md）
├── .memory/           跨会话记忆（运行时生成）
├── .tasks/            任务图（运行时生成）
├── pyproject.toml     打包配置
├── requirements.txt
├── .env.example       环境变量模板
├── TODO.md
├── README.md
└── README.txt

【设计说明】
对话历史与上下文管理、工具定义与本地执行、模型输出解析、循环终止、错误处理等核心逻辑均为自行编写，仅使用 Anthropic 官方客户端库完成模型调用。
