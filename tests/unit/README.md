# B1 输出服务 · 验证留痕（提交 ①）

分支：`feat/b1-copy-image`；提交 ① `[B1] 接入输出快照与剪贴板服务`。
契约草案见 `docs/issue-b1-contract.md`（本地文档，不入库）。

## 阶段 2 测试

| 命令 | 结果 |
| --- | --- |
| `python -m unittest discover -s tests/unit -v` | **7/7 通过** |
| `python -m compileall -q src/e2s/output tests/unit` | 通过 |
| 格式门禁（4 个 `.py`：UTF-8、末尾换行、行尾空白、TAB、行宽 100） | 0 不合格 |

当前环境未安装 pytest；用例以标准库 `unittest.TestCase` 编写，pytest 安装后可直接收集，
无需改写。样本为 2×2 合成色块，不含真实截图数据。

覆盖项：① 成功写入并返回 `succeeded`；② 写入失败返回 `clipboard_write_failed`，
且可按同一 `operation_id` 重试成功；③ 取消不写入；④ 队列满在写入前返回 `busy`；
⑤ 快照 `frozen` 不可变；⑥ 非法尺寸与空像素被拒绝；⑦ `TaskState` 与前端 5 个状态值一致。

## 阶段 3 代码评估（8 项）

| 项 | 结论 |
| --- | --- |
| 风格 | 通过：模块/函数 `snake_case`、类与异常 `PascalCase`、枚举成员大写、布尔 `is/has` 前缀、内部成员单下划线、4 空格缩进、约 100 字符 |
| 功能 | 通过（限 ① 范围）：合成快照写入剪贴板、失败保留编辑状态并允许重试；未越界实现 B2 保存 |
| 契约 | 通过：`operationId`/`sessionId`/`widthPx` 与 `frontend/src/bridge/types.ts` 对应，`TaskState` 5 值一致，错误码稳定 |
| 架构 | 通过：服务只依赖 `ports.py` 协议，不持有窗口对象、不调用 Qt API；PEP 420 命名空间包，未创建 `__init__.py` 或 `pyproject.toml`（属 A） |
| 健壮性 | 通过：互斥状态用单一枚举；成功/失败/取消/忙碌四分支可复现；结果按 `operation_id` 关联 |
| 资源与隐私 | 通过：无像素或剪贴板正文写入日志；样本仅 2×2 色块；忙碌分支在分配前退出 |
| 安全 | 通过：无外链、无动态求值、无用户输入求值 |
| 回归 | 通过：从最新 `origin/main` 建分支，仅新增 `src/e2s/output/` 与 `tests/unit/`，未改动已合入文件 |

**结论：通过**。非阻断观察项：`parameters` 运行时为可变 `dict`（服务不修改，后续可收紧为
`MappingProxyType`）；pytest 未安装；A 的 `pyproject.toml` 与仓库基础尚未建立，
正式包配置待联调后复验。

## 未覆盖（如实记录）

- 真实 Qt GUI 线程剪贴板与 A4 实际快照（PR-03 的第 ③ 次联调提交，待 A4）。
- 两个外部桌面程序的粘贴尺寸验收（B1 完成条件，待 A4）。
- 文件命名、暂存与保存（PR-04 B2，不在本提交范围）。
- Windows 真机的混合 DPI、热键与系统对话框验证。

## 提交 ② · `[B1] 验证失败恢复和粘贴尺寸`

新增 `samples.py`（合成色块与 5 组尺寸样本）、`test_paste_dimensions.py`、
`test_failure_recovery.py`；**未改动 ① 的产品代码**。

### 阶段 2 测试

| 命令 | 结果 |
| --- | --- |
| `python -m unittest discover -s tests/unit -v` | **15/15 通过**（① 7 项 + ② 8 项） |
| `python -m compileall -q src/e2s/output tests/unit` | 通过 |
| 格式门禁（7 个 `.py` + 本 README） | 0 不合格 |

覆盖项（②）：1×1 边缘、2×2、17×9 奇数、1920×1080、2560×1440 混合 DPI 共 5 组尺寸的
像素长度、首尾特征与写入一致性；复制像素与保存基准一致；`seed` 只改像素不改尺寸；
连续两次失败后按同一 `operation_id` 重试成功；失败不修改快照；取消优先于忙碌；
忙碌错误码不污染成功结果；取消后允许重试。

### 阶段 3 代码评估（8 项）

| 项 | 结论 |
| --- | --- |
| 风格 | 通过：`test_*.py`、`snake_case`、4 空格缩进、约 100 字符 |
| 功能 | 通过：仅覆盖 B1 ② 的验证范围，未越界实现 B2 保存或 ③ 真实链路 |
| 契约 | 通过：`channels=4` 与像素长度公式一致，错误码与 5 个状态值稳定 |
| 架构 | 通过：测试只依赖 `e2s.output` 与模拟 writer，不依赖 Qt 或窗口对象 |
| 健壮性 | 通过：失败、取消、忙碌边界与重试语义均可复现 |
| 资源与隐私 | 通过：最大样本 2560×1440×4 ≈ 14.7 MB 合成色块，无真实截图 |
| 安全 | 通过：无外链、无动态求值、无用户输入求值 |
| 回归 | 通过：未改动 ① 产品代码，仅新增测试与文档 |

**结论：通过**。提交前已修正契约草案：把 `pixel_budget_exceeded` 标注为
F4 / 超大图预算阶段实现，避免与「B1 首版仅实现 `queue_full`」的事实不一致。

