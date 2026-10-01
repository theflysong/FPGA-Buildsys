`ifndef __VCD_FILE__
`define __VCD_FILE__ "structural_hw.vcd"
`endif

`timescale 1ns/1ps

module tb_shw();
    reg  x;
    reg  y;
    reg  z;
    wire out;

    // 实例化被测模块
    structural_hw shw (
        .x   (x),
        .y   (y),
        .z   (z),
        .out (out)
    );

    integer i, j, k;
    reg expected_out;
    integer error_count;
    initial begin
        $dumpfile(`__VCD_FILE__);
        $dumpvars(0, x, y, z, out);

        error_count = 0;

        // 遍历所有输入组合
        for (i = 0; i < 2; i = i + 1) begin
            for (j = 0; j < 2; j = j + 1) begin
                for (k = 0; k < 2; k = k + 1) begin
                    x = i[0];
                    y = j[0];
                    z = k[0];

                    #10;  // 等待组合逻辑稳定

                    // 计算期望值
                    expected_out = (~x & ~y & z) | (~x & y & z) | (x & ~y);

                    // 比较实际输出与期望值
                    if (out !== expected_out) begin
                        $display("ERROR: x=%0d, y=%0d, z=%0d -> out=%0d; expected out=%0d",
                                 x, y, z, out, expected_out);
                        error_count = error_count + 1;
                    end
                end
            end
        end

        if (error_count == 0)
            $display("All tests passed!");
        else
            $display("Test failed with %0d errors.", error_count);

        $finish;
    end
endmodule