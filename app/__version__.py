"""Single source of truth for the Catom app version.

Bump this on every release. CI reads it to stamp the NSIS installer and the
`updates.aisimple.co/catom/latest.json` feed. The git tag MUST match (e.g.
`v1.0.3` here -> tag `v1.0.3`).
"""

__version__ = "1.3.10"
