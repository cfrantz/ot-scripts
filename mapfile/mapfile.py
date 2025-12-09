#!/usr/bin/env python3

import argparse
import subprocess
import logging
import re
import sys
import os.path

logger = logging.getLogger(__name__)

MAPFILE_FIELDS = ["address", "size", "section", "name"]

flags = argparse.ArgumentParser(description="ELF mapfile helper")
flags.add_argument(
    "--logging",
    default="info",
    choices=["debug", "info", "warning", "error", "critical"],
    help="Logging level",
)
flags.add_argument("--elf", type=str, help="ELF file")
flags.add_argument(
    "--objdump",
    type=str,
    default="/tools/riscv/bin/riscv32-unknown-elf-objdump",
    help="Location of objdump program",
)
flags.add_argument(
    "--map",
    type=str,
    help="Save a mapfile to this filename and exit",
)
flags.add_argument(
    "--map-sort",
    type=str,
    default="address",
    choices=MAPFILE_FIELDS,
    help="Sort the mapfile on this field (only valid with --map)",
)
flags.add_argument(
    "--sections",
    type=str,
    help="Comma separated list of sections to include in the diff analysis",
)
flags.add_argument("mapfile", type=str, nargs="*", help="Mapfiles to diff")


class Mapfile(object):
    SYMBOL = re.compile(
        r"(?P<addr>\w+)\s(?P<flags>.......)\s(?P<section>[^\s]+)\s(?P<size>\w+)\s(?P<name>.*)"
    )

    def __init__(self, elf, objdump=None, sortkey=0):
        self.objdump = "objdump" if objdump is None else objdump
        self.symbols = []
        if isinstance(sortkey, str):
            sortkey = MAPFILE_FIELDS.index(sortkey)
        self.sortkey = sortkey
        self.parse(elf)

    def parse(self, elf):
        syms = subprocess.check_output(
            [self.objdump, "--syms", "--demangle", elf]
        ).decode("utf-8")
        for line in syms.split("\n"):
            if m := self.SYMBOL.match(line):
                addr = int(m.group("addr"), 16)
                (binding, weakness, construct, warning, indirect, debug, objtype) = (
                    m.group("flags")
                )
                section = m.group("section")
                size = int(m.group("size"), 16)
                name = m.group("name")
                if objtype != " " and name:
                    self.symbols.append((addr, size, section, name))
        self.symbols.sort(key=lambda entry: entry[self.sortkey])

    def save(self, filename):
        with open(filename, "wt") as f:
            for addr, size, section, name in self.symbols:
                print(f"{addr:08x} {size:08x} {section} {name}", file=f)

    def address(self, address):
        for i in range(0, len(self.symbols)):
            addr, _, _, _ = self.symbols[i]
            if i > 0 and address < addr:
                addr, size, name = self.symbols[i - 1]
                delta = address - addr
                if delta < size:
                    return f"{name}+{delta:04x}"
                elif delta < 0x10000:
                    return f"{name}?{delta:04x}"
                else:
                    break
        return f"{address:08x}"


class MapDiff(object):

    def __init__(self, mapa, mapb, sections=[]):
        self.namea, _ = os.path.splitext(os.path.basename(mapa))
        self.nameb, _ = os.path.splitext(os.path.basename(mapb))
        self.mapa = self.parse_mapfile(mapa, sections)
        self.mapb = self.parse_mapfile(mapb, sections)

    def size_report(self):
        a = set(self.mapa.keys())
        b = set(self.mapb.keys())

        a_only = a - b
        b_only = b - a
        common = (a | b) - (a_only | b_only)

        a_report = []
        for sym in a_only:
            a_report.append((sym, self.mapa[sym][1]))
        a_report.sort(reverse=True, key=lambda x: x[1])
        b_report = []
        for sym in b_only:
            b_report.append((sym, self.mapb[sym][1]))
        b_report.sort(reverse=True, key=lambda x: x[1])
        common_report = []
        for sym in common:
            common_report.append((sym, self.mapa[sym][1], self.mapb[sym][1]))
        common_report.sort(reverse=True, key=self._size_score)

        total_a = 0
        total_b = 0
        print(f"{self.namea:<16} {self.nameb:<16}      Delta  Symbol")
        print(f"---------------- ---------------- ----------  ----------------")

        for sym, sz in a_report:
            delta = sz
            print(f"{sz:08x}                          {delta: #10x}  {sym}")
            total_a += sz
        for sym, sz in b_report:
            delta = -sz
            print(f"                 {sz:08x}         {delta: #10x}  {sym}")
            total_b += sz
        for sym, sa, sb in common_report:
            delta = sa - sb
            print(f"{sa:08x}         {sb:08x}         {delta: #10x}  {sym}")
            total_a += sa
            total_b += sb

        delta = total_a - total_b
        print(f"{total_a:08x}         {total_b:08x}         {delta: #10x}  Total Size")

    @staticmethod
    def _size_score(x):
        if delta := abs(x[1] - x[2]):
            return 1000000 * delta
        return x[1]

    @staticmethod
    def parse_mapfile(filename, sections=[]):
        mf = {}
        with open(filename, "rt") as f:
            for line in f:
                line = line.strip()
                (addr, size, section, symbol) = line.split(" ", 3)
                if sections and section not in sections:
                    continue
                mf[symbol] = (int(addr, 16), int(size, 16))
        return mf


def main(args):
    logging.basicConfig(level=args.logging.upper())
    if args.map:
        mf = Mapfile(args.elf, args.objdump, sortkey=args.map_sort)
        mf.save(args.map)
        return 0

    if len(args.mapfile) != 2:
        logging.error("Expected 2 mapfiles")
        return 1

    if args.sections:
        sections = args.sections.split(",")
    else:
        sections = []

    diff = MapDiff(args.mapfile[0], args.mapfile[1], sections=sections)
    diff.size_report()
    return 0


if __name__ == "__main__":
    sys.exit(main(flags.parse_args()))
