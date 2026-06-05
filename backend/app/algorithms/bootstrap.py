"""Import-only module — importing it triggers registration of all built-in
algorithms. Always import this once at app startup."""

from . import (  # noqa: F401
    builtins_filter,
    builtins_preprocess,
    builtins_reduce,
    builtins_regression,
    builtins_structure,
)
