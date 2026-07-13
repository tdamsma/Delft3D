#!/usr/bin/env python3
"""Extract a ranked self-time function list from a samply profile recorded
with `samply record --save-only --unstable-presymbolicate`.

Usage: python3 samply_top.py profile.json.gz [topN]

Joins the profile's frame addresses (rva) against the .syms.json sidecar's
per-library symbol tables (rva ranges -> symbol names). Self time = sample
weight whose leaf frame falls in the function; inclusive = weight of samples
with the function anywhere on the stack. Demangles gfortran module procedures
(__module_MOD_proc -> module::proc).
"""
import bisect
import gzip
import json
import re
import sys
from collections import defaultdict
from pathlib import Path


def demangle(name: str) -> str:
    m = re.match(r"^_*(\w+?)_MOD_(\w+)$", name)
    if m:
        return f"{m.group(1).lstrip('_')}::{m.group(2)}"
    return name


def load_syms(path: Path):
    """debug_name -> (sorted rva list, parallel (end, name) list)."""
    d = json.loads(path.read_text())
    st = d["string_table"]
    out = {}
    for lib in d["data"]:
        entries = sorted(lib.get("symbol_table") or [], key=lambda e: e["rva"])
        rvas = [e["rva"] for e in entries]
        info = [(e["rva"] + e.get("size", 0), st[e["symbol"]]) for e in entries]
        out[lib["debug_name"]] = (rvas, info)
    return out


def main():
    path = Path(sys.argv[1])
    top_n = int(sys.argv[2]) if len(sys.argv) > 2 else 25
    syms_path = Path(str(path).replace(".json.gz", ".json.syms.json"))
    symtabs = load_syms(syms_path) if syms_path.is_file() else {}

    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt") as f:
        prof = json.load(f)

    libs = prof.get("libs", [])

    def resolve(lib_idx, address):
        if lib_idx is None or lib_idx < 0 or lib_idx >= len(libs):
            return (f"0x{address:x}", "<unknown lib>")
        lib_name = libs[lib_idx].get("debugName") or libs[lib_idx].get("name")
        tab = symtabs.get(lib_name)
        if not tab:
            return (f"0x{address:x}", lib_name)
        rvas, info = tab
        i = bisect.bisect_right(rvas, address) - 1
        if i < 0:
            return (f"0x{address:x}", lib_name)
        end, name = info[i]
        return (demangle(name), lib_name)

    self_w = defaultdict(float)
    incl_w = defaultdict(float)
    grand_total = 0.0

    for th in prof["threads"]:
        samples = th["samples"]
        stack_col = samples["stack"]
        n = samples["length"]
        weights = samples.get("weight")
        interval = prof["meta"].get("interval", 1.0)

        stack_prefix = th["stackTable"]["prefix"]
        stack_frame = th["stackTable"]["frame"]
        frame_address = th["frameTable"]["address"]
        frame_func = th["frameTable"]["func"]
        func_resource = th["funcTable"].get("resource", [])
        res_lib = th.get("resourceTable", {}).get("lib", [])

        def frame_label(frame_i):
            addr = frame_address[frame_i]
            fi = frame_func[frame_i]
            lib_idx = None
            if func_resource and fi < len(func_resource):
                r = func_resource[fi]
                if r is not None and r >= 0 and r < len(res_lib):
                    lib_idx = res_lib[r]
            return resolve(lib_idx, addr)

        for si in range(n):
            st = stack_col[si]
            if st is None:
                continue
            w = weights[si] if weights else interval
            grand_total += w
            self_w[frame_label(stack_frame[st])] += w
            seen = set()
            cur = st
            while cur is not None:
                lbl = frame_label(stack_frame[cur])
                if lbl not in seen:
                    seen.add(lbl)
                    incl_w[lbl] += w
                cur = stack_prefix[cur]

    ranked = sorted(self_w.items(), key=lambda kv: -kv[1])[:top_n]
    print(f"grand total sample weight: {grand_total:.0f}")
    print(f"{'self':>10} {'self %':>7} {'incl %':>7}  function  [library]")
    for (name, lib), w in ranked:
        tot = incl_w.get((name, lib), 0.0)
        print(f"{w:10.0f} {w / grand_total:7.1%} {tot / grand_total:7.1%}  {name}  [{lib}]")


if __name__ == "__main__":
    main()
