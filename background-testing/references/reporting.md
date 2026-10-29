# 结构化报告规范

## 格式选择

| 形式 | 优点 | 局限 | 本技能用法 |
|---|---|---|---|
| Markdown + 图片 | AI 易读、易搜索、Git 差异清楚 | 大量截图的筛选和对照较弱 | 默认可读报告 |
| HTML + 图片 | 离线打开、图文对照、筛选方便 | 手写内容易与原记录漂移 | 视觉密集验收的阅读入口 |
| JSON + 附件 | 稳定 ID、精确状态和关联，便于续接/校验 | 人直接阅读较费力 | 唯一事实记录 |

默认组合为一份 `run.json` 和附件，由同一份数据生成 Markdown；桌面视觉验收同时生成离线 HTML。不建立网页服务，不依赖 CDN，不复制大型二进制进 JSON。已有 Allure/Robot/其他报告可保留，补足覆盖关系和直接入口即可，不为了本技能重建框架。

```text
tests/TestResults/<时间-主题-唯一ID>/
  run.json
  report.md
  report.html
  images/                 # 操作状态、全景、细节；文件名包含用例/尝试 ID
  references/             # 本轮对照材料或获准保存的局部，标清来源
  logs/                   # 原始日志、对象清单、脚本输出
  data/                   # 需要保留的测试副本；大文件按项目规则存放
```

目录沿用项目已有验证结构，不要求固定大小写或迁移路径。所有报告附件使用相对于本轮目录的路径；来源原文件路径及指纹只作元数据。移动目录后仍应能阅读，不引用临时绝对图片路径。

## run.json 版本 1

参考可解析的 [演示](../assets/report-example/run.json)，它有意包含失败、未测与暂缓，不能作为业务证据。

| 字段 | 记录内容 |
|---|---|
| schema_version / run_id / title / project | 版本号 1、本轮唯一 ID、主题和项目 |
| is_demo | 真业务填 false；演示始终标 true |
| phase / control / events | 当前生命周期及已发通知事件；事件含 at、phase、control、notice |
| inventory | complete、sources、strategy；是否完成本轮声明范围的盘点、原始来源和等价类/组合选择依据 |
| inputs | 对应本轮源数据的 path、sha256；没有文件输入时允许空数组并在 inventory 说明 |
| build | revision、dirty_state、artifact_sha256、config；无构建项目用源码/包指纹，不能凭空填提交号 |
| desktop | 可选；authorization、target、limits、stop，记录已有授权和实际目标，不能制造授权 |
| coverage | id、kind、title、scope、reason、required_case_ids；kind 为 requirement/resource/combination/workflow，scope 为 in/deferred/not_applicable |
| cases | 稳定 id、title、purpose、method、parameters、preconditions、steps、expected、attempts |
| attachments | id、path、kind、caption；可选 sha256；真实截图 desktop_screenshot、原生导出 native_export、参考 reference、日志 log、演示 illustration |
| limitations | 范围差距、证据复用及未能验证的事项；即使没有失败也写明适用边界 |
| previous_run | 可选；上一轮 ID 或位置，用于关联修复前记录 |

`purpose` 为 acceptance 或 diagnostic。`method` 为 desktop_ui、window_integration、host、script。字段必须表达实际入口，不能按期望的验收层次命名。

`expected` 含 source 和 description，说明独立来源和可观察标准。参数及预期在执行前写入；不能看结果后移动标准。

覆盖项、用例、尝试和附件的 ID 使用字母/数字开头，后续可含字母、数字、点、横线和下划线。时间用带时区的 ISO 8601，按实际发生顺序记录。真实运行的输入/构建指纹使用 64 位十六进制 SHA256，示例不得冒填真实指纹。

每次 `attempts` 元素记录 id、at、status、observed、reason、evidence（附件 ID 数组）、review（比较说明）。有效尝试至少有实际观察；失败、阻塞、错误、未测写具体原因。Passed 的 review 必须含 outcome=matched 及非空 note。截图要真正检查：在 note 说明对照了什么，而不是“截图已生成”。`origin` 可标 product/environment/test_setup/driver/unknown，帮助区分根因，不能把未经定位的崩溃都归为插件缺陷。

真实 `desktop_ui` 的 Passed 至少关联一张 desktop_screenshot；native_export 或 illustration 不能替代。视觉密集场景额外保留参考/完整图/关键细节，保留可核对总量和范围。脚本结果也需附可追溯日志或数据。生成器只能检查记录及文件，不能代替独立判断截图内容。

同一输入和构建重试可追加 attempts，最后一次决定该用例当前状态，较早失败仍展示。失败/错误后重试成功会标注稳定性待复核，整轮仍为 Incomplete；原因明确且稳定性复测在新 run 完成后才能交付通过，新轮关联原失败记录。改代码/构建、输入或测试配置后也创建新 run；完整结论的必需用例必须有新版本匹配证据，或明确按影响分析复用并标记历史，不能混记成当前轮实跑。

