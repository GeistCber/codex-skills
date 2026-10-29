# 开源借鉴与设计取舍

2026-10-29 查阅以下项目官方仓库文档；借鉴设计，不表示安装或集成了这些框架，也没有证据据此宣称哪一种方法是“大多数开发者”的统一选择。

| 来源 | 已核对的实践 | 本技能采用 | 适用界限 |
|---|---|---|---|
| [Playwright Trace Viewer](https://github.com/microsoft/playwright/blob/main/docs/src/trace-viewer-intro-js.md) | 按操作回看前后状态，关联日志、源码、网络及错误 | 用例/步骤关联操作状态、完整结果和失败证据 | DOM 快照不是 CAD 画布截图；本技能没有集成 Trace Viewer |
| [Playwright Reporters](https://github.com/microsoft/playwright/blob/main/docs/src/test-reporters-js.md) | 同一执行结果可输出多个 reporter，支持 JSON/HTML 等及重试信息 | 单一 JSON 事实记录，派生 Markdown/HTML，保留每次尝试 | 报告器不自动证明业务覆盖完整 |
| [Playwright Actionability](https://github.com/microsoft/playwright/blob/main/docs/src/actionability.md) | 动作前检查唯一目标、可见、稳定、可接收事件和启用，超时失败 | 输入前状态检查、有限等待、失败即停，不盲点 | Web 框架提供的保证不能直接许诺给 Windows 全局键鼠；必须核实驱动能力 |
| [Robot Framework Execution Artifacts](https://github.com/robotframework/robotframework/blob/master/doc/userguide/src/ExecutingTestCases/ExecutionArtifacts.rst) | 机器可读 XML/JSON 结果生成 HTML 日志/报告，可后处理 | 数据与展示分离、稳定目录、可续接的结构化结果 | 不为采用此模式而引入框架；具体 JSON 输出依赖相应版本 |
| [FlaUI](https://github.com/FlaUI/FlaUI) | 基于 Windows 原生 UI Automation，面向 Win32/WinForms/WPF 等 | 有语义定位时优先复用，按应用评估控件支持 | UIA 并不提供任意软件免焦点控制，更不等于用户可同时办公 |

这些项目分别解决观察、操作前提、结果记录和阅读体验。需求/资源/组合的覆盖分母、桌面占用通知及共享桌面的暂停约定，是针对本用户需求补充的执行规则；没有冒称某框架已替我们解决 AI 键鼠不可控。

没有选择直接安装完整报告平台：当前场景先需要本地离线看图、AI 续接和少依赖，标准库生成器足够。团队已有 Allure、Robot 或其他体系时复用其结构，建立相同的覆盖和证据关系即可。
