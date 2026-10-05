"""One KhervePDF window per user: opening a PDF while KhervePDF runs
(double-click, "Open with", KherveRef, KherveTeX...) adds a tab to the
running window instead of starting a second app.

A new launch connects to the running one over a local socket, sends
{"cmd": "open", "paths": [...]} as one JSON line, waits for "ok" and
exits. (Same protocol as KherveRef's ipc.py.)
"""
from __future__ import annotations

import getpass
import json
import os
import re

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def server_name() -> str:
    if os.environ.get("KHERVEPDF_IPC_NAME"):    # tests
        return os.environ["KHERVEPDF_IPC_NAME"]
    user = re.sub(r"[^A-Za-z0-9_]", "_", getpass.getuser() or "user")
    return f"khervepdf-{user}"


def send_to_running(request: dict, timeout_ms: int = 800) -> bool:
    """True when a running KhervePDF took the request."""
    sock = QLocalSocket()
    sock.connectToServer(server_name())
    if not sock.waitForConnected(timeout_ms):
        return False
    sock.write((json.dumps(request) + "\n").encode())
    sock.flush()
    sock.waitForBytesWritten(timeout_ms)
    # Hang up only once the window has the request: closing straight
    # away can lose it (Windows named pipes).
    sock.waitForReadyRead(5000)
    sock.disconnectFromServer()
    return True


class Server(QObject):
    request = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._buffers: dict[int, bytearray] = {}
        self._server = QLocalServer(self)
        name = server_name()
        if not self._server.listen(name):
            # A crashed instance leaves the socket file behind on Unix.
            QLocalServer.removeServer(name)
            self._server.listen(name)
        self._server.newConnection.connect(self._accept)

    def close(self) -> None:
        self._server.close()

    def _accept(self):
        while self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            self._buffers[id(sock)] = bytearray()
            sock.readyRead.connect(self._read)
            sock.disconnected.connect(self._dropped)
            # On Windows the whole request can arrive before readyRead
            # is connected, and then it is never signalled.
            self._consume(sock)

    def _read(self):
        self._consume(self.sender())

    def _consume(self, sock) -> None:
        buf = self._buffers.setdefault(id(sock), bytearray())
        if sock.bytesAvailable():
            buf.extend(bytes(sock.readAll()))
        if b"\n" not in buf:
            return
        line = bytes(buf).partition(b"\n")[0]
        buf.clear()
        try:
            req = json.loads(line.decode())
        except ValueError:
            req = None
        if sock.state() == QLocalSocket.ConnectedState:
            sock.write(b"ok\n")
            sock.flush()
        if isinstance(req, dict):
            self.request.emit(req)

    def _dropped(self):
        sock = self.sender()
        self._consume(sock)
        self._buffers.pop(id(sock), None)
        sock.deleteLater()
