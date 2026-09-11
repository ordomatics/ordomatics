{
    "name": "Ordomatics",
    "version": "18.0.1.0.0",
    "category": "Technical",
    "summary": "Client-side access to the Ordomatics platform services",
    "description": """
Ordomatics
==========

What a client deployment installs to reach platform services -- WhatsApp,
telephony, billing -- over the APIs those modules expose, rather than by
installing them. Those modules are private and platform-only: they live in
the platform's own image and never ship in a client one.

A stub for now: it declares the name and nothing else, so a client manifest
can depend on it while the API clients are written. It deliberately depends
on ``base`` alone, because it has to install in a client image, which carries
none of the platform addons.

Not to be confused with ``platform`` (ordomatics/odoo, addons/platform/
platform), which is the platform's own meta-module and was called
``ordomatics`` until this name was freed for this one.
    """,
    "author": "Ordomatics",
    "license": "LGPL-3",
    "depends": ["base"],
    "installable": True,
    "auto_install": False,
}
