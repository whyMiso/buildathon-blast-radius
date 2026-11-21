import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from br import patch as P, select as S, pack as K  # noqa: E402

DATA = "/data"


def main():
    tests = json.load(open(os.path.join(DATA, "tests.json")))["tests"]
    m = S.Maps()
    num = {t["id"]: t["number"] for t in tests}
    ms = {t["number"]: round(t["seconds"] * 1000) for t in tests}
    idx2num = [num.get(i) for i in m.ids]
    allnums = [t["number"] for t in tests]
    cdir = os.path.join(DATA, "commits")
    for f in sorted(os.listdir(cdir)):
        if not f.endswith(".patch"):
            continue
        cid = f[:-6]
        try:
            fcs = P.parse(open(os.path.join(cdir, f), encoding="utf-8").read())
            files = []
            for fc in fcs:
                old = S.read(fc.old) if fc.old else None
                if fc.old and old is None and not fc.new_file:
                    raise P.PatchError("missing")
                if fc.binary or fc.mode_only:
                    files.append((fc, old, old, set(), set()))
                    continue
                new, ch, ins = P.apply(fc, old)
                files.append((fc, old, new, ch, ins))
            cand = S.candidates(m, files)
            nums = sorted(n for n in (idx2num[i] for i in cand) if n is not None)
        except Exception as e:  # never guess downwards
            print("fallback", cid, repr(e), file=sys.stderr)
            nums = allnums
        cost, ws = K.pack([(n, ms[n]) for n in nums], 8)
        print(json.dumps({"commit": cid, "workers": ws}, separators=(",", ":")))


if __name__ == "__main__":
    main()
