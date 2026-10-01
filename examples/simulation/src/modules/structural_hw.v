`timescale 1ns/1ps

module structural_hw (
    input x,
    input y,
    input z,
    output out
);
    wire _x;
    wire _y;

    wire t1;
    wire t2;
    wire t3;

    not n1(_x, x);
    not n2(_y, y);
    and a1(t1, _x, _y, z);
    and a2(t2, _x,  y, z);
    and a3(t3,  x, _y);
    or  o1(out, t1, t2, t3);
endmodule