---
name: background-testing-off
description: 用户明确调用本技能、输入 /background-testing_off、/background-testingoff 或要求关闭后台测试模式时，只关闭持久开关并确认；主技能禁用时仍可使用。
---

# 关闭后台测试模式

独立入口，仅在用户明确要求执行关闭时操作。引用、示例或询问命令含义不改变状态。

用编辑工具检查 `C:\Users\Laptop\.codex\config.toml` 中路径为 `C:\Users\Laptop\.codex\skills\background-testing\SKILL.md` 的 `[[skills.config]]` 项，把 `enabled` 设为 `false`；不存在时添加一项，保留其他配置。匹配路径忽略 Windows 大小写与分隔符差异，不制造重复项；若已有重复项，先核对并仅合并该主技能的配置。不要用 Python/Shell 重写配置。

回读确认后简洁回复“后台测试模式已关闭”。不扫描业务项目、不执行测试、不删除脚本、夹具或报告，不修改业务任务提示词或 Git 同步开关。之后跳过此技能的自动模式，不直接读取主技能绕过关闭；on/off 独立入口仍可用，状态持续至用户明确开启。

关闭只控制后续自动调用，不声称已停止其他任务或独立测试进程。若用户同时明确要求停止正在运行的测试，只处理当前任务拥有且身份已核对的测试进程，并如实报告。用户另行明确要求单次普通测试时按请求执行，不自动重启持久模式。
