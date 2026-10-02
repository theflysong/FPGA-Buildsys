# FPGA Buildsystem

一个针对 FPGA 项目的构建系统, 基于 python 3.11+. 支持仿真, 综合, 实现, 生成比特流和烧录. 目前支持 Icarus Verilog 仿真器和 yosys + nextpnr + fasm2frames + xc7frames2bit 的 FPGA 工具链. 未来计划支持更多的仿真器和 FPGA 工具链.

## How to use

该项目要求 Python 3.11+, 前置库见 requirements.txt.
要使用该系统, 请将仓库克隆到你的项目目录的子目录中.

## 运行示例

你可以通过 python3 脚本运行该构建系统, 如:

```sh
python3 main.py --project [path-to-your-project] aux
python3 main.py --project [path-to-your-project] script
python3 main.py --project [path-to-your-project] build [target]
python3 main.py --project [path-to-your-project] simulate [target]
```

也可以将快捷入口安装到已有的项目目录中, 这样可以直接使用 `./buildsys` 来运行构建系统:

```sh
python3 main.py install buildsys [path-to-your-project]
cd [path-to-your-project]
./buildsys script
./buildsys.sh aux
./buildsys build [target]
./buildsys simulate [target]
```

`./buildsys` 和 `./buildsys.sh` 都会将参数转发给 `main.py`, 并自动将脚本所在目录作为 `--project` 参数传递. 这意味着你可以在任何地方运行这些脚本, 只要它们位于你的项目目录中.

此外, 还可以安装 Bash Tab 补全功能. 这需要 `sudo` 权限, 并且需要将补全文件安装到 `/usr/share/bash-completion/completions` 或其他 Bash 补全搜索路径中:

```sh
sudo python3 main.py install completion
# 或者指定安装目录
sudo python3 main.py install completion /usr/share/bash-completion/completions
```

安装后打开新终端, 或在当前终端执行:

```sh
source /usr/share/bash-completion/completions/buildsys
```

按 Tab 时, 补全入口调用 `buildsys completion`. 仿真 id 优先来自 `build/aux/*.f`, 程序 id 优先来自 `build/aux/*.ys`; 两类分别判断, 没有对应辅助文件时通过独立的 `completion_ids.py` 只读 `configuration.toml` 中的任务 id. 因此首次构建前、全项目 `cleandist` 后也能补全目标. 已有辅助文件时沿用文件名候选, 不因前缀无匹配而改读配置; 配置修改后可重新生成辅助文件, 删除或改名时先清除旧辅助文件.

补全不会执行 configure、生成文件、读取 FPGA 本地设置或探测 USB; 配置缺失或无效时静默返回空的 id 候选. 跨目录调用快捷入口时仍读取该入口对应项目的配置.

## 构建流程

该构建系统的构建流程如下所示:

```
aux -> script ---|---> build -> simulate
                 |
                 |---> synthesis -> implementation -> bitstream -> program
```

指定中间环节的任意一个(除program)都会触发前置环节的执行. 例如, 如果你运行 `build`, 它会先执行 `aux` 和 `script`, 然后再执行 `build`, 从而确保所有依赖都已生成. 你也可以直接运行 `aux` 或 `script`, 以生成辅助文件和脚本, 而不进行构建或仿真.

## 如何配置项目

一个最简单的项目结构如下:

```toml
name = "Example testbench"
id = "example"

[directories]
sources = ["sim/", "src/modules/"]
vvp = "build/vvp"
vcd = "build/vcd"

[[simulation]]
id = "tb_example"
top-symbol = "tb_example"
timescale = "1ns/1ps"
vvp = "tb_example.vvp"
vcd = "tb_example.vcd"
```

`[directories]` 中的产物目录 `vvp`、`vcd`、`synthesis`、`implementation`、`bitstream` 使用单个非空字符串，例如 `vvp = "build/vvp"`; 原来的数组写法会报配置错误。输入目录 `sources`、`constraints` 继续使用字符串数组，`constraints` 当前要求一个目录。所有路径以项目根目录为基准。

指定 `top-symbol` 之后, 构建系统会在源码目录下搜索含有 `top-symbol` 的模块, 将其作为仿真的顶层模块,
并自动导入依赖模块所在的源文件并编排顺序. 这需要你的源码(`.v`文件)含有对应的元数据描述文件(`.toml`文件).

一个典型的源码结构是这样的:

