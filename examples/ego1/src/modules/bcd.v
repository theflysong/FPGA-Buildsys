//!bcd.v
//!
//!Author: theflysong (song_of_the_fly@163.com)
//!
//!# BCD 相关模块
//!

//!## Binary 转换为 BCD 模块
//!
//!### Parameters
//!
//! - `parameter BIN_WIDTH` : 输入二进制数的位宽, 默认值为 8, 即 0~255
//! - `parameter BCD_WIDTH` : 输出 BCD 数的位宽, 默认值为 12, 即 3 位 BCD 数
//!
//! Static Assertion: 2^BIN_WIDTH <= 10^(ceil(BCD_WIDTH/4))
//!
//!### Ports
//!
//! - `input [BIN_WIDTH-1:0] bin_in` : 输入二进制数
//! - `output reg [BCD_WIDTH-1:0] bcd_out` : 输出 BCD 数
//!
//!### Description
//!
//!使用 Double Dabble 算法将二进制数转换为 BCD 数.
//!
module Bin2Bcd #(
    parameter BIN_WIDTH = 8,
    parameter BCD_WIDTH = 12
)(
    input  [BIN_WIDTH-1:0] bin_in,
    output reg [BCD_WIDTH-1:0] bcd_out
);

    integer i, k;
    reg [BCD_WIDTH-1:0] bcd;
    reg [BIN_WIDTH-1:0] bin;

    always @(*) begin
        bcd = {BCD_WIDTH{1'b0}};
        bin = bin_in;

        for (i = 0; i < BIN_WIDTH; i = i + 1) begin
            // 对每个 BCD 位检查是否 >= 5，是则加 3
            for (k = 0; k < BCD_WIDTH/4; k = k + 1) begin
                if (bcd[k*4 +: 4] >= 4'd5)
                    bcd[k*4 +: 4] = bcd[k*4 +: 4] + 4'd3;
            end

            // 整体左移，二进制最高位进入 BCD 最低位
            bcd = (bcd << 1) | bin[BIN_WIDTH-1];
            bin = bin << 1;
        end

        bcd_out = bcd;
    end
endmodule

//!## BCD 转 7-Segment 模块
//!
//!### Parameters
//!
//! - `parameter is_coanode` : 选择共阳极或共阴极的 7 段数码管, 默认值为 1, 即共阳极
//!
//!### Ports
//!
//! - `input [3:0] bcd_in` : 输入 BCD 数
//! - `output reg [6:0] seg7_out` : 输出 7-Seg 数码管的段选信号
//!
//!### Description
//!
//!将 BCD 数转换为 7 段数码管的段选信号, 支持共阳极和共阴极两种类型的数码管.
//!
module Bcd2Seg7 #(
    parameter is_coanode = 1
)(
    input [3:0] bcd_in,
    output reg [6:0] seg7_out
);
    // 共阴极编码: 1 表示点亮, 0 表示熄灭
    // 位序：abcdefg
    always @(*) begin
        case (bcd_in)
            4'd0: seg7_out = 7'b1111110;
            4'd1: seg7_out = 7'b0110000;
            4'd2: seg7_out = 7'b1101101;
            4'd3: seg7_out = 7'b1111001;
            4'd4: seg7_out = 7'b0110011;
            4'd5: seg7_out = 7'b1011011;
            4'd6: seg7_out = 7'b1011111;
            4'd7: seg7_out = 7'b1110000;
            4'd8: seg7_out = 7'b1111111;
            4'd9: seg7_out = 7'b1111011;
            default: seg7_out = 7'b0000000; // 非 BCD 输入, 熄灭
        endcase

        // 共阳极低电平点亮, 因此对共阴极编码取反
        if (is_coanode)
            seg7_out = ~seg7_out;
    end
endmodule