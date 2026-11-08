// Copyright 2026 CheshireAra contributors.
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0
// Give DC the finite RGB565/48-bit-address/64-bit-data fetcher type parameters.
// The DUT interface and state are unchanged by this implementation-only wrapper.
`include "axi/typedef.svh"
package e_vga_fetcher_impl_pkg;
  typedef logic [47:0] addr_t;
  typedef logic [1:0] id_t;
  typedef logic [63:0] data_t;
  typedef logic [7:0] strb_t;
  typedef logic [1:0] user_t;
  `AXI_TYPEDEF_ALL(vga, addr_t, id_t, data_t, strb_t, user_t)
  typedef struct packed {logic valid,write;addr_t addr;logic[31:0] wdata;logic[3:0] wstrb;} reg_req_t;
  typedef struct packed {logic ready,error;logic[31:0] rdata;} reg_rsp_t;
endpackage

module vga_capacity_impl import e_vga_fetcher_impl_pkg::*; #(
  parameter int unsigned Depth = 16
)(input logic clk_i,rst_ni,testmode_i,input vga_req_t axi_req_i,
  input vga_resp_t axi_rsp_i,output logic[1:0] err_irq_o,
  input reg_req_t reg_req_i,output reg_rsp_t reg_rsp_o);
  axi_err_unit_wrap #(.AddrWidth(48),.IdWidth(2),.UserErrBits(0),
    .UserErrBitsOffset(0),.NumOutstanding(Depth),.NumStoredErrors(4),
    .DropOldest(0),.axi_req_t(vga_req_t),.axi_rsp_t(vga_resp_t),
    .reg_req_t(reg_req_t),.reg_rsp_t(reg_rsp_t)) dut(.*);
endmodule