```
buildsys/
sim/
    tb_example.v
    tb_example.toml
src/
    modules/
        module1.v
        module1.toml
        module2.v
        module2.toml
```

源码对应的 `.toml` 文件中, 需要描述该源码含有的模块与所依赖的模块, 这由 `module.export` 和 `module.import` 字段来描述. 例如, `tb_example.toml` 可以这样写:

```toml
[[module.export]]
name = "tb_example"

[[module.import]]
name = "module1"
```

而 `module1.toml` 可以这样写:

```toml
[[module.export]]
name = "module1"

[[module.import]]
name = "module2"
```

以此类推...
将来计划让构建系统能够自动扫描源码目录下的 `.v` 文件并为其生成对应的 `.toml` 文件.

## FPGA 综合, 实现, 比特流生成与烧录

需要在 `configuration.toml` 中配置 FPGA 和程序, 例如:

```toml
[[fpga]]
id = "ego1"
part = "xc7a35tcsg324-1"

[[program]]
id = "driver7seg"
fpga = "ego1"
top-symbol = "Driver7Seg"
synthesis = "driver7seg.json"
implementation = "driver7seg.fasm"
bitstream = "driver7seg.bit"
constraints = "xilinx.xdc"
```

此外, 程序还需要 `[directories]` 配置 `constraints` 的单元素目录数组，以及 `synthesis`、`implementation`、`bitstream` 的目录字符串, 完整示例见 `examples/ego1/configuration.toml`.

第一次公共配置校验成功后, configure 会为每个 FPGA 创建 `build/fpga/<fpga-id>.toml`（权限 `0600`）, 并提示用户自行填写. 比如 `build/fpga/ego1.toml`:

```toml
# 必填: Project X-Ray 数据库目录; 相对路径以项目根目录为基准, 也支持绝对路径.
xray-database = ""

# 可选: 空列表使用 PATH; 每项只查找目录本身及其 bin/.
toolchain-root = []

# FPGA 构建必填：Python 模块搜索目录列表。
PYTHONPATH = []
```

`toolchain-root` 是路径列表, 可写绝对路径、`~` 或相对项目根目录的路径. 例如:

```toml
toolchain-root = ["FIRST_PATH_TO_ROOT", "SECOND_PATH_TO_ROOT"]
```

构建系统创建的脚本将按照列表顺序把每项的 `ROOT`、`ROOT/bin/` 加入 `PATH`;

`PYTHONPATH` 必须在本地 `build/fpga/<fpga-id>.toml` 中显式提供非空目录列表，支持绝对路径、`~` 和相对项目根目录的路径。例如：

```toml
PYTHONPATH = ["~/opt/fpga/ego1/src/prjxray"]
```

脚本按列表顺序设置模块搜索路径，并保留原有 `PYTHONPATH`；执行前检查目录存在。系统不再从 `toolchain-root` 推导 Python 模块目录。省略或填写 `[]` 时可以生成辅助文件和脚本、仿真及清理，但 FPGA 构建会提示填写；直接执行 `jobs.sh` 也会校验。已有比特流的烧录不要求填写数据库或 `PYTHONPATH`。填写后重新执行目标命令或 `script` 刷新脚本。

数据库或 `PYTHONPATH` 未填写时, `aux`、`script`、仿真和清理仍可执行; 而 `synthesis`、`implementation`、`bitstream` 在调用工具前报出对应本地文件的位置. 已有比特流的 `program` 不要求数据库或 `PYTHONPATH`, 但仍必须显式指定 protocol. 填好设置后重新执行目标命令或 `script` 刷新脚本; 之前生成的 FPGA 构建脚本也会拒绝缺少数据库或 `PYTHONPATH` 的流程, 并提示重新生成.

```sh
./buildsys script                         # 首次生成本地配置模板和任务脚本
# 编辑 build/fpga/ego1.toml
./buildsys synthesis driver7seg
./buildsys implementation driver7seg
./buildsys bitstream driver7seg
./buildsys program driver7seg --protocol ft2232
```

## Features

 - 一个统一的构建系统, 支持仿真, 综合, 实现, 比特流生成和烧录.
 - 支持 Icarus Verilog 仿真器.
 - 支持 yosys + nextpnr + fasm2frames + xc7frames2bit 的 FPGA 工具链.
 - 支持 Bash Tab 补全功能, 可以通过 Tab 键补全命令和目标.
 - `compact_json.py`: 压缩 yosys 生成的 JSON 文件, 以减少磁盘占用和提高解析速度.
