"""Deterministic executor for FinQA-style reasoning programs.

The LLM proposes a program; this module computes it. Keeping arithmetic out of
the model is what lets us separate CALCULATION_FAILURE from evidence failures.

Grammar (FinQA DSL):
    program  := step ("," step)*
    step     := OP "(" arg "," arg ")"
    arg      := number | number% | const_N | const_mN | #k | <table row name> | none
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

BINARY_OPS = {"add", "subtract", "multiply", "divide", "exp", "greater"}
TABLE_OPS = {"table_max", "table_min", "table_sum", "table_average"}

_STEP_RE = re.compile(r"(\w+)\(([^()]*)\)")
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


class ProgramError(ValueError):
    """Raised for malformed programs or arguments that cannot be resolved."""


@dataclass(frozen=True)
class Step:
    op: str
    args: tuple[str, str]


@dataclass
class ExecutionResult:
    value: float | str  # str only for "yes"/"no" from greater()
    steps: list[tuple[Step, float | str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def parse_program(program: str) -> list[Step]:
    text = program.strip().removesuffix("EOF").strip().rstrip(",")
    matches = list(_STEP_RE.finditer(text))
    if not matches:
        raise ProgramError(f"no steps found in program: {program!r}")
    # Everything between matches must be separators only; otherwise the
    # program has junk we would silently ignore.
    leftover = _STEP_RE.sub("", text).replace(",", "").strip()
    if leftover:
        raise ProgramError(f"unparseable text in program: {leftover!r}")
    steps = []
    for m in matches:
        op = m.group(1)
        if op not in BINARY_OPS | TABLE_OPS:
            raise ProgramError(f"unknown op: {op}")
        parts = [p.strip() for p in m.group(2).split(",")]
        if len(parts) != 2:
            raise ProgramError(f"{op} expects 2 args, got {len(parts)}: {m.group(0)}")
        steps.append(Step(op, (parts[0], parts[1])))
    return steps


def parse_number(token: str) -> float:
    """Parse a numeric literal as FinQA writes it. '5%' -> 0.05."""
    t = token.replace(",", "").replace("$", "").strip()
    pct = t.endswith("%")
    t = t.rstrip("%").strip()
    try:
        v = float(t)
    except ValueError as e:
        raise ProgramError(f"not a number: {token!r}") from e
    return v / 100 if pct else v


def parse_cell(cell: str) -> float | None:
    """Parse a FinQA table cell like '$ -23158 ( 23158 )' -> -23158.

    Returns None for non-numeric cells instead of guessing.
    """
    t = cell.replace(",", "").replace("$", "").strip()
    m = _NUM_RE.search(t)
    if not m:
        return None
    v = float(m.group(0))
    if t.endswith("%") or m.group(0) + "%" in t:
        v /= 100
    return v


def _const(token: str) -> float:
    body = token.removeprefix("const_")
    return -float(body[1:]) if body.startswith("m") else float(body)


def _resolve(arg: str, results: list[float | str]) -> float:
    if arg.startswith("#"):
        idx = int(arg[1:])
        if idx >= len(results):
            raise ProgramError(f"forward reference {arg}")
        val = results[idx]
        if isinstance(val, str):
            raise ProgramError(f"{arg} is a boolean result, not a number")
        return val
    if arg.startswith("const_"):
        return _const(arg)
    return parse_number(arg)


def _table_row(name: str, table: list[list[str]] | None, warnings: list[str]) -> list[float]:
    if not table:
        raise ProgramError("table op used but no table supplied")
    key = name.strip().lower()
    hits = [row for row in table if row and row[0].strip().lower() == key]
    if not hits:
        raise ProgramError(f"row {name!r} not found in table")
    if len(hits) > 1:
        # FinQA's reference executor takes the last match; we follow it for
        # benchmark fidelity but surface the ambiguity.
        warnings.append(f"ambiguous_row:{name}:{len(hits)}_matches")
    vals = [v for v in (parse_cell(c) for c in hits[-1][1:]) if v is not None]
    if not vals:
        raise ProgramError(f"row {name!r} has no numeric cells")
    return vals


def execute(program: str, table: list[list[str]] | None = None) -> ExecutionResult:
    steps = parse_program(program)
    results: list[float | str] = []
    trace: list[tuple[Step, float | str]] = []
    warnings: list[str] = []
    for step in steps:
        a, b = step.args
        if step.op in TABLE_OPS:
            vals = _table_row(a, table, warnings)
            out: float | str = {
                "table_max": max,
                "table_min": min,
                "table_sum": sum,
                "table_average": lambda v: sum(v) / len(v),
            }[step.op](vals)
        else:
            x, y = _resolve(a, results), _resolve(b, results)
            if step.op == "add":
                out = x + y
            elif step.op == "subtract":
                out = x - y
            elif step.op == "multiply":
                out = x * y
            elif step.op == "divide":
                if y == 0:
                    raise ProgramError("division by zero")
                out = x / y
            elif step.op == "exp":
                out = x**y
            else:  # greater
                out = "yes" if x > y else "no"
        if isinstance(out, float) and not math.isfinite(out):
            raise ProgramError(f"non-finite result at {step}")
        results.append(out)
        trace.append((step, out))
    return ExecutionResult(value=results[-1], steps=trace, warnings=warnings)


def numbers_match(
    pred: float | str,
    gold: float | str,
    rel: float = 0.01,
    abs_: float = 0.005,
    allow_percent_scale: bool = False,
) -> bool:
    """Tolerant numeric comparison.

    allow_percent_scale treats 0.12 and 12 as equal. Use it only when comparing
    against FinQA's free-text answers, which mix the two; never when scoring the
    system, where a scale error is a real DATA_FAILURE.
    """
    if isinstance(pred, str) or isinstance(gold, str):
        return str(pred).strip().lower() == str(gold).strip().lower()
    cands = (gold, gold * 100, gold / 100) if allow_percent_scale else (gold,)
    for g in cands:
        if abs(pred - g) <= max(rel * abs(g), abs_):
            return True
    return False
