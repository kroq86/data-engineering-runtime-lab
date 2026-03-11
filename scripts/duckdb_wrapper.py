#!/usr/bin/env python3
from __future__ import annotations

import sys

import duckdb


def main() -> int:
    args = sys.argv[1:]
    sql = None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "-c" and i + 1 < len(args):
            sql = args[i + 1]
            i += 2
            continue
        if arg == "-noheader":
            i += 1
            continue
        i += 1

    if not sql:
        print("duckdb wrapper expects -c <SQL>", file=sys.stderr)
        return 2

    rows = duckdb.sql(sql).fetchall()
    for row in rows:
        print("\t".join("" if value is None else str(value) for value in row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
