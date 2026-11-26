import json

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

FREE_TRANSLATION_URL = "https://index-translate.bilibili.com/v1/chat/completions"
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"


class StreamingTranslator(QObject):
    updated = Signal(str)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self._network = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None
        self._buffer = b""
        self._text = ""
        self._done = False
        self._timer = QTimer(self, interval=60000, singleShot=True)
        self._timer.timeout.connect(self._timeout)

    def translate(self, text: str, language: str, model: str, key: str = "") -> None:
        self.cancel()
        free = model == "free"
        request = QNetworkRequest(QUrl(FREE_TRANSLATION_URL if free else DEEPSEEK_URL))
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        request.setRawHeader(b"Accept", b"text/event-stream")
        if free:
            request.setRawHeader(b"User-Agent", b"Index-Translate-Client/1.0")
        else:
            request.setRawHeader(b"Authorization", b"Bearer " + key.encode("utf-8"))
        prompt = (f"Translate the following text into {language}. Output only the translation, "
                  f"without any explanation. Preserve the original formatting.\n\n{text}")
        body = {
            "model": "Index-Translate-35B-A3B" if free else "deepseek-flash",
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "temperature": 0,
        }
        if free:
            body.update(max_tokens=4096, chat_template_kwargs={"enable_thinking": False})
        else:
            body["thinking"] = {"type": "disabled"}
        self._buffer, self._text, self._done = b"", "", False
        reply = self._network.post(request, json.dumps(body, ensure_ascii=False).encode("utf-8"))
        self._reply = reply
        reply.readyRead.connect(self._read)
        reply.finished.connect(self._complete)
        self._timer.start()

    def cancel(self) -> None:
        self._timer.stop()
        reply, self._reply = self._reply, None
        if reply is not None:
            reply.abort()
            reply.deleteLater()

    def _timeout(self) -> None:
        self.cancel()
        self.failed.emit("翻译超时，请检查网络后重试。")

    def _read(self) -> None:
        if self._reply is None:
            return
        self._buffer += bytes(self._reply.readAll())
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            line = line.strip()
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if data == b"[DONE]":
                self._done = True
                continue
            try:
                event = json.loads(data)
                choice = event["choices"][0]
                if choice.get("finish_reason") == "stop":
                    self._done = True
                delta = choice.get("delta", {}).get("content") or ""
            except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                continue
            if isinstance(delta, str) and delta:
                self._text += delta
                self.updated.emit(self._text)

    def _complete(self) -> None:
        reply = self._reply
        if reply is None:
            return
        self._read()
        self._reply = None
        self._timer.stop()
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        error = reply.error()
        reply.deleteLater()
        if status != 200 or error != QNetworkReply.NetworkError.NoError:
            self.failed.emit(f"翻译请求失败（HTTP {status or '网络错误'}），请检查服务和配置。")
        elif not self._done or not self._text.strip():
            self.failed.emit("翻译结果不完整，请重试。")
        else:
            self.finished.emit(self._text)
