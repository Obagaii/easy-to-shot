# E2S Web 工作台 · 前端基线

React + TypeScript + Vite + Ant Design（`antd`）构建的本地静态工作台。产物随桌面应用分发，
从 `e2s://app/` 加载并支持离线使用；开发期使用与真实 WebChannel 同结构的模拟接口。

## 目录

~~~text
frontend/
├─ package.json / package-lock.json   # 锁定依赖
├─ tsconfig.json                      # strict 类型检查
├─ vite.config.ts                     # base './'，产物输出 dist/
├─ index.html
├─ src/
│  ├─ main.tsx
│  ├─ app/       # App.tsx、theme.ts、useReducedMotion.ts
│  ├─ pages/     # HistoryPage.tsx、SettingsPage.tsx
│  ├─ bridge/    # types.ts、mock-client.ts、qt-client.ts、index.ts
│  └─ styles/    # workbench.css
└─ tests/        # bridge.test.mjs
~~~

## 构建与预览

在 `frontend/` 下执行：`npm ci`（按锁文件安装）、`npm run typecheck`（`tsc --noEmit`）、
`npm run build`（类型检查 + `vite build`）、`npm run dev`（开发预览）。
也可在仓库根目录执行 `pwsh scripts/build-web.ps1`，脚本依次运行上述三步并校验
`frontend/dist/index.html` 存在。

**静态产物位置**：`frontend/dist/`（`index.html` + `assets/`）。A 做宿主集成时可把该目录
复制到 `src/e2s/resources/web/`，或让资源路由直接指向该目录；产物本身不入库。

本地环境若配置了不可达的 npm 代理，可用
`npm_config_userconfig=/dev/null npm --registry=https://registry.npmmirror.com ci`
覆盖配置后直连安装。`package-lock.json` 的 `resolved` 指向 npmmirror，
A 若使用其他镜像需确认可达。

## 桥接契约

`src/bridge/types.ts` 定义双方共用的 `WorkbenchBridge`，方法名与载荷统一 camelCase：

| 方法 | 参数 → 结果 |
| --- | --- |
| `startCapture` | `CaptureRequest` → `TaskResult` |
| `getSettings` / `saveSettings` / `resetSettings` | 草稿 → `SettingsResult` |
| `listHistory` | `HistoryQuery` → `HistoryList` |
| `copyHistoryItem` / `saveHistoryItemAs` | 记录 ID → `TaskResult` |
| `deleteHistoryItem` / `clearHistory` | 记录 ID / 受限操作 → `TaskResult` |
| `onTaskFinished` | 订阅 `taskFinished` 信号，返回取消订阅函数 |

任务结果用 `operationId` 关联，状态值为 `pending | succeeded | failed | cancelled | busy`；
错误码单独传递，用户提示文案在界面层维护。设置结果同时携带实际热键状态与错误码。

- 模拟实现：`mock-client.ts`，含 3 条合成历史记录、设置校验与失败分支。
- 真实实现：`qt-client.ts`，通过 `window.qt.webChannelTransport` 与 `QWebChannel` 连接宿主
  发布的 `workbench` 对象及 `taskFinished` 信号；`qwebchannel.js` 由 A 的宿主提供。
- 切换逻辑：`createBridge()` 在 `VITE_BRIDGE_MODE=mock` 时强制模拟；否则检测到 Qt 传输
  使用真实桥接，开发预览自动回退模拟。

## 与 A 的联调清单（需在 Issue 中确认）

1. 开始截图、读写设置、历史查询、预览路由、任务结果的参数、返回值、失败状态与取消行为。
2. 会话 ID、结果修订号、操作 ID、像素尺寸与快照所有权；字段变更同步 Python、TS 类型与模拟数据。
3. 预览资源路由与 `e2s://app/` 同源加载；`base: './'` 在 Qt WebEngine 中的表现。
4. 减少动态效果：Ant Design 主题与 `prefers-reduced-motion` 在打包 WebEngine 中复验。

## 验证记录

阶段 2 测试与阶段 3 评估结论见 `TEST_REPORT.md` 与 `ASSESSMENT.md`。
阶段 0 的零依赖验证小样见 `spike/web-workbench` 分支的 `spikes/web-workbench/`。

## 已知限制

- 主 JS chunk 约 766 KB（antd 全量引入），Vite 提示超过 500 KB；后续可按需加载或代码分割。
- `e2s_struct.md` 描述的 `theme.token.motion = false` 在 antd 6.7.1 类型中不存在；
  实现改用 `motionUnit: 0` 与 CSS `@media (prefers-reduced-motion: reduce)` 关闭动效。
- 真实 WebChannel 未在 Qt WebEngine 中联调；`build-web.ps1` 需在 Windows PowerShell 中复跑。
