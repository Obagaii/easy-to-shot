# Easy to Shot

Windows 桌面截图工具。当前可通过工作台、托盘或全局热键启动截图，确认后由应用控制器提交像素快照。

## 本地运行

使用 Windows 11 x64 和 Python 3.13。在 PowerShell 中执行：

~~~powershell
python -m pip install ".[test]"
python -m e2s
~~~

- 默认截图热键为 Ctrl+Shift+F8。可在工作台查看本次运行的实际热键，也可录入并应用其他组合。
- 拖动鼠标框选，拖动选区内部移动，拖动四角或四边中点缩放。方向键每次移动 1 像素，按住 Shift 每次移动 10 像素。Enter 确认选区，Esc 取消。
- 当前确认选区只会生成内存快照。复制到剪贴板和保存文件分别属于 B1 和 B2。
- 关闭工作台后程序仍驻留托盘。从托盘菜单选择“退出”结束进程。

## 验证

~~~powershell
python -m pytest
~~~

截图确认时，`AppController.snapshot_ready` 发出独立的 `OutputSnapshot`。系统剪贴板和文件对话框适配器位于 `e2s.platform.windows`。
