# EGO1: 100 MHz clk, sw <- SW0~SW7; seg_out(a~g) -> CA0~CG0; ans_out(BIT1~BIT8) -> DN0_K1..DN1_K4.

set_property PACKAGE_PIN P17 [get_ports {clk}]
set_property IOSTANDARD LVCMOS33 [get_ports {clk}]

# 拨码开关 SW0~SW7 -> sw[0]~[7]
set_property PACKAGE_PIN R1 [get_ports {sw[0]}]
set_property IOSTANDARD LVCMOS33 [get_ports {sw[0]}]

set_property PACKAGE_PIN N4 [get_ports {sw[1]}]
set_property IOSTANDARD LVCMOS33 [get_ports {sw[1]}]

set_property PACKAGE_PIN M4 [get_ports {sw[2]}]
set_property IOSTANDARD LVCMOS33 [get_ports {sw[2]}]

set_property PACKAGE_PIN R2 [get_ports {sw[3]}]
set_property IOSTANDARD LVCMOS33 [get_ports {sw[3]}]

set_property PACKAGE_PIN P2 [get_ports {sw[4]}]
set_property IOSTANDARD LVCMOS33 [get_ports {sw[4]}]

set_property PACKAGE_PIN P3 [get_ports {sw[5]}]
set_property IOSTANDARD LVCMOS33 [get_ports {sw[5]}]

set_property PACKAGE_PIN P4 [get_ports {sw[6]}]
set_property IOSTANDARD LVCMOS33 [get_ports {sw[6]}]

set_property PACKAGE_PIN P5 [get_ports {sw[7]}]
set_property IOSTANDARD LVCMOS33 [get_ports {sw[7]}]

# 右侧数码管段选 CA0~CG0（位序 a,b,c,d,e,f,g）
set_property PACKAGE_PIN B2 [get_ports {seg_out[0]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_out[0]}]

set_property PACKAGE_PIN B3 [get_ports {seg_out[1]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_out[1]}]

set_property PACKAGE_PIN A1 [get_ports {seg_out[2]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_out[2]}]

set_property PACKAGE_PIN B1 [get_ports {seg_out[3]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_out[3]}]

set_property PACKAGE_PIN A3 [get_ports {seg_out[4]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_out[4]}]

set_property PACKAGE_PIN A4 [get_ports {seg_out[5]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_out[5]}]

set_property PACKAGE_PIN B4 [get_ports {seg_out[6]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_out[6]}]

# 片选 BIT1~BIT8（ans_out[0]=BIT1 最右，ans_out[7]=BIT8 最左）
set_property PACKAGE_PIN G2 [get_ports {ans_out[0]}]
set_property IOSTANDARD LVCMOS33 [get_ports {ans_out[0]}]

set_property PACKAGE_PIN C2 [get_ports {ans_out[1]}]
set_property IOSTANDARD LVCMOS33 [get_ports {ans_out[1]}]

set_property PACKAGE_PIN C1 [get_ports {ans_out[2]}]
set_property IOSTANDARD LVCMOS33 [get_ports {ans_out[2]}]

set_property PACKAGE_PIN H1 [get_ports {ans_out[3]}]
set_property IOSTANDARD LVCMOS33 [get_ports {ans_out[3]}]

set_property PACKAGE_PIN G1 [get_ports {ans_out[4]}]
set_property IOSTANDARD LVCMOS33 [get_ports {ans_out[4]}]

set_property PACKAGE_PIN F1 [get_ports {ans_out[5]}]
set_property IOSTANDARD LVCMOS33 [get_ports {ans_out[5]}]

set_property PACKAGE_PIN E1 [get_ports {ans_out[6]}]
set_property IOSTANDARD LVCMOS33 [get_ports {ans_out[6]}]

set_property PACKAGE_PIN G6 [get_ports {ans_out[7]}]
set_property IOSTANDARD LVCMOS33 [get_ports {ans_out[7]}]