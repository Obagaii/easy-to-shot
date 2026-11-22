# PR-02 代码评估报告 · 前端基线

依据：AGENTS.md 第 2 节「阶段 3 · 代码评估」8 项清单；`e2s_style.md`、
`e2s_function.md`、`e2s_struct.md`、`snow_function.md` 第 10 节。
对象：`chore/web-workbench-bootstrap` 分支下的 `frontend/` 与 `scripts/build-web.ps1`。
前置：阶段 2 测试通过（`npm ci` / typecheck / `vite build` / 桥接测试 9/9，见 `TEST_REPORT.md`）。

## 1. 八项评估

| 项 | 结论 | 依据 |
| --- | --- | --- |
| 1 风格 | 通过 | 组件文件 PascalCase.tsx、Hook `useReducedMotion.ts`、模块与目录 kebab-case/小写；CSS 类名与自定义属性符合约定；TS 类型 PascalCase、变量与函数 camelCase；界面文案简体中文；2 空格缩进、UTF-8、末尾换行、无行尾空白、行宽约 100 字符（格式门禁） |
| 2 功能 | 通过（限阶段 0 范围） | 左侧导航首次显示历史、标题区「新建截图」、历史卡片网格与 Skeleton/Empty、预览 Drawer、删除确认 Modal、设置表单与实际热键状态；阶段 0 要求的设置开关、预览抽屉、确认弹窗均由 antd 组件实现。D3/D4 的真实接口验收留给后续 PR |
| 3 契约 | 通过 | `WorkbenchBridge` 方法名与载荷 camelCase（`operationId`、`widthPx`、`schemaVersion`）；模拟实现与真实实现同构；任务状态值与错误码稳定；字段变更时的同步责任写入 README 联调清单 |
| 4 架构 | 通过 | 目录与 `e2s_struct.md` 第 3 节一致（`app/`、`pages/`、`bridge/`、`styles/`）；依赖方向仅 `frontend → bridge → 宿主`，业务页面不直接操作系统 API；`bridge/` 同时提供真实与模拟接口 |
| 5 健壮性 | 通过 | `TaskState` 用单一状态值表达互斥状态；任务结果按 `operationId` 关联，`App` 用 `isActive` 标志避免旧任务覆盖已切换视图；`onTaskFinished` 返回取消订阅函数；模拟实现覆盖 `not_found` 与非法设置错误码（测试 3/6/8） |
| 6 资源与隐私 | 通过 | 无日志写入截图像素、OCR 内容或剪贴板正文；模拟数据仅含编号、UTC 时间、来源、尺寸、字节数；无大图缓冲与任务队列 |
| 7 安全 | 通过 | 页面不含外链或动态求值；`previewUrl` 使用应用自有 scheme；`base: './'` 限制在本地静态资源；`QWebChannel` 对象经显式白名单判断后才连接 |
| 8 回归 | 通过 | 分支从 `origin/main`（`fa4d970`）建立，新增 `frontend/` 与 `scripts/build-web.ps1`；不修改 A 侧目录，不影响已跟踪的 `LICENSE`、`README.md` |

## 2. 发现的问题与处理

### 已在提交前修正

- **格式超长行**：提交 1 初稿的 `HistoryPage.tsx` 有 3 行超过 100 字符目标值，
  已按字段逻辑换行后重跑格式门禁，12 个文件 0 不合格。按 AGENTS.md 要求，
  该问题在提交前修正，不产生额外提交、不 amend、不压缩本地提交。

### 规划偏差（实现按真实 API，需与 A 在 Issue 中确认）

- `e2s_struct.md` 描述「将 `theme.token.motion` 设为 `false`」。核查 antd 6.7.1 的
  `theme/interface/seeds.d.ts` 后确认不存在该字段，实际提供 `motionUnit` / `motionBase`。
  实现改用 `motionUnit: 0`，并保留 CSS `@media (prefers-reduced-motion: reduce)` 兜底。
  这是文档与依赖版本的偏差，不是代码缺陷；规划文档按约定不入库，需在 Issue 中说明。

### 非阻断观察项（记录，不在本 PR 修正）

- 主 JS chunk 765.64 KB，Vite 提示超过 500 KB（antd 全量引入）。构建成功，
  后续可按需加载或代码分割优化；阶段 0 未设包体门槛。
- `package-lock.json` 的 `resolved` 指向 npmmirror 镜像；A 若使用其他镜像需确认可达。
- `qt-client.ts` 的真实桥接、`scripts/build-web.ps1` 的 PowerShell 执行、
  Qt WebEngine 中的动效与焦点复验，均待 A 的宿主集成阶段完成。
- 未引入录屏、实时窗口贴图、自动滚动、云服务、MCP、自更新等
  `snow_function.md` 第 10 节排除的能力。

## 3. 总体结论

**通过**：8 项评估无阻断性风格、架构、契约、健壮性、安全与隐私问题；
唯一的代码格式缺陷已在提交前修正，其余为规划偏差或后续阶段范围。
阶段 2 与阶段 3 结论均已留痕，允许进入阶段 4 提交、推送并发起正式 PR。

## 4. 后续动作

1. 提交并推送 `chore/web-workbench-bootstrap`，发起以 `main` 为目标的正式 PR，
   写明产物位置 `frontend/dist/`、桥接契约与验证结果，由 A 审查批准后 Squash and merge。
2. A 使用同一静态产物完成 `chore/desktop-integration`，在 Qt WebEngine 中复验
   Python 回调、同源资源、动效与焦点恢复。
3. 阶段 0 剩余验收（工作台与截图打包到同一离线目录、混合 DPI、首开时间）由 A 的
   宿主集成与发行包流程完成后共同确认。
