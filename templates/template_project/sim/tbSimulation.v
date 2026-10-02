`ifndef __VCD_FILE__
`define __VCD_FILE__ "example.vcd"
`endif

`timescale 1ns/1ps

module tbSimulation;
    reg [3:0] addr;
    wire [7:0] data;
    integer index;

    example dut (
        .addr(addr),
        .data(data)
    );

    initial begin
        $dumpfile(`__VCD_FILE__);
        $dumpvars(0, tbSimulation);
        $timeformat(-3, 0, " ms", 0);
        $monitor("%0t: addr=%0d data=0x%02h (%c)", $time, addr, data, data);

        // Read "Hello,World!", holding each character for 500 ms.
        for (index = 0; index < 12; index = index + 1) begin
            addr = index;
            #500_000_000; // 500 ms with the 1 ns time unit.
        end
        $finish;
    end
endmodule
