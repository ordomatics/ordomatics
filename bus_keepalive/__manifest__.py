{
    "name": "Bus TCP Keepalive",
    "version": "18.0.1.0.0",
    "category": "Technical",
    "summary": "Adds TCP keepalives to the bus LISTEN/NOTIFY connection for Neon/cloud PostgreSQL",
    "description": """
Bus TCP Keepalive
=================

Neon (and other serverless PostgreSQL providers) silently drop idle connections
after ~5 minutes of inactivity. The bus dispatcher's LISTEN connection sits idle
between NOTIFY events, so the OS never detects the dead socket — ``select()``
just keeps timing out forever, and bus notifications stop arriving.

This module patches ``ImDispatch.loop()`` to enable TCP keepalives on the
underlying socket so the kernel detects dead connections within ~30 seconds:

- ``keepalives = 1`` (enable)
- ``keepalives_idle = 30`` (seconds before first probe)
- ``keepalives_interval = 10`` (seconds between probes)
- ``keepalives_count = 3`` (failed probes before declaring dead)

When the dead connection is detected, psycopg2 raises ``InterfaceError`` or
``OperationalError``, the bus loop's ``run()`` method catches it, sleeps, and
reconnects — restoring LISTEN/NOTIFY delivery automatically.

Add to ``server_wide_modules`` in ``odoo.conf`` or via ``--load`` so the patch
applies at startup before the bus thread starts.
    """,
    "author": "Ordomatics",
    "license": "LGPL-3",
    "depends": ["base"],
    "installable": True,
    "auto_install": False,
    "post_load": "patch_bus_keepalive",
}
