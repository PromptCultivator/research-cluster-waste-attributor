"""Research Cluster Waste Attributor (rcwa)."""

from typing import Any

import click
import typer.core

__version__ = "0.1.0"
__all__ = ["__version__"]

# Compatibility bridges for click >= 8.2 parameter formatting in typer
_orig_click_param_make_metavar = click.Parameter.make_metavar
_orig_click_arg_make_metavar = click.core.Argument.make_metavar


def _compat_click_param_make_metavar(self: click.Parameter, ctx: Any = None) -> str:
    """Allow optional context argument when rendering parameter metavars."""
    if ctx is None:
        ctx = click.get_current_context(silent=True)
    if ctx is not None:
        try:
            return _orig_click_param_make_metavar(self, ctx)  # pyright: ignore[reportCallIssue]
        except TypeError:
            pass
    return _orig_click_param_make_metavar(self)


def _compat_typer_arg_make_metavar(self: typer.core.TyperArgument, ctx: Any = None) -> str:
    """Allow flexible argument count when rendering Typer argument metavars."""
    if ctx is None:
        ctx = click.get_current_context(silent=True)
    if ctx is not None:
        try:
            return _orig_click_arg_make_metavar(self, ctx)  # pyright: ignore[reportCallIssue]
        except TypeError:
            pass
    name = getattr(self, "name", None)
    return str(name).upper() if name else "ARG"


click.Parameter.make_metavar = _compat_click_param_make_metavar  # type: ignore[method-assign]
click.core.Argument.make_metavar = _compat_typer_arg_make_metavar  # type: ignore[method-assign]
typer.core.TyperArgument.make_metavar = _compat_typer_arg_make_metavar  # type: ignore[method-assign]