### 仍未覆盖

- 真实 Qt GUI 线程剪贴板与 A4 实际快照（PR-03 的第 ③ 次联调提交）。
- 两个外部桌面程序的粘贴尺寸验收（B1 完成条件，待 A4）。
- 文件命名与保存（PR-04 B2）、Windows 真机混合 DPI 与系统对话框。

## PR-04 提交 ① · `[B2] 实现 PNG 编码和无覆盖保存`

分支 `feat/b2-save-image`；新增 `src/e2s/output/files.py`、`tests/unit/test_save_files.py`。
契约草案见 `docs/issue-b2-contract.md`（本地文档，不入库）。

### 阶段 2 测试

| 命令 | 结果 |
| --- | --- |
| `python -m unittest discover -s tests/unit -v` | **22/22 通过**（既有 15 项 + ① 7 项） |
| `python -m compileall -q src/e2s/output tests/unit` | 通过 |
| 格式门禁（9 个 `.py`） | 0 不合格 |

覆盖项：文件名格式与序号后缀、PNG 签名与 Pillow 读回尺寸/像素、快速保存落盘、
同秒两次保存产生不同文件、已有文件字节不变、目录不存在返回 `directory_not_writable`、
临时文件不残留。

### 阶段 3 代码评估（8 项）

| 项 | 结论 |
| --- | --- |
| 风格 | 通过：`snake_case` 模块与函数、`PascalCase` 数据类、常量大写、4 空格缩进、约 100 字符 |
| 功能 | 通过：仅覆盖 ① 的 PNG 编码与无覆盖保存，未越界实现 ② 另存 |
| 契约 | 通过：`E2S_yyyyMMdd_HHmmss.png`、`TaskState` 5 值、错误码稳定，与 B1 共用 `OutputSnapshot` |
| 架构 | 通过：输出层内聚，不依赖 Qt 或窗口对象；临时文件与目标同目录 |
| 健壮性 | 通过：目录不存在、编码失败、发布失败、序号耗尽四类分支均有稳定结果 |
| 资源与隐私 | 通过：临时文件立即清理，样本为合成色块，无像素写入日志 |
| 安全 | 通过：目标名由服务在输出目录内生成，不接受外部路径，无动态求值 |
| 回归 | 通过：未改动 B1 的 `service.py` / `ports.py` / `mock.py`，仅新增文件 |

**结论：通过**。非阻断观察项：`os.link` 在非 NTFS 或跨卷文件系统可能不可用
（本环境已验证可用并会在失败时返回 `write_failed`）；pytest 未安装；
A 的 `pyproject.toml` 未建立；另存、覆盖确认与错误恢复属提交 ②。

## PR-04 提交 ② · `[B2] 接入另存、覆盖确认及错误恢复`

`files.py` 新增 `save_as`、`_encode_payload`、`_publish_with_overwrite`；
`quick_save` 增加取消分支与权限错误映射；新增 `test_save_recovery.py`。

### 阶段 2 测试

| 命令 | 结果 |
| --- | --- |
| `python -m unittest discover -s tests/unit -v` | **32/32 通过**（既有 22 项 + ② 10 项） |
| `python -m compileall -q src/e2s/output tests/unit` | 通过 |
| 格式门禁（10 个 `.py`） | 0 不合格 |

覆盖项：新路径另存成功；目标已存在且未确认覆盖返回 `cancelled` / `overwrite_not_confirmed`
且原文件字节不变；确认覆盖后内容更新为正确 PNG；取消不写任何文件；父目录不存在返回
`directory_not_writable`；写入失败保留已有文件且不残留临时文件；快速保存取消不落盘；
失败后按同一 `operation_id` 重试成功；取消优先于覆盖确认。

### 阶段 3 代码评估（8 项）

| 项 | 结论 |
| --- | --- |
| 风格 | 通过：新增方法 `snake_case`、布尔 `is_*` 前缀、私有成员单下划线、4 空格缩进 |
| 功能 | 通过：覆盖 ② 的另存、覆盖确认与错误恢复，未越界实现 ③ 系统对话框 |
| 契约 | 通过：错误码 `overwrite_not_confirmed` / `write_failed` / `directory_not_writable` / `encode_failed` 稳定，状态值不变 |
| 架构 | 通过：`os.replace` 原子发布，临时文件与目标同目录，不依赖 Qt 或窗口对象 |
| 健壮性 | 通过：取消优先级、写入失败不破坏已有文件、失败重试、临时文件清理均可复现 |
| 资源与隐私 | 通过：临时文件在成功与失败路径都清理，样本为合成色块，无像素写入日志 |
| 安全 | 通过（有观察项）：无动态求值；未确认覆盖或取消时不写入 |
| 回归 | 通过：B1 与 PR-04 ① 的既有测试全部保持通过，未改动其产品代码 |

**结论：通过**。非阻断观察项：另存目标路径未做输出目录白名单校验，
依赖 A 的系统文件对话框返回可信路径（可在 D4 设置校验中补充约束）；
`os.link` 跨卷可用性；pytest 未安装；A 的 `pyproject.toml` 未建立。

### 仍未覆盖

- 真实系统文件对话框、A4 实际快照与 GUI 线程适配（PR-04 的第 ③ 次联调提交）。
- 默认输出目录 `EasyToShot` 的定位与可写性检查（`storage/paths.py`，后续 PR）。
- Windows 真机的混合 DPI、用户另存路径权限与系统对话框取消行为。
