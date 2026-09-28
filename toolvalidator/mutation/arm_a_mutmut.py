"""Arm A: operator-based mutants, using mutmut's operator classes on our own ``ast`` engine.

Not the ``mutmut`` binary: mutmut 3 makes no mutants for module-level code (86% of
RunBugRun programs are scripts without a ``def``) and expects pytest tests, while ours
are stdin/stdout cases (docs/DECISIONS.md). The rules are mutmut's: comparison swaps
(``<`` -> ``<=``), arithmetic swaps (``+`` -> ``-``, ``*`` -> ``/``), number + 1,
``True`` <-> ``False``, strings wrapped in ``XX``, ``and`` <-> ``or``, ``not``/unary minus
removed, ``break`` <-> ``continue``. Docstrings and f-string text are left alone.

Every place a rule applies is a candidate; candidates are tried in a seeded order until
``cap`` mutants are kept. A mutant that does not parse, or whose tree equals the original
or an earlier mutant, is dropped and counted. This module only rewrites source: it never
runs code.
"""

import ast
import random
from dataclasses import dataclass

from toolvalidator.mutation import Mutant, MutantSet

__all__ = ["DEFAULT_CAP", "mutate"]

DEFAULT_CAP = 20

_COMPARE_SWAP: dict[type[ast.cmpop], type[ast.cmpop]] = {
    ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt,
    ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.In: ast.NotIn, ast.NotIn: ast.In,
    ast.Is: ast.IsNot, ast.IsNot: ast.Is,
}  # fmt: skip
_ARITH_SWAP: dict[type[ast.operator], type[ast.operator]] = {
    ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Div, ast.Div: ast.Mult,
    ast.FloorDiv: ast.Div, ast.Mod: ast.Div, ast.Pow: ast.Mult, ast.LShift: ast.RShift,
    ast.RShift: ast.LShift, ast.BitAnd: ast.BitOr, ast.BitOr: ast.BitAnd, ast.BitXor: ast.BitAnd,
}  # fmt: skip
_SYMBOL: dict[type[ast.AST], str] = {
    ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=", ast.Eq: "==", ast.NotEq: "!=",
    ast.In: "in", ast.NotIn: "not in", ast.Is: "is", ast.IsNot: "is not",
    ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.FloorDiv: "//", ast.Mod: "%",
    ast.Pow: "**", ast.LShift: "<<", ast.RShift: ">>", ast.BitAnd: "&", ast.BitOr: "|",
    ast.BitXor: "^", ast.And: "and", ast.Or: "or", ast.Not: "not", ast.USub: "-",
}  # fmt: skip


@dataclass(frozen=True)
class _Site:
    index: int  # position of the node in ``ast.walk`` order (stable for the same source)
    operator: str
    slot: int = 0  # which comparison in a chain such as ``a < b < c``


def mutate(code: str, *, cap: int = DEFAULT_CAP, seed: int = 0) -> MutantSet:
    """Up to ``cap`` operator mutants of ``code``, in source order. Raises on unparsable code."""
    original = ast.parse(code)
    sites = _sites(original)
    order = list(sites)
    random.Random(seed).shuffle(order)
    seen = {ast.dump(original)}
    kept: list[tuple[_Site, Mutant]] = []
    dropped = 0
    for site in order:
        if len(kept) == cap:
            break
        built = _build(code, site)
        if built is None or built[1] in seen:
            dropped += 1
            continue
        seen.add(built[1])
        kept.append((site, built[0]))
    kept.sort(key=lambda pair: (pair[0].index, pair[0].slot))
    return MutantSet(mutants=[m for _, m in kept], candidates=len(sites), dropped=dropped)


def _sites(tree: ast.Module) -> list[_Site]:
    nodes = list(ast.walk(tree))
    protected = _protected_strings(nodes)
    return [
        _Site(index, operator, slot)
        for index, node in enumerate(nodes)
        for operator, slot in _rules(node, protected)
    ]


