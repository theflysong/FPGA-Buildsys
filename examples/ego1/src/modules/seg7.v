module Driver7Seg #(
    parameter integer SCAN_CYCLES = 25000
) (
    input  wire       clk,
    input  wire [7:0] sw,
    output wire [6:0] seg_out,
    output wire [7:0] ans_out
);
    localparam integer COUNT_WIDTH = (SCAN_CYCLES > 1) ? $clog2(SCAN_CYCLES) : 1;

    localparam [COUNT_WIDTH-1:0] SCAN_LAST = SCAN_CYCLES[COUNT_WIDTH-1:0] - 1'b1;

    reg [COUNT_WIDTH-1:0] scan_count = 0;
    // 用于选择当前显示的数字位，0-3分别对应4位数码管
    reg [1:0] digit_index = 0;

    always @(posedge clk) begin
        if (scan_count == SCAN_LAST) begin
            scan_count <= 0;
            digit_index <= digit_index + 2'd1;
        end else begin
            scan_count <= scan_count + 1'b1;
        end
    end

    wire [11:0] conv_bcd_code;
    wire [7:0] bin_in;

    assign bin_in = sw;

    Bin2Bcd #(.BIN_WIDTH(8), .BCD_WIDTH(12)) bcd_converter (
        .bin_in(bin_in),
        .bcd_out(conv_bcd_code)
    );

    wire [15:0] bcd_code;
    assign bcd_code = {4'b0000, conv_bcd_code};

    reg [3:0] selected_bcd;
    always @(*) begin
        case (digit_index)
            2'd0: selected_bcd = bcd_code[15:12];
            2'd1: selected_bcd = bcd_code[11:8];
            2'd2: selected_bcd = bcd_code[7:4];
            2'd3: selected_bcd = bcd_code[3:0];
        endcase
    end

    wire [6:0] seg_code;
    Bcd2Seg7 #(
        .is_coanode(0)
    ) anode7seg_converter (
        .bcd_in(selected_bcd),
        .seg7_out(seg_code)
    );

    // Bcd2Seg7 uses [6:0] = abcdefg; the board pins use [0:6] = abcdefg.
    assign seg_out = {seg_code[0], seg_code[1], seg_code[2],
                      seg_code[3], seg_code[4], seg_code[5], seg_code[6]};
    assign ans_out = 8'b0000_0001 << digit_index;
endmodule
