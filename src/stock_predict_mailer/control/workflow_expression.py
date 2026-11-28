"""Bounded, JSON-valued expressions for workflow computation nodes."""
from __future__ import annotations

import ast
import json
import operator

from ..agent_service.contracts import ServiceError

ARITHMETIC = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
              ast.Div: operator.truediv, ast.Mod: operator.mod}
COMPARISONS = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le,
               ast.Gt: operator.gt, ast.GtE: operator.ge}
ALLOWED = (ast.Expression, ast.Constant, ast.Name, ast.Load, ast.List, ast.Dict, ast.Subscript, ast.IfExp,
           ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.USub, ast.Not, ast.And, ast.Or,
           *ARITHMETIC, *COMPARISONS)


def compile_expression(text, names, node, field):
    def invalid(message):
        return ServiceError("INVALID_WORKFLOW", f"{node} · {field}：{message}")

    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 1000:
        raise invalid("请输入 1 至 1000 字的表达式")
    try:
        tree = ast.parse(text.strip(), mode="eval")
    except (SyntaxError, ValueError, RecursionError):
        raise invalid("表达式语法无效") from None
    for count, part in enumerate(ast.walk(tree), 1):
        if count > 120 or not isinstance(part, ALLOWED):
            raise invalid("仅支持 JSON 字面量、索引、算术、比较和条件表达式")
        if isinstance(part, ast.Name) and part.id not in names:
            raise invalid(f"未声明变量 {part.id}")
        if isinstance(part, ast.Constant) and type(part.value) not in (str, int, float, bool, type(None)):
            raise invalid("仅支持 JSON 值")
        if isinstance(part, ast.Dict) and any(key is None for key in part.keys):
            raise invalid("对象不支持展开语法")
    return tree.body


def ensure_size(value):
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode()) > 16_384:
        raise ValueError("计算结果超过 16 KiB")
    return value


def evaluate(tree, variables, node):
    def visit(part):
        if isinstance(part, ast.Constant):
            return ensure_size(part.value)
        if isinstance(part, ast.Name):
            return variables[part.id]
        if isinstance(part, ast.List):
            return ensure_size([visit(item) for item in part.elts])
        if isinstance(part, ast.Dict):
            result = {}
            for key, item in zip(part.keys, part.values, strict=True):
                name = visit(key)
                if not isinstance(name, str):
                    raise ValueError("对象字段名必须为文本")
                result[name] = visit(item)
            return ensure_size(result)
        if isinstance(part, ast.Subscript):
            return visit(part.value)[visit(part.slice)]
        if isinstance(part, ast.IfExp):
            return visit(part.body if visit(part.test) else part.orelse)
        if isinstance(part, ast.BoolOp):
            return (all if isinstance(part.op, ast.And) else any)(visit(item) for item in part.values)
        if isinstance(part, ast.UnaryOp):
            value = visit(part.operand)
            if isinstance(part.op, ast.Not):
                return not value
            if type(value) in (int, float):
                return -value
            raise ValueError("负号需要数值")
        if isinstance(part, ast.BinOp):
            left, right = visit(part.left), visit(part.right)
            operation = type(part.op)
            if operation is ast.Add and type(left) is type(right) is str:
                return ensure_size(left + right)
            if type(left) in (int, float) and type(right) in (int, float):
                return ensure_size(ARITHMETIC[operation](left, right))
            raise ValueError("算术运算需要数值，加号也支持拼接文本")
        left = visit(part.left)
        for operation, right_part in zip(part.ops, part.comparators, strict=True):
            right = visit(right_part)
            if not COMPARISONS[type(operation)](left, right):
                return False
            left = right
        return True

    try:
        return ensure_size(visit(tree))
    except KeyError as error:
        message = f"字段不存在 · {str(error)[:120]}"
    except IndexError:
        message = "索引超出范围"
    except ZeroDivisionError:
        message = "除数不能为零"
    except (ValueError, TypeError, OverflowError, RecursionError):
        message = "类型不匹配，或表达式结果超出大小与数值范围"
    raise ServiceError("WORKFLOW_EXPRESSION", f"{node} · {message}")