def _protected_strings(nodes: list[ast.AST]) -> set[int]:
    """Docstrings, bare string statements and f-string text: changing them tests nothing."""
    protected: set[int] = set()
    for node in nodes:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            protected.add(id(node.value))
        if isinstance(node, ast.JoinedStr):
            protected.update(id(sub) for sub in ast.walk(node) if isinstance(sub, ast.Constant))
    return protected


def _rules(node: ast.AST, protected: set[int]) -> list[tuple[str, int]]:
    match node:
        case ast.Constant(value=bool()):
            return [("boolean", 0)]
        case ast.Constant(value=int() | float()):
            return [("number", 0)]
        case ast.Constant(value=str()) if id(node) not in protected:
            return [("string", 0)]
        case ast.Compare(ops=ops):
            return [("comparison", i) for i, op in enumerate(ops) if type(op) in _COMPARE_SWAP]
        case ast.BinOp(op=op) | ast.AugAssign(op=op) if type(op) in _ARITH_SWAP:
            return [("arithmetic", 0)]
        case ast.BoolOp():
            return [("boolean_operator", 0)]
        case ast.UnaryOp(op=ast.Not() | ast.USub()):
            return [("unary_removal", 0)]
        case ast.Break() | ast.Continue():
            return [("loop_control", 0)]
    return []


def _build(code: str, site: _Site) -> tuple[Mutant, str] | None:
    """The mutant for one site and its tree dump, or None when it does not unparse/parse."""
    tree = ast.parse(code)
    node = list(ast.walk(tree))[site.index]
    line = getattr(node, "lineno", None)
    change = _apply(tree, node, site.slot)
    try:
        mutated = ast.unparse(tree)
        dump = ast.dump(ast.parse(mutated))
    except (SyntaxError, ValueError, RecursionError):
        return None
    mutant = Mutant(
        operator=site.operator, line=line, description=f"line {line}: {change}", code=mutated
    )
    return mutant, dump


def _apply(tree: ast.Module, node: ast.AST, slot: int) -> str:
    """Change ``node`` inside ``tree`` in place; return a short 'before -> after'."""
    match node:
        case ast.Constant(value=bool() as old):
            node.value = not old
            return f"{old} -> {node.value}"
        case ast.Constant(value=int() | float() as old):
            node.value = old + 1
            return f"{old!r} -> {node.value!r}"
        case ast.Constant(value=str() as old):
            node.value = f"XX{old}XX"
            return f"{old!r} -> {node.value!r}"
        case ast.Compare():
            old_cmp = node.ops[slot]
            node.ops[slot] = _COMPARE_SWAP[type(old_cmp)]()
            return f"{_SYMBOL[type(old_cmp)]} -> {_SYMBOL[type(node.ops[slot])]}"
        case ast.BinOp() | ast.AugAssign():
            old_op = node.op
            node.op = _ARITH_SWAP[type(old_op)]()
            return f"{_SYMBOL[type(old_op)]} -> {_SYMBOL[type(node.op)]}"
        case ast.BoolOp():
            old_bool = node.op
            node.op = ast.Or() if isinstance(old_bool, ast.And) else ast.And()
            return f"{_SYMBOL[type(old_bool)]} -> {_SYMBOL[type(node.op)]}"
        case ast.UnaryOp():
            _Replace(node, node.operand).visit(tree)
            return f"{_SYMBOL[type(node.op)]} removed"
        case ast.Break() | ast.Continue():
            new: ast.stmt = ast.Continue() if isinstance(node, ast.Break) else ast.Break()
            _Replace(node, ast.copy_location(new, node)).visit(tree)
            return "break -> continue" if isinstance(node, ast.Break) else "continue -> break"
    raise AssertionError(f"no rule for {type(node).__name__}")  # _rules and _apply disagree


class _Replace(ast.NodeTransformer):
    """Swap one node object (by identity) for another."""

    def __init__(self, target: ast.AST, replacement: ast.AST) -> None:
        self.target = target
        self.replacement = replacement

    def visit(self, node: ast.AST) -> ast.AST:
        if node is self.target:
            return self.replacement
        return self.generic_visit(node)
