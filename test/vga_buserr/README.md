# VGA bus-error address capacity

Cheshire `6c6dd5e834347f72c7be31cd6c41021ec293c5b9` sizes the VGA bus-error
address tracker from `CoreMaxTxns`, which is eight in its default configuration.
The old VGA instead admits up to `VgaBufferDepth=16` external read transactions.
The passive error tracker must retain an address for every accepted request.

This candidate changes only that instance to `Cfg.VgaBufferDepth`. The existing
Cheshire PR #293 uses `Cfg.VgaMaxReadTxns=24` together with an APB/SystemRDL
migration. The evidence here concerns the current locked old VGA and does not
validate that migration. A capacity of 24 also exceeds the demonstrated bound.
The candidate and this test support review of the existing PR, not a competing
claim to its broader changes.

## Why the credit bound is sixteen

In the locked VGA `3718b9930f94a9eaad8ee50b4bccc71df0403084`, the external AR is
joined with `credit_valid`. The counter permits issue only below `BufferDepth`.
It increments on an external accepted AR and decrements on an accepted LAST
popped from the registered R FIFO. Therefore

```
external accepted AR - FIFO-popped LAST <= BufferDepth = 16
external accepted AR - external accepted LAST <= that counter
```

`MaxReadTxns=24` configures the burst splitter before this external credit gate.
It does not replace the sixteen-credit external gate. The test drives the real
module to watermarks 0/1/7/8/9/15/16, holds sixteen without a response, releases
one, checks simultaneous AR/R at fifteen, and reaches sixteen again.

## Fixed official inputs

All dependencies below come from the official Cheshire base's Bender.lock.
No F/R dependency or official lock file is changed.

| Package | Commit |
|---|---|
| axi_vga | 3718b9930f94a9eaad8ee50b4bccc71df0403084 |
| axi | 78831b6feba265d5ee2683bbf42b4150f8a35c43 |
| common_cells | 9afda9abb565971649c2aa0985639c096f351171 |
| register_interface | 5daa85d164cf6b54ad061ea1e4c6f3624556e467 |
| unbent | e9c9d5cfb635f2d4668c816ce9235798cfecb297 |

