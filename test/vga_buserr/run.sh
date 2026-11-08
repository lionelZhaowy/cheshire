#!/usr/bin/env bash
# Copyright 2026 CheshireAra contributors.
# Licensed under the Apache License, Version 2.0, see LICENSE for details.
# SPDX-License-Identifier: Apache-2.0
set -u
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
: "${AXI_DIR:?Set AXI_DIR to 78831b6feba265d5ee2683bbf42b4150f8a35c43}"
: "${COMMON_CELLS_DIR:?Set COMMON_CELLS_DIR to 9afda9abb565971649c2aa0985639c096f351171}"
: "${REGISTER_INTERFACE_DIR:?Set REGISTER_INTERFACE_DIR to 5daa85d164cf6b54ad061ea1e4c6f3624556e467}"
: "${UNBENT_DIR:?Set UNBENT_DIR to e9c9d5cfb635f2d4668c816ce9235798cfecb297}"
: "${VGA_DIR:?Set VGA_DIR to 3718b9930f94a9eaad8ee50b4bccc71df0403084}"
: "${FETCHER_SOURCE:?Set FETCHER_SOURCE to the accepted-LAST candidate}"
: "${RUN_DIR:?Set a new absolute RUN_DIR}"
export AXI_DIR COMMON_CELLS_DIR REGISTER_INTERFACE_DIR UNBENT_DIR VGA_DIR RUN_DIR FETCHER_SOURCE
export VGA_TEST_ROOT="$root"
export VGA_ERROR_DEPTH="${VGA_ERROR_DEPTH:-16}"
mkdir "$RUN_DIR"
python3 - <<'PY'
from pathlib import Path
import os,yaml,json,hashlib
out=Path(os.environ['RUN_DIR']);root=Path(os.environ['VGA_TEST_ROOT'])
cc=Path(os.environ['COMMON_CELLS_DIR']);axi=Path(os.environ['AXI_DIR']);reg=Path(os.environ['REGISTER_INTERFACE_DIR']);vga=Path(os.environ['VGA_DIR']);unbent=Path(os.environ['UNBENT_DIR'])
def sources(package):
 def visit(items):
  for item in items:
   if isinstance(item,str):yield package/item
   elif 'test' not in str(item.get('target','')) and item.get('target')!='simulation':yield from visit(item['files'])
 return list(visit(yaml.safe_load((package/'Bender.yml').read_text())['sources']))
files=sources(cc)+sources(axi)+[reg/'vendor/lowrisc_opentitan/src'/n for n in ['prim_subreg_arb.sv','prim_subreg.sv','prim_subreg_ext.sv']]
files += [reg/'src/reg_demux.sv']+sources(unbent)
files += [vga/'src'/n for n in ['axi_vga_reg_pkg.sv','axi_vga_reg_top.sv','axi_vga_timing_fsm.sv']]
files += [Path(os.environ['FETCHER_SOURCE']),vga/'src/axi_vga.sv',root/'test/vga_buserr/tb_e_vga_unit.sv']
files=list(dict.fromkeys(files));includes=[cc/'include',axi/'include',reg/'include']
(out/'sources.f').write_text(''.join('+incdir+'+str(p)+'\n' for p in includes)+''.join(str(p)+'\n' for p in files))
frozen=files+[p for d in includes for p in d.rglob('*.svh')]
(out/'inputs.json').write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in frozen},indent=2)+'\n')
(out/'limit.ucli').write_text('run 2 ms\nquit\n')
PY
cd "$RUN_DIR"
timeout 600 vcs -full64 -sverilog -assert svaext -timescale=1ns/1ps +vcs+lic+wait -top tb_e_vga_unit "+define+VGA_ERROR_DEPTH=$VGA_ERROR_DEPTH" -o simv -Mdir=objects -f sources.f >compile.log 2>&1
rc=$?; echo "$rc" >compile.rc
if [[ $rc != 0 ]]; then exit "$rc"; fi
status=0
for profile in timing flow restart capacity; do
 mkdir "$profile"
 (cd "$profile"; timeout 600 ../simv -ucli -do ../limit.ucli "+E_VGA_UNIT_PROFILE=$profile" >stdout.log 2>&1; echo "$?" >process.rc)
 if ! grep -qx "E_VGA_UNIT_PASS profile=$profile" "$profile/stdout.log"; then status=1; fi
done
exit "$status"