## 状态与覆盖计算

### 新轮功能级配置

保留版本1旧报告的读取能力；新轮添加 `profile: "functional-v1"`，旧轮不补造冻结记录。新配置增加：

- `inventory.dimensions`：每项有 id、title、strategy、selected、uncovered。selected 为 value 与 case_ids；uncovered 为 value 与 reason。范围内应测而未测的值，另建 NotRun 用例并关联覆盖项，不能只藏在说明里。
- `expected.checks`：每项有 id、description、target；数值可带 unit、tolerance（默认0）。target 是独立确定的具体数值、清单或状态，避免只有“结果正确”。
- 尝试的 `checks`：每项有 id、value、status，逐一对应预期。Passed 尝试必须核对全部检查点；数值超容差或其他值不等时禁止标 Passed。Failed/Error 可保留已完成的部分检查，不能补造未观察值。
- `plan`：path、sha256、frozen_at，指向执行前冻结的 `plan.json`。其中保存输入/构建、盘点、覆盖及各例参数/步骤/预期。生成器核对指纹和内容，阻止事后改标准；它不提供防篡改存证或证明预期来源真实。
- 复用尝试标 `evidence_origin: "historical"`，同时写 evidence_run 和 reuse_reason；核对版本和影响后引用，不改原尝试时间、不声称本轮实操。
- 生命周期至少记录实际的 inventory→planning→preflight，随后按实际操作记录接管、暂停、恢复、补充与结束；当前 phase/control 必须匹配最后事件。暂停后恢复记录 resume_authorized=true，依据来自用户指示或事先约定，不由工具制造授权。

用 `session.py <run.json> event --phase planning --notice "已在聊天中通知的摘要"` 记录事件；事件不发送聊天消息。计划确定后执行 `session.py <run.json> freeze`，再进入预检及实操。它只更新本轮测试记录，不修改技能开关。新场景/新标准、新构建或输入建立关联新轮。

- 用例：Passed（符合预期）、Failed（观察到行为不符）、NotRun（尚未执行）、Blocked（前提或依赖未满足）、Error（执行器/环境未能完成判断）。无 attempts 默认 NotRun。
- 每个 in 覆盖项列全必需验收用例，所有最新状态 Passed 且没有失败后重试的稳定性待复核项才算通过；稳定性待复核时覆盖项记 Blocked，不能用诊断用例填分子。分项展示“通过项/声明范围内项”，同时列已规划、未测/阻塞和范围外项。
- 所有 in 项通过且无其他验收失败/未测、盘点完整：Passed。存在 deferred 或 not_applicable：PassedWithinScope，标题写“声明范围内通过”，同时显示具体差距。
- 有 Failed/Error：Failed；其余有 NotRun/Blocked、空验收集、盘点不完整或尚未 finished/released：Incomplete。诊断失败也需展示并阻止无保留的通过结论；诊断成功不能让失败验收通过。
- is_demo=true 的结果永远为 Demo，不参与业务验收。缺附件、引用不存在、重复 ID、非法状态或结构损坏属于无效报告，不能照常输出绿色结论。

结论只针对声明的覆盖清单，生成器不证明清单已经穷尽需求。即使显示 100%，仍需审阅其分母、原始依据和暂缓范围。执行器、生成报告和产品验收是三个不同的成功条件。

## 生成与交付

```text
python <技能目录>/scripts/report.py <本轮目录>/run.json
python <技能目录>/scripts/report.py <本轮目录>/run.json --check
python <技能目录>/scripts/report.py <本轮目录>/run.json --require-pass
```

生成器只读 run.json 和附件，在该目录生成/更新派生的 report.md/report.html；不改业务源文件、配置或原图。`--check` 只读校验；默认退出码 0 表示报告有效且生成成功，**即使产品失败也可能为 0**。`--require-pass` 仅在 Passed 或 PassedWithinScope 时返回 0（仍需审阅范围）；产品失败/未完成/演示返回 1，无效报告返回 2。它不执行测试、不接管桌面，也不证明 on/off 控制已经实际切换。

每例展示参数、前提、步骤、独立预期、实际观察、尝试历史和图片，新配置逐点列预期/实际/结果。首页将无失败重试的通过与重试后通过分列；历史格式明确标识。业务观察使用中文摘要，原始英文断言或JSON放日志附件，不能把它们直接当成面向开发者的说明。先看失败/未测，再看覆盖矩阵和逐例；保留全景与细节的联系。HTML 提供状态筛选和搜索，图片可点开。摘要分别统计实操、窗口集成、宿主和脚本，不能把脚本断言数混成实操流程数。

交付前运行校验，打开 HTML 检查图片/中文/链接，再抽查至少一例失败/未测是否如实表达。最终给直接文件链接，概述当前阶段、桌面已释放、通过/失败/未测及暂缓。数据量大时摘要仍来自同一个记录，禁止另写一份不同结论。
