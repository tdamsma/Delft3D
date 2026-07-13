#!/usr/bin/env python3
"""Adjusted hotspot ranking: samples landing in gfortran's IEEE FPU-state
runtime (_gfortrani_{get,set}_fpu_{state,except_flags}) are re-attributed to
the nearest non-runtime caller frame, so the ranking reflects which dflowfm
procedures *incur* that overhead. Also prints the raw runtime share.

Usage: python3 samply_attr.py profile.json.gz [topN]
"""
import bisect
import gzip
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

FPU_RUNTIME = {
    "_gfortrani_set_fpu_except_flags",
    "_gfortrani_get_fpu_except_flags",
    "_gfortrani_set_fpu_state",
    "_gfortrani_get_fpu_state",
    "_gfortran_ieee_procedure_entry",
    "_gfortran_ieee_procedure_exit",
}


def demangle(name):
    m = re.match(r"^_*(\w+?)_MOD_(\w+)$", name)
    return f"{m.group(1).lstrip('_')}::{m.group(2)}" if m else name


def load_syms(path):
    d = json.loads(path.read_text())
    st = d["string_table"]
    out = {}
    for lib in d["data"]:
        entries = sorted(lib.get("symbol_table") or [], key=lambda e: e["rva"])
        out[lib["debug_name"]] = ([e["rva"] for e in entries],
                                  [st[e["symbol"]] for e in entries])
    return out


def main():
    path = Path(sys.argv[1])
    top_n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    symtabs = load_syms(Path(str(path).replace(".json.gz", ".json.syms.json")))
    with gzip.open(path, "rt") as f:
        prof = json.load(f)
    libs = prof.get("libs", [])

    adj_self = defaultdict(float)   # (name, lib) -> weight incl. re-attributed fpu time
    fpu_of = defaultdict(float)     # (name, lib) -> re-attributed fpu weight only
    pure_self = defaultdict(float)
    total = 0.0
    fpu_total = 0.0

    for th in prof["threads"]:
        samples = th["samples"]
        stack_col = samples["stack"]
        weights = samples.get("weight")
        interval = prof["meta"].get("interval", 1.0)
        sp = th["stackTable"]["prefix"]
        sf = th["stackTable"]["frame"]
        fa = th["frameTable"]["address"]
        ff = th["frameTable"]["func"]
        fr = th["funcTable"].get("resource", [])
        rl = th.get("resourceTable", {}).get("lib", [])

        def label(frame_i):
            addr, fi = fa[frame_i], ff[frame_i]
            lib_name = None
            if fr and fi < len(fr):
                r = fr[fi]
                if r is not None and 0 <= r < len(rl):
                    li = rl[r]
                    if li is not None and 0 <= li < len(libs):
                        lib_name = libs[li].get("debugName") or libs[li].get("name")
            if lib_name and lib_name in symtabs:
                rvas, names = symtabs[lib_name]
                i = bisect.bisect_right(rvas, addr) - 1
                if i >= 0:
                    return names[i], lib_name
            return f"0x{addr:x}", (lib_name or "?")

        for si in range(samples["length"]):
            st = stack_col[si]
            if st is None:
                continue
            w = weights[si] if weights else interval
            total += w
            raw_leaf, leaf_lib = label(sf[st])
            if raw_leaf in FPU_RUNTIME:
                fpu_total += w
                # walk up to first frame not in the FPU runtime and not in
                # libgfortran trampolines
                cur = sp[st]
                owner = ("<unattributed fpu>", "")
                while cur is not None:
                    nm, lb = label(sf[cur])
                    if nm not in FPU_RUNTIME:
                        owner = (demangle(nm), lb)
                        break
                    cur = sp[cur]
                adj_self[owner] += w
                fpu_of[owner] += w
            else:
                key = (demangle(raw_leaf), leaf_lib)
                adj_self[key] += w
                pure_self[key] += w

    print(f"total weight {total:.0f}; IEEE-FPU runtime share {fpu_total / total:7.1%}")
    print(f"{'adj self%':>9} {'own%':>6} {'fpu%':>6}  function [library]")
    for key, w in sorted(adj_self.items(), key=lambda kv: -kv[1])[:top_n]:
        name, lib = key
        print(f"{w / total:9.1%} {pure_self.get(key, 0) / total:6.1%} "
              f"{fpu_of.get(key, 0) / total:6.1%}  {name} [{lib}]")


if __name__ == "__main__":
    main()
