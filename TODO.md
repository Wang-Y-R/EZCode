# TODO

> 目标：一个在终端运行的编程智能体，从最小循环出发，逐步叠加 harness 机制。

## 待实现（S01–S11）

- [ ] **1 Agent Loop** —— 最小循环：`messages` + `while` + `tool_use`，一个 bash 工具即可跑通
- [ ] **2 Tool Use** —— 多工具（read / write / edit / glob）+ dispatch map，路径沙箱
- [ ] **3 Permission** —— 权限审批管线，破坏性操作先判断能否执行、是否询问用户
- [ ] **4 Hooks** —— PreToolUse / PostToolUse 扩展点，不改主循环也能扩展
- [ ] **5 TodoWrite** —— 先列计划再执行，提高长任务完成率
- [x] **6 Subagent** —— 给子任务全新的 `messages[]`，最终文本作为一条工具结果返回
- [x] **7 Skill Loading** —— 技能先列目录，用到时再按需展开注入
- [x] **8 Context Compact** —— 上下文压缩（budget / snip / micro / summary 四步）
- [x] **9 Memory** —— 记忆系统（筛选 / 提取 / 整理三个子系统）
- [x] **10 Task System** —— 文件持久化的任务图（TaskRecord / blockedBy）
- [x] **11 Background Tasks** —— 慢操作丢后台线程，完成后注入通知
