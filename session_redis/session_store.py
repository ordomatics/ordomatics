# -*- coding: utf-8 -*-
"""
Redis-backed Odoo session store.

Patches ``odoo.http.Root.session_store`` at startup so every pod in a
multi-pod k8s deployment reads/writes sessions from the same Redis instance
instead of pod-local files.

Uses only Python stdlib (socket) — no redis-py required.
"""

import json
import logging
import os
import socket as _socket

_logger = logging.getLogger(__name__)

_REDIS_HOST = os.environ.get("SESSION_REDIS_HOST", "redis")
_REDIS_PORT = int(os.environ.get("SESSION_REDIS_PORT", "6379"))
_SESSION_TTL = int(os.environ.get("SESSION_REDIS_TTL", str(7 * 24 * 3600)))
_KEY_PREFIX = "odoo_sess:"


# ---------------------------------------------------------------------------
# Minimal RESP protocol client
# ---------------------------------------------------------------------------

def _resp_encode(*args):
    parts = [a.encode() if isinstance(a, str) else a for a in args]
    buf = f"*{len(parts)}\r\n".encode()
    for p in parts:
        buf += f"${len(p)}\r\n".encode() + p + b"\r\n"
    return buf


def _resp_decode(data: bytes):
    if not data:
        return None
    t = chr(data[0])
    nl = data.index(b"\r\n")
    line = data[1:nl].decode()
    if t == "+":
        return line
    if t == "-":
        raise RuntimeError(f"Redis error: {line}")
    if t == ":":
        return int(line)
    if t == "$":
        size = int(line)
        if size == -1:
            return None
        start = nl + 2
        return data[start: start + size]
    return None


def _redis(*args):
    """Execute one Redis command via a fresh socket; returns decoded value or None on error."""
    try:
        conn = _socket.create_connection((_REDIS_HOST, _REDIS_PORT), timeout=3)
        try:
            conn.sendall(_resp_encode(*args))
            buf = b""
            while True:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
                t = chr(buf[0])
                if t in ("+", "-", ":") and b"\r\n" in buf:
                    break
                if t == "$":
                    nl = buf.index(b"\r\n")
                    size = int(buf[1:nl])
                    if size == -1 or len(buf) >= nl + 2 + size + 2:
                        break
                else:
                    break
            return _resp_decode(buf)
        finally:
            conn.close()
    except Exception as exc:
        _logger.warning("session_redis: Redis %s failed: %s", args[0], exc)
        return None


# ---------------------------------------------------------------------------
# RedisSessionStore
# ---------------------------------------------------------------------------

class RedisSessionStore:
    """
    Drop-in replacement for ``odoo.http.FilesystemSessionStore`` backed by Redis.

    Implements the interface Odoo expects:
        get(sid), save(session), delete(session), new(),
        rotate(session, env), generate_key(), is_valid_key(key), vacuum()
    """

    def __init__(self, session_class, renew_missing=True):
        self.session_class = session_class
        self.renew_missing = renew_missing
        # Delegate generate_key / is_valid_key to FilesystemSessionStore
        # so we stay consistent with Odoo's key format.
        from odoo.http import FilesystemSessionStore as _FS
        self._fs = _FS.__new__(_FS)

    # -- key helpers ---------------------------------------------------------

    def generate_key(self, salt=None):
        return self._fs.generate_key(salt)

    def is_valid_key(self, key):
        return self._fs.is_valid_key(key)

    # -- CRUD ----------------------------------------------------------------

    def new(self):
        return self.session_class({}, self.generate_key(), True)

    def get(self, sid):
        if not self.is_valid_key(sid):
            return self.new()
        raw = _redis("GET", _KEY_PREFIX + sid)
        if raw:
            try:
                return self.session_class(json.loads(raw), sid, False)
            except Exception as exc:
                _logger.warning("session_redis: decode error for %s: %s", sid, exc)
        # Session not found or corrupt — return a blank session with the same SID
        return self.session_class({}, sid, True)

    def save(self, session):
        _redis("SET", _KEY_PREFIX + session.sid,
               json.dumps(dict(session)), "EX", str(_SESSION_TTL))

    def delete(self, session):
        _redis("DEL", _KEY_PREFIX + session.sid)

    def rotate(self, session, env):
        """Called on login: assign new SID and recompute session token."""
        self.delete(session)
        session.sid = self.generate_key()
        if session.uid and env:
            from odoo.service import security
            session.session_token = security.compute_session_token(session, env)
        session.should_rotate = False
        self.save(session)

    def vacuum(self, max_lifetime=None):
        pass  # Redis TTL handles expiry — nothing to sweep


# ---------------------------------------------------------------------------
# post_load entry point
# ---------------------------------------------------------------------------

_store: RedisSessionStore | None = None


def patch_session_store():
    """
    Called via ``post_load`` in __manifest__.py.
    Replaces ``Application.session_store`` with a Redis-backed store.

    We must patch both the class descriptor AND clear any existing instance
    attribute, because Odoo's ``lazy_property`` caches the result on the
    instance on first access — if the original ``FilesystemSessionStore``
    was already cached, a class-level patch alone would be shadowed.
    """
    from odoo.http import Application, Session, root
    from odoo.tools.func import lazy_property

    @lazy_property
    def _get_store(self):
        store = RedisSessionStore(Session, renew_missing=True)
        _logger.info(
            "session_redis: session store → Redis (%s:%s, TTL %ds)",
            _REDIS_HOST, _REDIS_PORT, _SESSION_TTL,
        )
        return store

    Application.session_store = _get_store
    # Clear any already-cached instance attribute so the new descriptor fires
    if root is not None:
        root.__dict__.pop("session_store", None)
    _logger.info("session_redis: Application.session_store patched")
