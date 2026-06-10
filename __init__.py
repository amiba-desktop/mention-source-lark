"""Lark mention source — exposes Feishu search as the ``search`` capability.

HTTP-agnostic: the backplane's mention-sources gateway adapts ``search`` into
``GET /mention-sources/lark/search`` for the composer. This package never
imports a web framework.
"""

from .source import search  # noqa: F401  -- the capability the loader grabs
