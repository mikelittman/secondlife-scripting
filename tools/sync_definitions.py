#!/usr/bin/env python3
"""Build compact symbol tables from secondlife/lsl-definitions.

Runtime tools read the JSON this writes. PyYAML is required only here:

    python3 -m venv .venv && .venv/bin/pip install pyyaml
    .venv/bin/python tools/sync_definitions.py
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "lsl_tools" / "data"
LSL_URL = "https://raw.githubusercontent.com/secondlife/lsl-definitions/main/lsl_definitions.yaml"
SLUA_URL = "https://raw.githubusercontent.com/secondlife/lsl-definitions/main/slua_definitions.yaml"
LSL_REV = "77cca2b0ee676c46dab7146a2cf63692cc6b91fe"
SLUA_LANG_REV = "af1379e6fc30d66ba991f15213f2d48d65175e55"
LUAU_GRAMMAR_REV = "a8914d6c1fc5131f8e1c13f769fa704c9f5eb02f"
TAILSLIDE_REV = "f950e066863f215c2d22c66fc9498b12d4387b7f"

SOURCES = {
    "lsl-definitions": {
        "repository": "https://github.com/secondlife/lsl-definitions",
        "revision": LSL_REV,
    },
    "tailslide": {
        "repository": "https://github.com/secondlife/tailslide",
        "revision": TAILSLIDE_REV,
    },
    "slua": {
        "repository": "https://github.com/secondlife/slua",
        "revision": SLUA_LANG_REV,
    },
    "tree-sitter-luau": {
        "repository": "https://github.com/tree-sitter-grammars/tree-sitter-luau",
        "revision": LUAU_GRAMMAR_REV,
    },
}


def _load_yaml(path: Path):
    try:
        import yaml
    except ImportError:
        sys.exit("PyYAML is required to sync definitions. Install it in a virtualenv.")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _fetch(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return
    print(f"fetch {url}")
    with urllib.request.urlopen(url, timeout=60) as response:
        dest.write_bytes(response.read())


def _deprecated(value) -> dict | None:
    if not value:
        return None
    if value is True:
        return {"use": "", "reason": ""}
    if isinstance(value, dict):
        return {"use": value.get("use") or "", "reason": value.get("reason") or ""}
    return {"use": "", "reason": str(value)}


def _tooltip(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(text.split())


def _arguments(raw) -> list[dict]:
    args = []
    for entry in raw or []:
        if not isinstance(entry, dict) or len(entry) != 1:
            continue
        name, info = next(iter(entry.items()))
        info = info or {}
        args.append(
            {
                "name": name,
                "type": info.get("type") or "",
                "tooltip": _tooltip(info.get("tooltip")),
            }
        )
    return args


def _slua_name(lsl_name: str) -> str:
    if lsl_name.startswith("ll") and len(lsl_name) > 2:
        return lsl_name[2:]
    return lsl_name


def build_lsl(data: dict) -> dict:
    functions = {}
    for name, info in (data.get("functions") or {}).items():
        functions[name] = {
            "return": info.get("return") or "void",
            "arguments": _arguments(info.get("arguments")),
            "tooltip": _tooltip(info.get("tooltip")),
            "deprecated": _deprecated(info.get("deprecated")),
            "slua_deprecated": _deprecated(info.get("slua-deprecated")),
            "slua_removed": bool(info.get("slua-removed")),
            "sleep": info.get("sleep") or 0,
            "energy": info.get("energy") or 0,
            "slua_name": _slua_name(name),
        }
    events = {}
    for name, info in (data.get("events") or {}).items():
        events[name] = {
            "arguments": _arguments(info.get("arguments")),
            "tooltip": _tooltip(info.get("tooltip")),
            "deprecated": _deprecated(info.get("deprecated")),
            "slua_removed": bool(info.get("slua-removed")),
        }
    constants = {}
    for name, info in (data.get("constants") or {}).items():
        constants[name] = {
            "type": info.get("type") or "",
            "value": info.get("value"),
            "tooltip": _tooltip(info.get("tooltip")),
            "deprecated": _deprecated(info.get("deprecated")),
            "slua_removed": bool(info.get("slua-removed")),
            "private": bool(info.get("private")),
        }
    return {
        "syntax_version": data.get("llsd-lsl-syntax-version"),
        "types": {name: _tooltip((info or {}).get("tooltip")) for name, info in (data.get("types") or {}).items()},
        "controls": sorted((data.get("controls") or {}).keys()),
        "functions": functions,
        "events": events,
        "constants": constants,
    }


def _params(raw) -> list[dict]:
    params = []
    for param in raw or []:
        if not isinstance(param, dict):
            continue
        name = param.get("name") or ""
        typ = param.get("type") or ""
        # A trailing `?` means nil is allowed. It does not mean the argument
        # may be omitted. Omission comes from default-value or optional: true.
        variadic = name == "..." or str(typ).startswith("...")
        optional = variadic or param.get("optional") is True or "default-value" in param
        params.append({"name": name, "type": typ, "optional": optional, "variadic": variadic})
    return params


def _module_function(info: dict) -> dict:
    return {
        "params": _params(info.get("parameters")),
        "overloads": [_params(item.get("parameters")) for item in info.get("overloads") or [] if isinstance(item, dict)],
        "return": info.get("return-type") or "",
        "tooltip": _tooltip(info.get("comment")),
        "deprecated": _deprecated(info.get("deprecated") or info.get("slua-deprecated")),
        "removed": bool(info.get("slua-removed")),
    }


def build_slua(slua: dict, lsl: dict) -> dict:
    modules: dict[str, dict] = {}
    for module in slua.get("modules") or []:
        functions = {}
        for fn in module.get("functions") or []:
            if isinstance(fn, dict) and fn.get("name"):
                functions[fn["name"]] = _module_function(fn)
        constants = {}
        for const in module.get("constants") or []:
            if isinstance(const, dict) and const.get("name"):
                constants[const["name"]] = {
                    "type": const.get("type") or "",
                    "tooltip": _tooltip(const.get("comment")),
                }
        modules[module["name"]] = {
            "tooltip": _tooltip(module.get("comment")),
            "functions": functions,
            "constants": constants,
        }

    ll_functions = {}
    for lsl_name, info in lsl["functions"].items():
        method = info["slua_name"]
        ll_functions[method] = {
            "lsl_name": lsl_name,
            "params": [{"name": arg["name"], "type": arg["type"]} for arg in info["arguments"]],
            "return": info["return"],
            "tooltip": info["tooltip"],
            "deprecated": info["slua_deprecated"] or info["deprecated"],
            "removed": info["slua_removed"],
            "sleep": info["sleep"],
            "energy": info["energy"],
        }
    modules.setdefault("ll", {"tooltip": "Second Life LSL library.", "functions": {}, "constants": {}})
    modules["ll"]["functions"] = ll_functions

    # lsl_definitions/slua.py generate_ll_modules: every llcompat function is
    # @deprecated with an empty replacement, including functions removed from ll.
    # llcompat matches LSL semantics. It is not a rename of ll.
    compat = {}
    for method, info in ll_functions.items():
        compat[method] = {
            **info,
            "deprecated": {"use": "", "reason": ""},
            "removed": False,
        }
    for lsl_name, info in lsl["functions"].items():
        if not info["slua_removed"]:
            continue
        method = info["slua_name"]
        compat[method] = {
            "lsl_name": lsl_name,
            "params": [{"name": arg["name"], "type": arg["type"], "optional": False, "variadic": False} for arg in info["arguments"]],
            "return": info["return"],
            "tooltip": info["tooltip"],
            "deprecated": {"use": "", "reason": ""},
            "removed": False,
            "sleep": info["sleep"],
            "energy": info["energy"],
        }
    existing = modules.get("llcompat") or {}
    modules["llcompat"] = {
        "tooltip": "Like ll, but exactly matches LSL semantics.",
        "functions": compat,
        "constants": existing.get("constants") or {},
    }

    globals_ = []
    for item in slua.get("global-variables") or []:
        if isinstance(item, dict) and item.get("name"):
            globals_.append({"name": item["name"], "tooltip": _tooltip(item.get("comment")), "type": item.get("type") or ""})
    builtins = []
    for item in slua.get("functions") or []:
        if isinstance(item, dict) and item.get("name"):
            builtins.append({"name": item["name"], **_module_function(item)})
    removed_constants = sorted(name for name, info in lsl["constants"].items() if info["slua_removed"] and not info["private"])
    return {
        "version": slua.get("version") or "",
        "controls": sorted((slua.get("controls") or {}).keys()),
        "modules": modules,
        "globals": globals_,
        "builtins": builtins,
        "events": lsl["events"],
        "removed_constants": removed_constants,
    }


def main() -> None:
    cache = Path("/tmp/lsl-src")
    lsl_path = cache / "lsl_definitions.yaml"
    slua_path = cache / "slua_definitions.yaml"
    _fetch(LSL_URL, lsl_path)
    _fetch(SLUA_URL, slua_path)
    lsl_raw = _load_yaml(lsl_path)
    slua_raw = _load_yaml(slua_path)
    lsl = build_lsl(lsl_raw)
    slua = build_slua(slua_raw, lsl)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {"sources": SOURCES}
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (OUT_DIR / "lsl.json").write_text(json.dumps(lsl, separators=(",", ":")) + "\n", encoding="utf-8")
    (OUT_DIR / "slua.json").write_text(json.dumps(slua, separators=(",", ":")) + "\n", encoding="utf-8")
    print(
        f"wrote {OUT_DIR} "
        f"lsl functions={len(lsl['functions'])} events={len(lsl['events'])} constants={len(lsl['constants'])} "
        f"slua modules={len(slua['modules'])} ll={len(slua['modules']['ll']['functions'])}"
    )


if __name__ == "__main__":
    main()
