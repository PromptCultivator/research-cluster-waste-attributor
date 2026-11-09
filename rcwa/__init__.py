"""Research Cluster Waste Attributor (rcwa)."""

from typing import Any

import click

__version__ = "0.1.0"
__all__ = ["__version__"]

# Compatibility bridge for click >= 8.2 parameter formatting in typer
_orig_make_metavar = click.Parameter.make_metavar


def _compat_make_metavar(self: click.Parameter, ctx: Any = None) -> str:
    """Allow optional context argument when rendering parameter metavars."""
    if ctx is None:
        ctx = click.get_current_context(silent=True)
    return _orig_make_metavar(self, ctx)


click.Parameter.make_metavar = _compat_make_metavar  # type: ignore[method-assign]
