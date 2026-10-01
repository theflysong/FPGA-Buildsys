`ifndef __VCD_FILE__
`define __VCD_FILE__ "bcd2seg7.vcd"
`endif

module tb_Bcd2Seg7;
    reg [3:0] bcd_in;
    wire [6:0] anode_out;
    wire [6:0] cathode_out;
    integer digit;

    Bcd2Seg7 anode_dut (
        .bcd_in(bcd_in),
        .seg7_out(anode_out)
    );

    Bcd2Seg7 #(.is_coanode(0)) cathode_dut (
        .bcd_in(bcd_in),
        .seg7_out(cathode_out)
    );

    function [6:0] expected_cathode;
        input [3:0] value;
        begin
            case (value)
                4'd0: expected_cathode = 7'b1111110;
                4'd1: expected_cathode = 7'b0110000;
                4'd2: expected_cathode = 7'b1101101;
                4'd3: expected_cathode = 7'b1111001;
                4'd4: expected_cathode = 7'b0110011;
                4'd5: expected_cathode = 7'b1011011;
                4'd6: expected_cathode = 7'b1011111;
                4'd7: expected_cathode = 7'b1110000;
                4'd8: expected_cathode = 7'b1111111;
                4'd9: expected_cathode = 7'b1111011;
                default: expected_cathode = 7'b0000000;
            endcase
        end
    endfunction

    initial begin
        bcd_in = 0;

        $dumpfile(`__VCD_FILE__);
        $dumpvars(0, bcd_in, anode_out, cathode_out);

        for (digit = 0; digit < 16; digit = digit + 1) begin
            bcd_in = digit;
            #1;
            if (cathode_out !== expected_cathode(bcd_in))
                $fatal(1, "cathode Bcd2Seg7: input=%0d got=%b expected=%b",
                       digit, cathode_out, expected_cathode(bcd_in));
            if (anode_out !== ~expected_cathode(bcd_in))
                $fatal(1, "anode Bcd2Seg7: input=%0d got=%b expected=%b",
                       digit, anode_out, ~expected_cathode(bcd_in));
        end

        $display("PASS: Bcd2Seg7 anode and cathode, inputs 0-15");
        $finish;
    end
endmodule
