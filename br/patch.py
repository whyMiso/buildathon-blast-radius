"""Strict unified-diff parser and applier (git style, also plain diff -u)."""

import re

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class PatchError(Exception):
    pass


class FileChange:
    __slots__ = ("old", "new", "hunks", "binary", "new_file", "deleted", "mode_only")

    def __init__(self):
        self.old = None  # path in the old tree or None (new file)
        self.new = None  # path in the new tree or None (deleted)
        self.hunks = []  # (old_start, old_len, new_start, new_len, [(tag, text)])
        self.binary = False
        self.new_file = False
        self.deleted = False
        self.mode_only = False

    @property
    def path(self):
        return self.old or self.new


def _strip(p):
    p = p.strip()
    if "\t" in p:
        p = p.split("\t", 1)[0]
    if p.startswith('"') and p.endswith('"'):
        p = p[1:-1].encode("latin-1", "backslashreplace").decode("unicode_escape").encode("latin-1").decode("utf-8")
    if p == "/dev/null":
        return None
    if p.startswith(("a/", "b/")):
        p = p[2:]
    return p


def parse(text):
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    files = []
    cur = None
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if line.startswith("diff --git "):
            cur = FileChange()
            files.append(cur)
            m = re.match(r"diff --git (\"?a/.*?\"?) (\"?b/.*\"?)$", line)
            if m:
                cur.old = _strip(m.group(1))
                cur.new = _strip(m.group(2))
            i += 1
            continue
        if line.startswith("--- ") and i + 1 < n and lines[i + 1].startswith("+++ "):
            if cur is None or cur.hunks:
                cur = FileChange()
                files.append(cur)
            cur.old = _strip(line[4:])
            cur.new = _strip(lines[i + 1][4:])
            if cur.old is None:
                cur.new_file = True
            if cur.new is None:
                cur.deleted = True
            i += 2
            continue
        if cur is None:
            i += 1
            continue
        if line.startswith("new file mode"):
            cur.new_file = True
            i += 1
            continue
        if line.startswith("deleted file mode"):
            cur.deleted = True
            i += 1
            continue
        if line.startswith("rename from "):
            cur.old = line[len("rename from "):]
            i += 1
            continue
        if line.startswith("rename to "):
            cur.new = line[len("rename to "):]
            i += 1
            continue
        if line.startswith(("Binary files", "GIT binary patch")):
            cur.binary = True
            i += 1
            continue
        m = HUNK.match(line)
        if m:
            os_, ol, ns, nl = int(m.group(1)), int(m.group(2) or 1 if m.group(2) is None else m.group(2)), int(m.group(3)), int(m.group(4) or 1 if m.group(4) is None else m.group(4))
            if m.group(2) is None:
                ol = 1
            if m.group(4) is None:
                nl = 1
            body = []
            co, cn = 0, 0
            i += 1
            while i < n and (co < ol or cn < nl):
                l = lines[i]
                if l.startswith("\\"):
                    if body:
                        body[-1] = (body[-1][0], body[-1][1], True)
                    i += 1
                    continue
                tag = l[:1]
                if tag == " " or l == "":
                    body.append((" ", l[1:], False))
                    co += 1
                    cn += 1
                elif tag == "-":
                    body.append(("-", l[1:], False))
                    co += 1
                elif tag == "+":
                    body.append(("+", l[1:], False))
                    cn += 1
                else:
                    raise PatchError("bad hunk line")
                i += 1
            while i < n and lines[i].startswith("\\"):
                if body:
                    body[-1] = (body[-1][0], body[-1][1], True)
                i += 1
            if co != ol or cn != nl:
                raise PatchError("short hunk")
            cur.hunks.append((os_, ol, ns, nl, body))
            continue
        i += 1
    for f in files:
        if f.new_file:
            f.old = None
        if f.deleted:
            f.new = None
        if not f.hunks and not f.binary and f.old == f.new and not f.new_file and not f.deleted:
            f.mode_only = True
    return files


def apply(fc, old_text):
    """Apply one FileChange to old text (str or None). Returns (new_text, changed_old_lines, ins_points).

    changed_old_lines: set of 1-based old line numbers removed/modified.
    ins_points: set of old line numbers before which lines were inserted (len+1 = at end).
    """
    if fc.binary:
        raise PatchError("binary")
    if fc.deleted:
        return None, set(range(1, (old_text or "").count("\n") + 2)), set()
    old_lines = [] if not old_text else old_text.split("\n")
    # track trailing newline: split gives final "" when text ends with \n
    old_nl = True
    if old_lines and old_lines[-1] == "":
        old_lines.pop()
    elif old_lines:
        old_nl = False
    out = []
    pos = 0  # index into old_lines
    changed = set()
    ins = set()
    new_nl = old_nl
    offset = 0
    for os_, ol, ns, nl, body in fc.hunks:
        start = os_ - 1 if ol > 0 else os_
        old_seg = [t for tag, t, _ in body if tag in " -"]
        # locate with offset search if needed
        def match_at(s):
            return s >= pos and old_lines[s:s + len(old_seg)] == old_seg

        s = start + offset
        if not match_at(s):
            found = None
            for d in range(1, 200):
                for cand in (s - d, s + d):
                    if 0 <= cand <= len(old_lines) and match_at(cand):
                        found = cand
                        break
                if found is not None:
                    break
            if found is None:
                raise PatchError("context mismatch")
            offset += found - s
            s = found
        out.extend(old_lines[pos:s])
        k = s
        for tag, t, nonl in body:
            if tag == " ":
                out.append(t)
                k += 1
                if nonl:
                    new_nl = False
            elif tag == "-":
                changed.add(k + 1)
                k += 1
                if nonl:
                    new_nl = True
            else:
                ins.add(k + 1)
                out.append(t)
                new_nl = not nonl if nonl else new_nl
        pos = k
    out.extend(old_lines[pos:])
    if not out:
        return "", changed, ins
    return "\n".join(out) + ("\n" if new_nl else ""), changed, ins
