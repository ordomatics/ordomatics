"""
Monkey-patch the bus ImDispatch.loop() to enable TCP keepalives on the
LISTEN connection. This ensures Neon/serverless PG idle disconnects are
detected by the kernel within ~30s, triggering a reconnect in run().
"""
import logging
import os
import selectors
import json

import odoo

_logger = logging.getLogger(__name__)

# Configurable via env vars (seconds)
KEEPALIVE_IDLE = int(os.environ.get("BUS_KEEPALIVE_IDLE", "30"))
KEEPALIVE_INTERVAL = int(os.environ.get("BUS_KEEPALIVE_INTERVAL", "10"))
KEEPALIVE_COUNT = int(os.environ.get("BUS_KEEPALIVE_COUNT", "3"))


def _set_tcp_keepalive(conn):
    """Enable TCP keepalives on a psycopg2 connection's underlying socket."""
    import socket
    import sys

    if not hasattr(socket, "TCP_KEEPIDLE"):
        # macOS uses TCP_KEEPALIVE instead; skip on non-Linux
        _logger.warning("bus_keepalive: TCP_KEEPIDLE not available on %s, skipping", sys.platform)
        return

    sock = conn.fileno()
    if sock < 0:
        return
    raw_sock = socket.fromfd(sock, socket.AF_INET, socket.SOCK_STREAM)
    try:
        raw_sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        raw_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, KEEPALIVE_IDLE)
        raw_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, KEEPALIVE_INTERVAL)
        raw_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, KEEPALIVE_COUNT)
    finally:
        # fromfd() duplicates the fd; close the duplicate without affecting the original
        raw_sock.close()
    _logger.info(
        "Bus LISTEN connection: TCP keepalive enabled "
        "(idle=%ds, interval=%ds, count=%d)",
        KEEPALIVE_IDLE, KEEPALIVE_INTERVAL, KEEPALIVE_COUNT,
    )


def patch_bus_keepalive():
    """Called via post_load hook at server startup."""
    from odoo.addons.bus.models.bus import ImDispatch, hashable, TIMEOUT, stop_event

    def loop_with_keepalive(self):
        """Dispatch postgres notifications with TCP keepalives enabled."""
        _logger.info("Bus.loop listen imbus on db postgres (with TCP keepalive)")
        with odoo.sql_db.db_connect('postgres').cursor() as cr, \
             selectors.DefaultSelector() as sel:
            cr.execute("listen imbus")
            cr.commit()
            conn = cr._cnx
            _set_tcp_keepalive(conn)
            sel.register(conn, selectors.EVENT_READ)
            while not stop_event.is_set():
                if sel.select(TIMEOUT):
                    conn.poll()
                    channels = []
                    while conn.notifies:
                        channels.extend(json.loads(conn.notifies.pop().payload))
                    websockets = set()
                    for channel in channels:
                        websockets.update(self._channels_to_ws.get(hashable(channel), []))
                    for websocket in websockets:
                        websocket.trigger_notification_dispatching()

    ImDispatch.loop = loop_with_keepalive
    _logger.info("bus_keepalive: patched ImDispatch.loop with TCP keepalives")
