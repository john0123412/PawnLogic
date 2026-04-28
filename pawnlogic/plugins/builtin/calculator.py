"""Built-in calculator plugin."""

from __future__ import annotations

import ast
import math
import operator as op
from typing import Any

from pawnlogic.plugins.base import Plugin, PluginResult

# Supported operators for safe evaluation
_OPERATORS: dict[type, Any] = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.Pow: op.pow,
    ast.USub: op.neg,
    ast.UAdd: op.pos,
    ast.Mod: op.mod,
    ast.FloorDiv: op.floordiv,
}

_SAFE_NAMES: dict[str, float] = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
    "inf": math.inf,
}


def _safe_eval(node: ast.expr) -> float:
    """Recursively evaluate a parsed AST node using only safe operations."""
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float)):
            raise ValueError(f"Unsupported constant type: {type(node.value)}")
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id not in _SAFE_NAMES:
            raise NameError(f"Name '{node.id}' is not allowed.")
        return _SAFE_NAMES[node.id]
    if isinstance(node, ast.BinOp):
        op_fn = _OPERATORS.get(type(node.op))
        if op_fn is None:
            raise TypeError(f"Operator {type(node.op).__name__} is not supported.")
        return op_fn(_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp):
        op_fn = _OPERATORS.get(type(node.op))
        if op_fn is None:
            raise TypeError(f"Operator {type(node.op).__name__} is not supported.")
        return op_fn(_safe_eval(node.operand))
    raise TypeError(f"Unsupported AST node type: {type(node).__name__}")


class CalculatorPlugin(Plugin):
    """Evaluate arithmetic expressions safely.

    Only numeric literals, the constants ``pi``, ``e``, ``tau``, ``inf``
    and the operators ``+``, ``-``, ``*``, ``/``, ``//``, ``%``, ``**``
    are permitted.  No function calls or imports are allowed.
    """

    @property
    def name(self) -> str:
        return "calculator"

    @property
    def description(self) -> str:
        return (
            "Evaluates a mathematical expression and returns the numeric result. "
            "Supports +, -, *, /, //, %, ** and the constants pi, e, tau, inf."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "expression": {
                "type": "string",
                "description": "The arithmetic expression to evaluate, e.g. '2 ** 10 + 3'.",
            }
        }

    def execute(self, **kwargs: Any) -> PluginResult:
        expression: str = kwargs.get("expression", "")
        if not expression:
            return PluginResult(
                success=False, output="", error="'expression' parameter is required."
            )
        try:
            tree = ast.parse(expression, mode="eval")
            result = _safe_eval(tree.body)
            return PluginResult(
                success=True,
                output=str(result),
                data={"expression": expression, "result": result},
            )
        except ZeroDivisionError:
            return PluginResult(success=False, output="", error="Division by zero.")
        except Exception as exc:
            return PluginResult(success=False, output="", error=str(exc))
