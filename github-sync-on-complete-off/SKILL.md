---
name: github-sync-on-complete-off
description: 用户明确调用本技能或发出/github-sync-on-complete_off及/github-sync-on-completeoff命令时，关闭Git同步完成检查功能；只切换开关并确认，不提交或上传，不修改业务任务提示词。
---

# 关闭 Git 同步

本技能是独立开关入口，主技能被禁用时仍可使用。仅在用户明确要求执行关闭时操作；引用或询问命令含义不应改变状态。

用编辑工具检查并修改`C:\Users\Laptop\.codex\config.toml`中路径为`C:\Users\Laptop\.codex\skills\github-sync-on-complete\SKILL.md`的`[[skills.config]]`项，将`enabled`设为`false`；不存在时添加一个配置项，不制造重复项，保留其他配置。不要用Python或Shell脚本重写配置文件。

回读并验证状态后，仅简洁回复“Git同步已关闭”。不扫描项目、不提交、不上传、不弹上传确认。后续任务跳过自动完成检查与上传选项；不得通过直接读取主技能文件绕过关闭状态。开关持续关闭，直到用户调用on入口或明确要求开启。
