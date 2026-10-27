# AutoCAD 插件示例（按需读取）

先读取受测项目的适用规则。不要因为使用此示例就加载 CAM/xTubeNest 专属规则或扫描其他项目。

## 可复用做法

- 纯算法进程加 `accoreconsole.exe` 作为日常路径：验证数据库实体、单位/变换、事务回滚、保存重开、原生命令和插件加载；先确认所需 API 在当前宿主及版本受支持。
- `acad.exe`、面板和屏幕驱动单列。依赖 Editor、交互选择或图形系统的能力不能自动归为无界面兼容；不能把打印引擎导出 PNG 称为桌面截图。
- 原题数据采用共享只读访问并校验指纹，避免锁住用户已打开的 DWG；测试写入副本或独立产物。
- 真实输入驱动需明确启用且锁定自己创建的目标实例。启动、附加和退出均不操作用户办公实例。

## 已有实践定位

仅在当前会话确实指向该项目时，使用 `D:\project\CadPracticeVerification` 的现有入口：

| 用途 | 路径 |
|---|---|
| 默认后台 | `Scripts\RunChecks.ps1` → `RunBackgroundChecks.ps1 -Suite All` |
| 后台专项 | `RunBackgroundChecks.ps1 -Suite Regression/Storefront/Mapping/MappingIndex/MappingMultiFace`，每次选一个值 |
| 桌面集成 | `Scripts\RunDesktopChecks.ps1` |
| 真实输入 | `Scripts\MappingGuideDriver.ps1`，显式 `-AllowDesktopInput`，非 Launch 操作指定 `-TestProcessId` |
| 方法、来源和覆盖 | `Docs\后台与桌面测试分离-20261027.md` |

默认资源值是该项目的选择：单宿主串行、BelowNormal、进程私有内存 2048MB、系统物理/提交空间各保留 1024MB、步骤超时 180 秒。其他项目按数据规模调整，不照搬成通用门槛。

2026-10-27 的历史证据为 `TestResults\Background\Run-20261027-165936589-4af7e6e6\run-manifest.json`：13 组、1778 项后台断言通过，调度器另有 21 项回归；这是历史基线，后续使用须核对当前输入、程序集、测试脚本及报告，不能固定宣称每轮均为该数量或所有交互已经通过。

旧 `CompareMapping.py` 的全场景 oracle 来自 10 月 21 日图纸与早期四类柜体，不能直接套用 10 月 27 日移动后的平面和 29 类规则。当前 `--templates-only` 只作模板独立比较；另有索引、多面检查。保留旧全场景失败差异并将该范围记为 NotRun，现代完整场景的独立期望仍需依据当前原图及已确认规则建立。此例用于说明基准版本和未测范围，不允许遇到失败就一律缩小检查。
