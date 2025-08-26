#!/usr/bin/env python3

import argparse
import subprocess
import re
import sys

flags = argparse.ArgumentParser(description="Trace file helper")
flags.add_argument(
    "--logging",
    default="info",
    choices=["debug", "info", "warning", "error", "critical"],
    help="Logging level",
)
flags.add_argument(
    "--elf",
    type=str,
    help="ELF file"
)
flags.add_argument(
    "--objdump",
    type=str,
    default="/tools/riscv/bin/riscv32-unknown-elf-objdump",
    help="Location of objdump program"
)
flags.add_argument(
    "--map",
    type=str,
    help="Save a mapfile to this filename",
)
flags.add_argument(
    "trace",
    type=str,
    nargs='?',
    help="Verilator trace file"
)

class Mapfile(object):
  SYMBOL = re.compile(r'(?P<addr>\w+)\s(?P<flags>.......)\s(?P<section>[^\s]+)\s(?P<size>\w+)\s(?P<name>.*)')

  def __init__(self, elf, objdump=None):
    self.objdump = "objdump" if objdump is None else objdump
    self.symbols = []
    self.parse(elf)

  def parse(self, elf):
    syms = subprocess.check_output([self.objdump, "--syms", "--demangle", elf]).decode('utf-8')
    for line in syms.split('\n'):
      if m := self.SYMBOL.match(line):
        addr = int(m.group("addr"), 16)
        (binding, weakness, construct, warning, indirect, debug, objtype) = m.group("flags")
        section = m.group("section")
        size = int(m.group("size"), 16)
        name = m.group("name")
        if objtype != ' ':
          self.symbols.append((addr, size, name))
    self.symbols.sort()

  def save(self, filename):
    with open(filename, "wt") as f:
      for addr, size, name in self.symbols:
        print(f"{addr:08x} {size:08x} {name}", file=f)

  def address(self, address):
    for i in range(0, len(self.symbols)):
      addr, _, _ = self.symbols[i]
      if i>0 and address < addr:
        addr, size, name = self.symbols[i-1]
        delta = address - addr
        if delta < size:
          return f"{name}+{delta:04x}"
        elif delta < 0x10000:
          return f"{name}?{delta:04x}"
        else:
          break
    return f"{address:08x}"

class Tracefile(object):
  TRACE = re.compile(r'\s+(?P<time>\d+)\s+(?P<cycle>\d+)\s+(?P<addr>\w+)\s+(?P<opcode>\w+)\s+(?P<instruction>[^ ]+)\s+(?P<values>x\d+[=:].*)?')

  def __init__(self, mapfile):
    self.mapfile = mapfile
    self.uart = []

  def parse_values(self, values):
    attr = {}
    for value in re.split(r'\s+', values):
      if ':' in value:
        k, v = value.split(':')
        attr[k] = int(v, 0)

    if attr.get('PA') == 0x4000001c:
      c = chr(attr.get('store'))
      if c == '\n':
        print("UART line:", ''.join(self.uart))
        self.uart = []
      else:
        print(f"UART char: {c}")
        self.uart.append(c)


  def parse(self, tracefile):
    with open(tracefile, "rt") as trace:
      for line in trace:
        if m := self.TRACE.match(line):
          addr = int(m.group("addr"), 16)
          (opcode, *operand) = m.group("instruction").strip().split('\t')
          if operand:
            opcode = f"{opcode:<8} {operand[0]}"
          values = m.group("values") or ""
          values = values.strip()
          symbol = self.mapfile.address(addr)
          print(f"{addr:08x} {symbol:<40} {opcode:<32} {values}")
          self.parse_values(values)



def main(args):
  mf = Mapfile(args.elf, args.objdump)
  if args.map:
    mf.save(args.map)
    return 0

  t = Tracefile(mf)
  t.parse(args.trace)
  return 0

if __name__ == '__main__':
  sys.exit(main(flags.parse_args()))

