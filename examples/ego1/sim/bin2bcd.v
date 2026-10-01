`ifndef __VCD_FILE__
`define __VCD_FILE__ "bin2bcd.vcd"
`endif

module tb_Bin2Bcd;
    reg [9:0] bin_in;
    wire [11:0] bcd_default;
    wire [15:0] bcd_wide;
    reg [11:0] expected_default;
    reg [15:0] expected_wide;
    integer value;
    integer truncated;

    Bin2Bcd default_dut (
        .bin_in(bin_in[7:0]),
        .bcd_out(bcd_default)
    );

    Bin2Bcd #(.BIN_WIDTH(10), .BCD_WIDTH(16)) wide_dut (
        .bin_in(bin_in),
        .bcd_out(bcd_wide)
    );

    initial begin
        bin_in = 0;
        $dumpfile(`__VCD_FILE__);
        $dumpvars(0, bin_in, bcd_default, bcd_wide, expected_default, expected_wide);

        for (value = 0; value < 1024; value = value + 1) begin
            bin_in = value;
            truncated = value % 256;
            expected_default[11:8] = truncated / 100;
            expected_default[7:4] = (truncated / 10) % 10;
            expected_default[3:0] = truncated % 10;
            expected_wide[15:12] = value / 1000;
            expected_wide[11:8] = (value / 100) % 10;
            expected_wide[7:4] = (value / 10) % 10;
            expected_wide[3:0] = value % 10;
            #1;

            if (bcd_default !== expected_default)
                $fatal(1, "default Bin2Bcd: input=%0d got=%h expected=%h",
                       truncated, bcd_default, expected_default);
            if (bcd_wide !== expected_wide)
                $fatal(1, "wide Bin2Bcd: input=%0d got=%h expected=%h",
                       value, bcd_wide, expected_wide);
        end

        $display("PASS: Bin2Bcd default and 10-bit variants");
        $finish;
    end
endmodule
