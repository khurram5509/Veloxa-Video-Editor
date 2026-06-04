"""V14.1.0: single-instance guard.

Uses a Qt local socket (named pipe on Windows) keyed to the current
user. The first launched instance:

* opens a ``QLocalServer`` listening on ``SOCKET_NAME``,
* accepts incoming connections from second-instance launchers,
* on any incoming bytes (``activate``), raises and focuses its main
  window.

Every subsequent launch:

* connects to the existing server,
* writes ``activate``,
* exits with success.

Survives system sleep / hibernation / user-session changes because
the named pipe is per-user (``%USERNAME%`` baked into the name) and
the listener is auto-recreated on Qt's normal socket-error recovery.
A stale socket from a previously-crashed instance is detected on
listen failure and cleaned up via ``removeServer``.

Public API:

* :func:`request_single_instance` — call from ``main()`` BEFORE
  constructing the main window. Returns ``True`` if this process
  should continue as the primary instance; ``False`` if a previous
  instance was contacted (caller should exit).
* :func:`install_activation_handler` — wires the server's
  ``newConnection`` signal to a callback (typically a method on the
  main window that raises + focuses it).
"""
from __future__ import annotations

import getpass
import logging
import sys
from typing import Callable, Optional

from PyQt6.QtCore import QTimer
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

log = logging.getLogger("veloxa.single_instance")


# Pipe name keyed to the user, so two different users on the same
# machine each get their own primary instance. ``\\.\pipe\<name>`` is
# the Windows convention; Qt prepends that automatically.
def _socket_name() -> str:
    try:
        user = getpass.getuser() or "default"
    except Exception:
        user = "default"
    # Sanitise — pipe names cannot contain backslashes.
    user = "".join(c for c in user if c.isalnum() or c in "._-")[:32] or "default"
    return f"VeloxaVideoEditor-{user}"


SOCKET_NAME = _socket_name()
CONNECT_TIMEOUT_MS = 600
WRITE_TIMEOUT_MS = 600
# V14.1.1: ACK handshake. The primary writes ACK_MAGIC back after
# handling the activate request. If the new instance doesn't receive
# the ACK within ACK_TIMEOUT_MS, the primary is dead or wedged and
# the new instance promotes itself. Prevents the "after the update,
# 'already running' error" bug where the new EXE saw the old EXE's
# still-open pipe during teardown and exited.
ACK_TIMEOUT_MS = 1500
ACTIVATE_MAGIC = b"activate\n"
ACK_MAGIC = b"OK\n"


# ------------------------------------------------------------------ public

class _Holder:
    """Owns the QLocalServer across the lifetime of the primary
    instance. Kept module-level so the Python garbage collector
    doesn't drop it before the app exits."""

    def __init__(self):
        self.server: Optional[QLocalServer] = None
        self.activate_cb: Optional[Callable[[], None]] = None


_state = _Holder()


def request_single_instance(timeout_ms: int = CONNECT_TIMEOUT_MS) -> bool:
    """Try to claim this user's primary-instance slot.

    Returns ``True`` if this process is the primary instance — caller
    proceeds with normal startup. Returns ``False`` if a previous
    instance was successfully contacted and asked to activate — caller
    should exit immediately.

    Always returns ``True`` if both connect and listen fail (degrades
    open rather than blocking startup on a wedged pipe).
    """
    # Step 1: try to contact an existing primary AND verify it
    # responds. The waitForReadyRead + ACK byte is what distinguishes
    # a live primary from a stale pipe held by an exiting old version
    # of the app (the failure mode the user hit after V14.0.x -> V14.1.0
    # update — installer launched the new EXE while the old one was
    # still tearing down).
    sock = QLocalSocket()
    sock.connectToServer(SOCKET_NAME)
    if sock.waitForConnected(timeout_ms):
        try:
            sock.write(ACTIVATE_MAGIC)
            sock.waitForBytesWritten(WRITE_TIMEOUT_MS)
            if sock.waitForReadyRead(ACK_TIMEOUT_MS):
                data = bytes(sock.readAll())
                if ACK_MAGIC.strip() in data:
                    sock.disconnectFromServer()
                    sock.close()
                    log.info("Second instance: primary acknowledged, exiting.")
                    return False
            # No ACK -> primary is dead or wedged. Fall through to
            # take over as primary.
            log.info("Pipe was open but no ACK received — "
                     "stale endpoint, taking over.")
        finally:
            try:
                sock.disconnectFromServer()
            except Exception:
                pass
            sock.close()
    else:
        sock.close()

    # Step 2: bind a server on the same name. ``removeServer`` first
    # in case a previous primary crashed and left a stale endpoint.
    QLocalServer.removeServer(SOCKET_NAME)
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    if not server.listen(SOCKET_NAME):
        log.warning(
            "Primary-instance listen failed (%s): %s. "
            "Degrading: starting WITHOUT single-instance enforcement.",
            SOCKET_NAME, server.errorString())
        # Fail-open: still continue as a normal instance.
        return True

    server.newConnection.connect(_on_new_connection)
    _state.server = server
    log.info("Primary instance: listening on %s", SOCKET_NAME)
    return True


def install_activation_handler(callback: Callable[[], None]):
    """Register the callback fired when a second instance pings us.

    The callback runs on the Qt main-event thread (queued from the
    network slot). Typical use: focus + raise the main window."""
    _state.activate_cb = callback


# ------------------------------------------------------------------ internals

def _on_new_connection():
    server = _state.server
    if server is None:
        return
    sock = server.nextPendingConnection()
    if sock is None:
        return

    # Read whatever the second instance wrote. The ``activate`` magic
    # is just a sanity check; any non-empty payload activates the
    # window. After running the activation callback we write ACK_MAGIC
    # back so the second instance knows we're alive (V14.1.1 fix:
    # without the ACK, a new instance launched right after an installer
    # upgrade could see the old EXE's still-open pipe, think it was a
    # valid primary, and exit with "already running" before the user
    # ever sees the new app).
    handled = [False]

    def _read_and_act():
        if handled[0]:
            return
        handled[0] = True
        try:
            data = bytes(sock.readAll())
            if data:
                cb = _state.activate_cb
                if cb is not None:
                    try:
                        cb()
                    except Exception as exc:
                        log.warning("activation callback raised: %s", exc)
            # ACK regardless of payload contents — the act of writing
            # back is what proves liveness to the second instance.
            try:
                sock.write(ACK_MAGIC)
                sock.waitForBytesWritten(500)
            except Exception:
                pass
        finally:
            try:
                sock.disconnectFromServer()
                sock.close()
            except Exception:
                pass

    if sock.bytesAvailable() > 0:
        _read_and_act()
    else:
        sock.readyRead.connect(_read_and_act)
        # Safety: never wait forever for the second instance to send.
        QTimer.singleShot(500, _read_and_act)


def already_running_message() -> str:
    """Standard text the caller can show to the user when their
    second-instance launch is short-circuited."""
    return ("Veloxa Video Editor is already running.\n\n"
            "The existing window has been brought to the front.")
