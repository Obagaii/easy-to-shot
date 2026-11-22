# PR-02 测试报告 · 前端基线

对应 AGENTS.md 第 2 节「阶段 2 · 测试」与 `e2s_git.md` 第 5 节第 4 条的验证要求。
分支：`chore/web-workbench-bootstrap`；被测对象：`frontend/` 与 `scripts/build-web.ps1`。

## 1. 执行命令与结果

| 阶段 | 命令 | 结果 |
| --- | --- | --- |
| 提交 1 | `npm ci` | 91 个包按 `package-lock.json` 安装成功 |
| 提交 1 | `npm run typecheck` | 通过（`tsc --noEmit`，strict） |
| 提交 1 | `npm run build` | 通过，1497 模块，产出 `dist/index.html` 与 CSS/JS |
| 提交 1 | 格式门禁（12 个源码/配置文件） | 0 不合格 |
| 提交 2 | `npm run typecheck` | 通过 |
| 提交 2 | `npm run build` | 通过，产出 `dist/index.html` 与 CSS/JS |
| 提交 2 | `node --experimental-strip-types --test tests/bridge.test.mjs` | **9/9 通过** |
| 提交 2 | 格式门禁（源码、配置、测试、脚本） | 0 不合格 |

复现命令（在 `frontend/` 下）：`npm ci` → `npm run typecheck` → `npm run build`
→ `node --experimental-strip-types --test tests/bridge.test.mjs`。
本环境 npm 代理不可达，命令使用
`npm_config_userconfig=/dev/null npm --registry=https://registry.npmmirror.com` 覆盖后直连。

## 2. 覆盖项

| 编号 | 测试项 | 对应要求 |
| --- | --- | --- |
| 1 | WebChannel 契约字段 camelCase、5 种任务状态值 | 跨层命名约定 |
| 2 | 读取设置返回草稿、实际热键状态与空错误码 | 设置读写 |
| 3 | 保存设置回写草稿；非法条数返回错误码且不写入 | 设置校验与失败反馈 |
| 4 | 恢复默认清除上一次草稿 | 恢复默认 |
| 5 | 历史查询按 offset/limit 分页并返回总数 | 历史查询 |
| 6 | 删除不存在记录返回 `failed` + `not_found`，列表不变 | 失败状态 |
| 7 | 删除成功后列表更新；清空后为空 | 删除与清空 |
| 8 | 任务结果按 `operationId` 通知订阅者；取消订阅后不再收到 | 任务结果关联与旧结果隔离 |
| 9 | 静态产物包含本地应用入口 | 同源静态资源 |
| — | TypeScript 严格检查、`vite build`、格式门禁 | AGENTS.md 阶段 2 前端必跑项 |

格式门禁检查 `.ts/.tsx/.css/.html/.json/.mjs/.ps1/.d.ts` 的 UTF-8、末尾换行、
无行尾空白、行宽约 100 字符；`.md` 文档只检查末尾换行与行尾空白。

## 3. 未覆盖范围（如实记录）

- 未在 Qt WebEngine、离线发行包或真实 QWebChannel 中验证桥接调用与 Python 回调；
  需 A 完成 `chore/desktop-integration` 后联调。
- `scripts/build-web.ps1` 未在本环境 PowerShell 中执行，三个步骤已用等价 npm 命令验证；
  需在 Windows PowerShell 7+ 复跑。
- 界面动效、焦点恢复、快速切页与减少动态效果未在真实 WebEngine 中复验；
  `spike/web-workbench` 分支的零依赖小样已用 DOM 替身覆盖这些行为。
- 混合 DPI、热键、剪贴板、系统对话框与首开时间属于 Windows 真机验收，不在本 PR 范围。
- 主 JS chunk 765.64 KB，Vite 提示超过 500 KB；构建成功但包体待后续优化。

## 4. 结论

阶段 2 测试通过：`npm ci` / TypeScript 严格检查 / `vite build` 均通过，
桥接行为测试 9/9，格式门禁 0 不合格。可以进入阶段 3 代码评估。
