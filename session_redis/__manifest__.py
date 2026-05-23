{
    "name": "Session Store: Redis",
    "version": "18.0.1.0.0",
    "category": "Technical",
    "summary": "Replaces Odoo's file-based session store with Redis for multi-pod deployments",
    "description": """
Session Store: Redis
====================

In a multi-pod Kubernetes deployment, Odoo's default file-based session store
breaks bus (WebSocket) notifications:

- The browser logs in via the **main pod** → session file written to that pod's
  local EmptyDir filesystem.
- The browser's SharedWorker opens a WebSocket to the **longpolling pod** →
  that pod can't find the session file → creates an anonymous session (uid=None)
  → partner channel never subscribed → no bus notifications ever reach the
  browser → popups/real-time features silently broken.

This module patches ``Root.session_store`` to use Redis so all pods share the
same session state.

**Configuration (env vars)**:

- ``SESSION_REDIS_HOST`` — Redis hostname (default: ``smartacus-test-ordomatics-redis``)
- ``SESSION_REDIS_PORT`` — Redis port (default: ``6379``)
- ``SESSION_REDIS_TTL``  — Session TTL in seconds (default: 604800 = 7 days)

No ``redis-py`` dependency; uses a minimal built-in RESP socket client.

Add to ``server_wide_modules`` in ``odoo.conf`` so the patch applies at
startup on every pod before any HTTP/WebSocket request is served.
    """,
    "author": "Ordomatics",
    "license": "LGPL-3",
    "depends": ["base"],
    "installable": True,
    "auto_install": False,
    "post_load": "patch_session_store",
}
