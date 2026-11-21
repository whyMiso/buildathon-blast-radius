"""Compile maprun pickles + the pinned tree into the shipped maps.

usage: python build_maps.py PKL_DIR SQLGLOT_ROOT IMPORTS_JSON OUT_DIR
"""

import ast
import glob
import json
import os
import pickle
import sys

pkl_dir, root, imports_json, out = sys.argv[1:5]
os.makedirs(os.path.join(out, "cov"), exist_ok=True)

recs = []
for f in glob.glob(os.path.join(pkl_dir, "*.pkl")):
    with open(f, "rb") as fh:
        recs.append(pickle.load(fh))
recs.sort(key=lambda r: r["number"])
ids = [r["id"] for r in recs]
assert all(r["verdict"] == "pass" for r in recs), [r["id"] for r in recs if r["verdict"] != "pass"]
with open(os.path.join(out, "tests.txt"), "w") as fh:
    fh.write("\n".join(ids) + "\n")

# per file line -> tests
cov = {}
for i, r in enumerate(recs):
    for path, lines in r.get("lines", {}).items():
        d = cov.setdefault(path, {})
        for ln in lines:
            d.setdefault(ln, []).append(i)


def enc_sets(mapping):
    sets, idx, res = [], {}, {}
    for k, v in mapping.items():
        key = tuple(sorted(set(v)))
        if key not in idx:
            idx[key] = len(sets)
            sets.append(list(key))
        res[k] = idx[key]
    return sets, res


def cov_name(path):
    return path.replace("/", "__") + ".json"


for path, d in cov.items():
    sets, lm = enc_sets(d)
    with open(os.path.join(out, "cov", cov_name(path)), "w") as fh:
        json.dump({"s": sets, "l": {str(k): v for k, v in lm.items()}}, fh, separators=(",", ":"))

# receivers
recv = {}
for i, r in enumerate(recs):
    for c in r.get("recv", []):
        recv.setdefault(c, []).append(i)
sets, cm = enc_sets(recv)
json.dump({"s": sets, "c": cm}, open(os.path.join(out, "recv.json"), "w"), separators=(",", ":"))

# opens
opens = {}
for i, r in enumerate(recs):
    for p in r.get("opens", []):
        opens.setdefault(p, []).append(i)
json.dump(opens, open(os.path.join(out, "opens.json"), "w"), separators=(",", ":"))

# runtime name references: names used inside function bodies -> tests covering those statements
def runtime_refs(path, src):
    tree = ast.parse(src)
    res = {}

    def visit_func(fn):
        for node in ast.walk(fn):
            nm = None
            if isinstance(node, ast.Name):
                nm = node.id
            elif isinstance(node, ast.Attribute):
                nm = node.attr
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.isidentifier():
                nm = node.value
            if nm:
                res.setdefault(nm, set()).add(node.lineno)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            if isinstance(node, ast.Lambda):
                visit_func(node.body)
            else:
                for b in node.body:
                    visit_func(b)
    return res


names = {}
for d, _, fs in os.walk(os.path.join(root, "sqlglot")):
    for f in fs:
        if not f.endswith(".py"):
            continue
        p = os.path.relpath(os.path.join(d, f), root)
        src = open(os.path.join(root, p), encoding="utf-8").read()
        lc = cov.get(p, {})
        for nm, lines in runtime_refs(p, src).items():
            s = names.setdefault(nm, set())
            for ln in lines:
                s.update(lc.get(ln, ()))
names = {k: v for k, v in names.items() if v}
sets, nm = enc_sets(names)
json.dump({"s": sets, "n": nm}, open(os.path.join(out, "names.json"), "w"), separators=(",", ":"))

# imports (per test file: sqlglot modules imported at import; parent import-time lines)
imp = json.load(open(imports_json))
json.dump(imp, open(os.path.join(out, "imports.json"), "w"), separators=(",", ":"))

# profile: cpu per test (fork, traced -> rough); refined later
json.dump({r["id"]: round(r.get("cpu", 0), 3) for r in recs}, open(os.path.join(out, "profile_traced.json"), "w"))
print("tests", len(ids), "files", len(cov), "names", len(names))
