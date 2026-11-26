import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from e2s.capture import stream_translation
from e2s.capture.stream_translation import StreamingTranslator


@pytest.mark.parametrize("model", ["free", "deepseek"])
def test_translation_streams_utf8_and_uses_selected_service(app: QApplication, monkeypatch, model):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((body, self.headers.get("Authorization"), self.headers.get("User-Agent")))
            chunks = [
                {"choices": [{"delta": {"content": "你好"}}]},
                {"choices": [{"delta": {"content": "世界"}}]},
                {"choices": [{"delta": None, "finish_reason": "stop"}]},
            ]
            data = b"".join(b"data: " + json.dumps(item, ensure_ascii=False).encode() + b"\n\n"
                            for item in chunks)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data[:37])
            self.wfile.flush()
            self.wfile.write(data[37:])

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}/chat/completions"
    monkeypatch.setattr(stream_translation, "FREE_TRANSLATION_URL", endpoint)
    monkeypatch.setattr(stream_translation, "DEEPSEEK_URL", endpoint)
    translator = StreamingTranslator(app)
    updates, completed, errors = [], [], []
    translator.updated.connect(updates.append)
    translator.finished.connect(completed.append)
    translator.failed.connect(errors.append)
    try:
        translator.translate("hello", "Simplified Chinese", model, "test-key")
        for _ in range(300):
            if completed or errors:
                break
            QTest.qWait(10)
        assert not errors
        assert updates == ["你好", "你好世界"]
        assert completed == ["你好世界"]
        body, auth, agent = requests[0]
        assert body["stream"] is True
        assert "Simplified Chinese" in body["messages"][0]["content"]
        if model == "free":
            assert body["model"] == "Index-Translate-35B-A3B"
            assert auth is None
            assert agent == "Index-Translate-Client/1.0"
        else:
            assert body["model"] == "deepseek-flash"
            assert auth == "Bearer test-key"
    finally:
        translator.cancel()
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