Both variants use the same corrected accepted-LAST fetcher from the companion
[`axi_vga` contribution at `87ed00f2a90be97ca43db40719b9c362e37edcfa`](https://github.com/lionelZhaowy/axi_vga/tree/87ed00f2a90be97ca43db40719b9c362e37edcfa). This prerequisite is explicit: the old fetcher has an
independent request-completion defect. Use the exact public companion source,
not an unrelated local patch stack. All other VGA RTL stays at the locked commit.

## Run the real modules

Use VCS W-2024.09-SP1, Python 3 with PyYAML, and Bash. Obtain the packages at the
exact commits above. Run from this Cheshire checkout. Set absolute paths.

```sh
export AXI_DIR=/absolute/locked/axi
export COMMON_CELLS_DIR=/absolute/locked/common_cells
export REGISTER_INTERFACE_DIR=/absolute/locked/register_interface
export UNBENT_DIR=/absolute/locked/unbent
export VGA_DIR=/absolute/locked/axi_vga
export FETCHER_SOURCE=/absolute/companion-axi_vga/src/axi_vga_fetcher.sv
export VGA_REVIEWER=/absolute/companion-axi_vga/test/retained_completion/review_vga.py

VGA_ERROR_DEPTH=8 RUN_DIR=/tmp/vga-capacity-eight bash test/vga_buserr/run.sh
VGA_ERROR_DEPTH=16 RUN_DIR=/tmp/vga-capacity-sixteen bash test/vga_buserr/run.sh
for variant in eight sixteen; do
  for profile in timing flow restart; do
    python3 "$VGA_REVIEWER" --kind unit --profile "$profile" \
      --run "/tmp/vga-capacity-$variant/$profile" \
      --output "/tmp/vga-capacity-$variant/$profile/audit.json"
  done
  python3 test/vga_buserr/review_capacity.py \
    --run "/tmp/vga-capacity-$variant/capacity" \
    --output "/tmp/vga-capacity-$variant/capacity/audit.json"
done
```

The eight-entry capacity command is expected to fail. Both use identical test
bytes and stimulus. Only `VGA_ERROR_DEPTH` changes the real `axi_err_unit_wrap`
instance parameter. `E_VGA_INSTANCE` prints that actual parameter, the actual
VGA buffer depth and the splitter limit. Each build records all source/header
SHA values. Each simulation has a 2 ms HDL and 600-second wall limit.

The test instantiates the complete real old VGA and its passive error-unit
wrapper. The wrapper is not a behavior model and is not inserted into the data
path. Address48, ID2, UserErrBits0, NumStoredErrors4 and DropOldest0 match the
Cheshire VGA instance. The independent reader owns its public accepted-AR FIFO.
It checks each accepted R, response ID, full error address and metadata, IRQ,
peek/pop behavior and transaction balance. Error-response payload is not used
as valid numeric gold.

## Actual results

| Profile | Eight entries | Sixteen entries |
|---|---|---|
| timing, two cases / 512 display pixels | Pass | Pass |
| flow, three cases / 768 display plus 256 black pixels | Native overflow failures despite zero pixel errors | Pass |
| restart, three cases / 768 display pixels | Pass | Pass |
| capacity, one case / 2181 in-test checks | 8 wrong address/high-address readbacks and overflow warnings | 0 errors |

The capacity input performs 32 accepted AR and 32 accepted R transfers. It holds
sixteen credits, checks a simultaneous AR/R edge at fifteen, then injects one
SLVERR and one DECERR. It checks ADDR/TOP/META, repeats ADDR peeks, verifies a CODE write does
not pop the head, and uses a CODE read to pop it and clear IRQ. A normal response
follows each cleared error. Final outstanding requests, error FIFO and IRQ are
empty. The independent sixteen-entry reader performs 3303 checks with no errors
or missing data. The original fails at normal test finalization, not at timeout.
The flow baseline's native warning is a failure even though pixels match.

The three original display profiles keep their independent pixel, sync,
transaction, reset and drain checks. They cover explicit disable/drain and reset
with requests in flight. Deliberate underflow recovery uses a common reset.
No EEPROM model or complete private SoC is required.

## Actual implementation checks

The full real typed `axi_err_unit_wrap` was checked at Depth8 and Depth16 with
DC W-2024.09-SP1. The included `vga_capacity_impl.sv` fixes the same public types.
Use `check_structure.tcl` with `OUT`, `INPUTS`, `VARIANT`, `MODULE=vga`,
`TOP=vga_capacity_impl` and `DEPTH=8` or `16`. The output directory contains
`sources.list` and `includes.list`. Its source list is:

```
COMMON_CELLS_DIR/src/cf_math_pkg.sv
AXI_DIR/src/axi_pkg.sv
COMMON_CELLS_DIR/src/fifo_v3.sv
COMMON_CELLS_DIR/src/onehot_to_bin.sv
REGISTER_INTERFACE_DIR/vendor/lowrisc_opentitan/src/prim_subreg_ext.sv
REGISTER_INTERFACE_DIR/src/reg_demux.sv
UNBENT_DIR/src/bus_err_unit_bare.sv
UNBENT_DIR/src/bus_err_unit_reg_pkg.sv
UNBENT_DIR/src/bus_err_unit_reg_top.sv
UNBENT_DIR/src/bus_err_unit.sv
UNBENT_DIR/src/axi_err_unit_wrap.sv
THIS_CHECKOUT/test/vga_buserr/vga_capacity_impl.sv
```

Replace the path prefixes with the absolute values above. The include list has
`COMMON_CELLS_DIR/include`, `AXI_DIR/include` and `REGISTER_INTERFACE_DIR/include`.
Run `timeout 1800 dc_shell -f test/vga_buserr/check_structure.tcl` with those
variables. Both parameterizations have zero latches, loops, multiple drivers,
unexplained cells or final blackboxes. They contain 3718/6942 flip-flops and
28620/49996 hierarchical generic cells. `compile -no_map` is a structural check,
not technology timing or area signoff. VCS `+lint=all` on the two actual typed
instances has identical inherited warning categories and counts. No assertion
is disabled in the functional comparisons.

AI assistance: OpenAI Codex assisted implementation, test preparation and
validation. A separate AI technical review is recorded with the contribution.
This does not claim a human review.
