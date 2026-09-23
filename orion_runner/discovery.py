"""ORION Runner - experiment discovery via AST (no code is imported/executed).

Adapted from higgsfield (https://github.com/higgsfield-ai/higgsfield,
Copyright (c) higgsfield.ai authors, Apache-2.0 - see THIRD_PARTY.md). Only
scalar defaults, type names and option tuples are decoded, so experiments can
be listed and their parameter schema shown without importing the module.
"""
import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .params import Param

TYPE_DICT = {"str": str, "int": int, "float": float, "bool": bool}

_EXPERIMENT_ARGS = {"name": (str,), "seed": (int, type(None))}
_PARAM_ARGS = {
    "name": (str,),
    "default": (str, int, bool, float, type(None)),
    "description": (str, type(None)),
    "required": (bool, type(None)),
    "type": (type,),
    "options": (tuple, type(None)),
}


@dataclass
class _Dec:
    name: str
    allowed: Dict[str, tuple]
    arg_pairs: Dict[str, Any] = field(default_factory=dict)

    def add_arg_pair(self, left: str, right: Any):
        if left not in self.allowed:
            raise ValueError(f"argument {left!r} of {self.name} is not allowed")
        kinds = self.allowed[left]
        if not any(right is None and kind is type(None) or type(right) is kind for kind in kinds):
            raise ValueError(
                f"argument {left!r} of {self.name} has type {type(right).__name__}, "
                f"need one of {[k.__name__ for k in kinds]}"
            )
        if left in self.arg_pairs:
            raise ValueError(f"argument {left!r} redefined on {self.name}")
        self.arg_pairs[left] = right


def _kwarg_value(node: ast.AST):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in TYPE_DICT:
            raise ValueError(f"cannot resolve type name {node.id!r}")
        return TYPE_DICT[node.id]
    if isinstance(node, (ast.Tuple, ast.List)):
        return tuple(elt.value for elt in node.elts if isinstance(elt, ast.Constant))
    raise ValueError(f"unsupported decorator value node: {type(node).__name__}")


def _parse_decorators(node: ast.FunctionDef) -> Optional[Tuple[_Dec, Dict[str, _Dec]]]:
    if not node.decorator_list:
        return None
    first = node.decorator_list[0]
    if not isinstance(first, ast.Call):
        return None
    func = getattr(first, "func", None)
    if not isinstance(func, ast.Name) or func.id != "experiment":
        return None

    exp, params = None, {}
    for dec_node in node.decorator_list:
        if not isinstance(dec_node, ast.Call):
            continue
        dec_fn = getattr(dec_node, "func", None)
        if not isinstance(dec_fn, ast.Name) or dec_fn.id not in ("experiment", "param"):
            continue
        dec = _Dec(dec_fn.id, _EXPERIMENT_ARGS if dec_fn.id == "experiment" else _PARAM_ARGS)
        if len(dec_node.args) == 1:
            name = dec_node.args[0]
            if isinstance(name, ast.Constant) and isinstance(name.value, str):
                dec.add_arg_pair("name", name.value)
            else:
                return None
        for kw in dec_node.keywords:
            try:
                dec.add_arg_pair(kw.arg, _kwarg_value(kw.value))
            except (ValueError, AttributeError):
                return None
        if dec_fn.id == "experiment":
            exp = dec
        else:
            params.setdefault(dec.arg_pairs.get("name", ""), dec)
    if exp is None:
        return None
    return exp, params


@dataclass
class ExperimentSpec:
    name: str
    params: List[Param]
    path: str
    seed: Optional[int] = None


def discover_experiments(path) -> List[ExperimentSpec]:
    """Return ExperimentSpec entries for every @experiment function in a file
    or directory tree, parsed purely via ast - nothing is imported or run."""
    target = Path(path)
    files = []
    if target.is_file():
        files = [target]
    elif target.is_dir():
        files = sorted(target.rglob("*.py"))
    else:
        return []

    specs = []
    for file in files:
        try:
            tree = ast.parse(file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for node in ast.iter_child_nodes(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            parsed = _parse_decorators(node)
            if parsed is None:
                continue
            exp_dec, param_decs = parsed
            params = []
            seed = None
            for pdec in param_decs.values():
                param = Param.from_values(**pdec.arg_pairs)
                if param.name == "seed":
                    seed = param.default
                params.append(param)
            if not any(p.name == "seed" for p in params):
                params.insert(0, Param("seed", default=seed or 42, type=int))
            specs.append(ExperimentSpec(
                name=exp_dec.arg_pairs["name"],
                params=params,
                path=str(file),
                seed=seed,
            ))
    return specs