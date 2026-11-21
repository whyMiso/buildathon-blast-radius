"""Static selector: patch -> candidate test indices (conservative, falls back wide)."""

import ast
import json
import os

from . import patch as P

HERE = os.path.dirname(os.path.abspath(__file__))
MAPS = os.path.join(os.path.dirname(HERE), "maps")
ROOT = os.environ.get("SQLGLOT_ROOT", "/opt/sqlglot")


class Maps:
    def __init__(self):
        self.ids = open(os.path.join(MAPS, "tests.txt")).read().split("\n")
        self.ids = [i for i in self.ids if i]
        self.n = len(self.ids)
        self.recv = json.load(open(os.path.join(MAPS, "recv.json")))
        self.opens = json.load(open(os.path.join(MAPS, "opens.json")))
        self.names = json.load(open(os.path.join(MAPS, "names.json")))
        self._cov = {}
        self.by_file = {}
        for i, t in enumerate(self.ids):
            self.by_file.setdefault(t.split("::")[0], []).append(i)

    def cov(self, path):
        if path not in self._cov:
            f = os.path.join(MAPS, "cov", path.replace("/", "__") + ".json")
            self._cov[path] = json.load(open(f)) if os.path.exists(f) else None
        return self._cov[path]

    def tests_on_line(self, path, ln):
        c = self.cov(path)
        if not c:
            return set()
        k = c["l"].get(str(ln))
        return set(c["s"][k]) if k is not None else set()

    def tests_on_lines(self, path, lines):
        out = set()
        for ln in lines:
            out |= self.tests_on_line(path, ln)
        return out

    def tests_in_file(self, path):
        c = self.cov(path)
        out = set()
        if c:
            for s in c["s"]:
                out.update(s)
        return out


def read(path):
    try:
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None


def spans(tree):
    """Innermost statement spans -> list of (start, end, kind, name, enclosing_func_span)."""
    res = []

    def walk(node, func, cls):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                start = min([ch.lineno] + [d.lineno for d in ch.decorator_list])
                res.append((start, ch.end_lineno, "func", ch.name, cls))
                walk(ch, ch, cls)
            elif isinstance(ch, ast.ClassDef):
                start = min([ch.lineno] + [d.lineno for d in ch.decorator_list])
                res.append((start, ch.end_lineno, "class", ch.name, cls))
                walk(ch, func, ch)
            else:
                walk(ch, func, cls)

    walk(tree, None, None)
    return res


def all_stmt_tests(m, path):
    return m.tests_in_file(path)


def unit_diff(old_src, new_src):
    """Return ('noop',) | ('syntax',) | ('units', set of changed unit keys, changed_lines_old)."""
    try:
        a = ast.parse(old_src)
    except SyntaxError:
        return ("unknown",)
    try:
        b = ast.parse(new_src)
    except SyntaxError:
        return ("syntax",)
    if ast.dump(a) == ast.dump(b):
        return ("noop",)
    return ("diff", a, b)


FIXTURE_DIR = "tests/fixtures/"
WALKERS = ("tests/test_docs.py", "tests/test_typing.py", "tests/test_dialect_imports.py", "tests/test_dialect_entry_points.py")


def fixture_noop(path, old, new):
    sys_path = os.path.join(ROOT, "tests")
    import importlib.util
    spec = importlib.util.spec_from_file_location("br_helpers", os.path.join(sys_path, "helpers.py"))
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)

    def parsed(text):
        flt = h._filter_comments(text)
        a = []
        lines = []
        for line in flt.splitlines():
            lines.append(line)
            if not line.startswith("#"):
                a.append("\n".join(lines))
                lines.clear()
        pairs = []
        try:
            st = flt.split(";")
            for i in range(0, len(st), 2):
                if i + 1 < len(st):
                    sql, meta = h._extract_meta(st[i].strip())
                    pairs.append((meta, sql, st[i + 1].strip()))
        except Exception:
            pairs = [flt]
        return a, pairs

    try:
        return parsed(old) == parsed(new)
    except Exception:
        return False


def candidates(m, files):
    """files: list of (FileChange, old_text, new_text, changed_old_lines, ins_points). Returns set or None for 'all'."""
    cand = set()
    allt = set(range(m.n))
    for fc, old, new, changed, ins in files:
        path = fc.path
        newp = fc.new or fc.old
        if fc.binary:
            return allt
        is_py = path.endswith(".py")
        reads = set(m.opens.get(path, ())) | set(m.opens.get(newp, ()))
        if path.startswith("sqlglot/") and is_py:
            if fc.new_file:
                cand |= set(i for w in WALKERS for i in m.by_file.get(w, []))
                continue
            if fc.deleted:
                cand |= m.tests_in_file(path)
                cand |= set(i for w in WALKERS for i in m.by_file.get(w, []))
                continue
            if fc.old != fc.new:
                return allt
            d = unit_diff(old, new)
            if d[0] == "noop":
                cand |= reads
                continue
            if d[0] in ("syntax", "unknown"):
                cand |= m.tests_in_file(path)
                cand |= set(i for w in WALKERS for i in m.by_file.get(w, []))
                continue
            _, a, b = d
            sp = [s for s in spans(a) if s[2] == "func"]
            lines_changed = set(changed) | set(ins)
            wide = False
            for ln in lines_changed:
                best = None
                for s in sp:
                    if s[0] <= ln <= s[1] and (best is None or s[1] - s[0] < best[1] - best[0]):
                        best = s
                if best is None:
                    wide = True
                    continue
                # in a function; is the line part of the signature (before first body stmt)?
                fnode = next((n for n in ast.walk(a) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.lineno <= best[1] and n.end_lineno == best[1] and n.name == best[3]), None)
                body0 = fnode.body[0].lineno if fnode else best[0]
                if ln < body0 and ln not in ins:
                    wide = True
                elif ln <= body0 and ln in ins and ln == body0 and False:
                    wide = True
                else:
                    cand |= m.tests_on_lines(path, range(best[0], best[1] + 1))
            if wide:
                cand |= m.tests_in_file(path)
            cand |= reads
        elif path.startswith("tests/") and is_py:
            if fc.new_file:
                continue
            if fc.deleted or path == "tests/helpers.py" or path.endswith("__init__.py") or fc.old != fc.new:
                return allt
            d = unit_diff(old, new)
            if d[0] == "noop":
                cand |= reads
                continue
            cand |= set(m.by_file.get(path, []))
        elif path.startswith(FIXTURE_DIR):
            if old is not None and new is not None and fixture_noop(path, old, new):
                continue
            cand |= reads
            if not reads:
                cand |= set(i for t in ("tests/test_optimizer.py", "tests/test_transpile.py") for i in m.by_file.get(t, []))
        else:
            cand |= reads
            if path in ("setup.py", "pyproject.toml", "setup.cfg", "sqlglotc/setup.py", "Makefile"):
                cand |= set(m.by_file.get("tests/test_build.py", [])) | set(m.by_file.get("tests/test_sqlglotc.py", []))
    return cand
