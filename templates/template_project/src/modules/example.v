`timescale 1ns/1ps

module example (
    input [3:0] addr,
    output reg [7:0] data
);
    always @(*) begin
        case (addr)
            4'd0:  data = 8'h48; // H
            4'd1:  data = 8'h65; // e
            4'd2:  data = 8'h6C; // l
            4'd3:  data = 8'h6C; // l
            4'd4:  data = 8'h6F; // o
            4'd5:  data = 8'h2C; // ,
            4'd6:  data = 8'h57; // W
            4'd7:  data = 8'h6F; // o
            4'd8:  data = 8'h72; // r
            4'd9:  data = 8'h6C; // l
            4'd10: data = 8'h64; // d
            4'd11: data = 8'h21; // !
            default: data = 8'h00;
        endcase
    end
endmodule
