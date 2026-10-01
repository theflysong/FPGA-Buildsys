`ifndef __VCD_FILE__
`define __VCD_FILE__ "driver7seg.vcd"
`endif

module tb_Driver7Seg;
    reg clk = 0;
    reg [7:0] sw;
    wire [6:0] seg_out;
    wire [7:0] ans_out;

    Driver7Seg #(.SCAN_CYCLES(3)) dut (
        .clk(clk),
        .sw(sw),
        .seg_out(seg_out),
        .ans_out(ans_out)
    );

    task check_display;
        input [7:0] expected_ans;
        input [6:0] expected_seg;
        begin
            if (ans_out !== expected_ans || seg_out !== expected_seg)
                $fatal(1, "ans=%b seg=%b expected ans=%b seg=%b",
                       ans_out, seg_out, expected_ans, expected_seg);
        end
    endtask

    task advance_slot;
        integer i;
        begin
            for (i = 0; i < 3; i = i + 1) begin
                #1 clk = 1;
                #1 clk = 0;
            end
            #1;
        end
    endtask

    initial begin
        $dumpfile(`__VCD_FILE__);
        $dumpvars(0, tb_Driver7Seg);
        sw = 8'd123;
        #1;
        check_display(8'b0000_0001, 7'b0111111); // 0
        advance_slot();
        check_display(8'b0000_0010, 7'b0000110); // 1
        advance_slot();
        check_display(8'b0000_0100, 7'b1011011); // 2
        advance_slot();
        check_display(8'b0000_1000, 7'b1001111); // 3
        advance_slot();
        check_display(8'b0000_0001, 7'b0111111); // wrap to 0

        sw = 8'd255;
        #1;
        check_display(8'b0000_0001, 7'b0111111); // 0
        advance_slot();
        check_display(8'b0000_0010, 7'b1011011); // 2
        advance_slot();
        check_display(8'b0000_0100, 7'b1101101); // 5
        advance_slot();
        check_display(8'b0000_1000, 7'b1101101); // 5

        $display("PASS: Driver7Seg scans four BCD digits");
        $finish;
    end
endmodule
