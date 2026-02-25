"""
Calculator Tool - Mathematical operations (AST-based safe evaluator only)
"""

from python.helpers.tools import Tool, Response
import ast
import operator
import math


class Calculator(Tool):
    """Perform calculations"""

    name = "calculator"
    description = "Perform mathematical calculations"
    parameters = {
        "expression": {
            "type": "string",
            "description": "Mathematical expression to evaluate",
            "required": True
        }
    }

    # Safe operators
    SAFE_OPERATORS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.Mod: operator.mod,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }

    # Safe functions and constants
    SAFE_FUNCTIONS = {
        'abs': abs,
        'round': round,
        'min': min,
        'max': max,
        'sum': sum,
        'pow': pow,
        'sqrt': math.sqrt,
        'sin': math.sin,
        'cos': math.cos,
        'tan': math.tan,
        'log': math.log,
        'log10': math.log10,
        'pi': math.pi,
        'e': math.e,
    }

    async def execute(self, **kwargs) -> Response:
        expression = kwargs.get("expression", "")

        if not expression:
            return Response(message="Error: No expression provided", break_loop=False)

        try:
            result = self._safe_eval(expression)

            if isinstance(result, float):
                if result.is_integer():
                    result = int(result)
                else:
                    result = round(result, 10)

            return Response(
                message=f"Result: {result}",
                break_loop=False,
                data={"result": result}
            )

        except Exception as e:
            return Response(
                message=f"Calculation error: {str(e)}",
                break_loop=False
            )

    def _safe_eval(self, expr):
        """Safely evaluate mathematical expression using AST parser only."""
        expr = expr.replace('^', '**')
        return self._eval_ast(expr)

    def _eval_ast(self, expr):
        """Evaluate using AST for safety."""
        node = ast.parse(expr, mode='eval')
        return self._eval_node(node.body)

    def _eval_node(self, node):
        # ast.Constant replaces deprecated ast.Num in Python 3.8+
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        elif isinstance(node, ast.Num):  # Fallback for older Python
            return node.n
        elif isinstance(node, ast.BinOp):
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            op = self.SAFE_OPERATORS.get(type(node.op))
            if op is None:
                raise ValueError(f"Unsupported operator: {ast.dump(node.op)}")
            return op(left, right)
        elif isinstance(node, ast.UnaryOp):
            operand = self._eval_node(node.operand)
            op = self.SAFE_OPERATORS.get(type(node.op))
            if op is None:
                raise ValueError(f"Unsupported unary operator: {ast.dump(node.op)}")
            return op(operand)
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError("Only named function calls are supported")
            func = self.SAFE_FUNCTIONS.get(node.func.id)
            if func is None or not callable(func):
                raise ValueError(f"Unknown function: {node.func.id}")
            args = [self._eval_node(arg) for arg in node.args]
            return func(*args)
        elif isinstance(node, ast.Name):
            val = self.SAFE_FUNCTIONS.get(node.id)
            if val is None:
                raise ValueError(f"Unknown variable: {node.id}")
            return val

        raise ValueError(f"Unsupported operation: {ast.dump(node)}")


__all__ = ["Calculator"]
