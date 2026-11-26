from hashlib import sha256
from pathlib import Path
from time import monotonic, sleep

from PySide6.QtCore import QLockFile, QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from e2s.platform.windows.activation import allow_foreground_activation

_ACTIVATE = b"A"
_ACCEPTED = b"K"
_STARTUP_TIMEOUT = 2.0


class SingleInstanceError(RuntimeError):
    pass


class SingleInstance(QObject):
    activation_requested = Signal()

    def __init__(self, data_directory: Path) -> None:
        super().__init__()
        data_directory.mkdir(parents=True, exist_ok=True)
        endpoint_id = sha256(str(data_directory.resolve()).casefold().encode()).hexdigest()[:32]
        self._endpoint = f"easy-to-shot-{endpoint_id}"
        self._lock = QLockFile(str(data_directory / "app.lock"))
        # Live processes can retain the lock indefinitely. Qt still recovers dead owners.
        self._lock.setStaleLockTime(0)
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._receive_connections)

    def start(self) -> bool:
        """Return True for the primary, False after the existing instance accepts activation."""
        deadline = monotonic() + _STARTUP_TIMEOUT
        while monotonic() < deadline:
            if self._lock.tryLock(0):
                if self._server.listen(self._endpoint):
                    return True
                self.close()
                raise SingleInstanceError("无法启动单实例服务。")
            if self._lock.error() != QLockFile.LockError.LockFailedError:
                raise SingleInstanceError("无法读写应用锁，请检查应用数据目录。")
            if self._activate_existing(deadline):
                return False
            sleep(0.04)
        raise SingleInstanceError("Easy to Shot 已运行，但暂时无法激活主菜单。")

    def close(self) -> None:
        self._server.close()
        for socket in self._server.findChildren(QLocalSocket):
            socket.abort()
        self._lock.unlock()

    def _activate_existing(self, deadline: float) -> bool:
        socket = QLocalSocket()
        socket.connectToServer(self._endpoint)
        if not socket.waitForConnected(80):
            return False

        process_id, _, _ = self._lock.getLockInfo()
        if process_id > 0:
            allow_foreground_activation(process_id)
        if socket.write(_ACTIVATE) != len(_ACTIVATE):
            raise SingleInstanceError("无法向已运行的 Easy to Shot 发送激活请求。")
        socket.flush()
        remaining_ms = max(1, int((deadline - monotonic()) * 1000))
        if socket.bytesAvailable() or socket.waitForReadyRead(remaining_ms):
            if bytes(socket.read(len(_ACCEPTED))) == _ACCEPTED:
                return True
        raise SingleInstanceError("已运行的 Easy to Shot 未确认激活请求。")

    def _receive_connections(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            socket.setReadBufferSize(2)
            socket.disconnected.connect(socket.deleteLater)
            socket.readyRead.connect(lambda pending=socket: self._receive_message(pending))
            QTimer.singleShot(1000, socket, socket.abort)
            if socket.bytesAvailable():
                self._receive_message(socket)

    def _receive_message(self, socket: QLocalSocket) -> None:
        if bytes(socket.readAll()) == _ACTIVATE:
            self.activation_requested.emit()
            socket.write(_ACCEPTED)
        socket.disconnectFromServer()

