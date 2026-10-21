# FPGA Buildsystem

一个针对 FPGA 项目的构建系统, 基于 python 3.11+. 支持仿真, 综合, 实现, 生成比特流和烧录. 目前支持 Icarus Verilog 仿真器和 yosys + nextpnr + fasm2frames + xc7frames2bit 的 FPGA 工具链. 未来计划支持更多的仿真器和 FPGA 工具链.

## How to use

该项目要求 Python 3.11+, 前置库见 requirements.txt.
要使用该系统, 请将仓库克隆到你的项目目录的子目录中.

使用 `xpr` 命令时, 先在当前 Python 环境安装 `requirements.txt` 中的 `pytcl-eda`, 并将 Vivado 加入 PATH. 例如在 Bash 中:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 运行示例

你可以通过 python3 脚本运行该构建系统, 如:

```sh
python3 main.py --project [path-to-your-project] auxiliary
python3 main.py --project [path-to-your-project] script
python3 main.py --project [path-to-your-project] build [target]
python3 main.py --project [path-to-your-project] simulate [target]
```

也可以将快捷入口安装到已有的项目目录中, 这样可以直接使用 `./buildsys` 来运行构建系统:

```sh
python3 main.py install buildsys [path-to-your-project]
cd [path-to-your-project]
./buildsys script
./buildsys.sh auxiliary
./buildsys build [target]
./buildsys simulate [target]
```

安装命令同时生成 `buildsys`、`buildsys.sh` 和 `buildsys.bat`. 三个入口都会将参数转发给 `main.py`, 并自动将脚本所在目录作为 `--project` 参数传递, 因此可以跨目录调用. Bash 入口使用 PATH 中的 `python3`, Windows 批处理入口使用 PATH 中的 `python`, 可先激活安装了依赖的虚拟环境.

Windows 命令提示符中可使用:

```bat
python main.py install buildsys C:\path\to\project
C:\path\to\project\buildsys.bat auxiliary
C:\path\to\project\buildsys.bat xpr driver7seg
```

`auxiliary` 命令和 `build/auxiliary/` 目录使用完整名称, 避免 Windows 保留名限制. 已有项目升级后请重新运行 `script` 生成新路径的任务文件. `.bat` 提供 Windows 命令入口; 执行原有 Bash 构建与清理任务仍需要 Bash 及相应工具环境, `xpr` 直接通过 Python 调用 Vivado.

在新建的空目录中安装入口后, 可以使用 `init` 创建模板项目:

```sh
mkdir my-project
python3 main.py install buildsys my-project
cd my-project
./buildsys init
./buildsys simulate example_simulation
```

`init` 接受仅包含 `buildsys`、`buildsys.sh`、`buildsys.bat` 三个入口的目录, 也兼容旧的两个 Bash 入口或仅有 `buildsys.bat` 的目录; 如有其他文件或目录（包括隐藏文件）, 会报错并保留现有内容。初始化会复制 `templates/template_project/` 中的配置、Verilog 源码及模块元数据, 保留已有入口脚本。也可使用 `python3 main.py --project [path-to-your-project] init`; 不指定 `--project` 时使用当前目录。

模板测试台 `tbSimulation` 从仿真时间 0 开始依次读取 `Hello,World!`, 每隔 500 ms 切换到下一个地址, 每个字符保持 500 ms, 在 6 秒仿真时间后结束。连续相同字符的数据值保持不变。运行仿真需要 `iverilog` 和 `vvp`, 波形输出到 `build/sim/example.vcd`。这里的时间是仿真时间。

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

按 Tab 时, 补全入口调用 `buildsys completion`. 仿真 id 合并 `build/auxiliary/*.f` 与 `configuration.toml` 中的 simulation id, 程序 id 合并 `build/auxiliary/*.ys` 与配置中的 program id, 并去重. 配置中的 id 通过独立的 `completion_ids.py` 只读获取, 不要求目标的其他字段完整. 因此首次构建前、仅构建部分目标后、全项目 `cleandist` 后也能补全所有已配置目标. 删除或改名后仍可能补全旧辅助文件的 id, 可先清除旧辅助文件.

补全不会执行 configure、生成文件、读取 FPGA 本地设置或探测 USB; 配置缺失或无效时静默跳过配置候选, 仍可使用已有辅助文件的 id. 跨目录调用快捷入口时仍读取该入口对应项目的配置.

## 构建流程

该构建系统的构建流程如下所示:

```
auxiliary -> script ---|---> build -> simulate
                 |
                 |---> synthesis -> implementation -> bitstream -> program
```

指定中间环节的任意一个(除program)都会触发前置环节的执行. 例如, 如果你运行 `build`, 它会先执行 `auxiliary` 和 `script`, 然后再执行 `build`, 从而确保所有依赖都已生成. 你也可以直接运行 `auxiliary` 或 `script`, 以生成辅助文件和脚本, 而不进行构建或仿真.

指定目标时, 配置校验和文件生成按目标及命令阶段进行. 例如 `simulate tb_example` 不要求其他 program 的构建字段或 FPGA 本地设置正确; `synthesis coreprog` 不要求实现、约束或比特流配置完整. 各命令要求如下:

| 命令 | 需要的配置 |
| --- | --- |
| `build` / `simulate` | 当前 simulation、vvp/vcd 路径、顶层模块及其源码依赖 |
| `synthesis` | 当前 program 的顶层和源码依赖、综合输出、引用 FPGA 及本地构建设置 |
| `implementation` | 综合所需配置, 加实现输出和已有约束文件 |
| `bitstream` | 实现所需配置, 加 bitstream/frames 输出 |
| `program` | 已有 bitstream 的路径、FPGA 引用、可选工具路径、显式 protocol; 无需源码、约束、数据库或 PYTHONPATH |
| `clean` / `cleandist` | 所选目标的产物路径; 无需源码、约束或 FPGA 本地设置 |
| `auxiliary` / `script` | 全量配置、全部源码依赖和 FPGA 本地设置格式 |

所有项目命令仍要求公共配置的 TOML 语法、项目基本信息及全部任务 id 合法且唯一. 构建相关命令还需要扫描全部源码元数据以建立模块索引, 因此元数据必须存在、格式正确且导出符号唯一; 未被当前目标引用的缺失 import 或依赖环不会阻塞该目标. `auxiliary` / `script` 会检查全部源码依赖, 可用于检查整个项目.

单目标命令只刷新当前阶段及其前置阶段的辅助文件和脚本, 不重写其他目标文件. 项目级 `.map` / `.dep` 仅由 `auxiliary` / `script` 刷新. `jobs.sh` 仍列出全部任务 id, 但尚未生成脚本的任务会提示先运行对应的 buildsys 目标命令或全量 `script`. 项目级及各目标的清理脚本由全量 `script` 生成; CLI 清理使用临时脚本, 不需要预先生成任务脚本.

无目标的 `clean` / `cleandist` 校验全部目标的产物路径后才开始删除; 任一产物路径配置错误时不会删除文件. FPGA 本地设置始终保留.

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

第一次所需公共配置校验成功后, `auxiliary` / `script` 会为每个 FPGA 创建 `build/fpga/<fpga-id>.toml`（权限 `0600`）; 单目标 FPGA 构建仅为引用的 FPGA 创建和读取本地文件. 仿真、烧录和清理不会创建这些文件. 比如 `build/fpga/ego1.toml`:

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

数据库或 `PYTHONPATH` 未填写时, `auxiliary`、`script`、仿真和清理仍可执行; 而 `synthesis`、`implementation`、`bitstream` 在调用工具前报出对应本地文件的位置. 已有比特流的 `program` 不要求数据库或 `PYTHONPATH`, 但仍必须显式指定 protocol. 烧录时本地文件不存在则使用 PATH; 存在时要求 TOML 可解析, 仅校验并应用 `toolchain-root`, 不设置或检查 PYTHONPATH 目录. 填好设置后重新执行目标命令或 `script` 刷新脚本; 之前生成的 FPGA 构建脚本也会拒绝缺少数据库或 `PYTHONPATH` 的流程, 并提示重新生成.

```sh
./buildsys script                         # 首次生成本地配置模板和任务脚本
# 编辑 build/fpga/ego1.toml
./buildsys synthesis driver7seg
./buildsys implementation driver7seg
./buildsys bitstream driver7seg
./buildsys program driver7seg --protocol ft2232
```

## Vivado 工程导出

在 `[directories]` 中添加单个目录字符串:

```toml
[directories]
xpr = "build/xpr"
```

```sh
./buildsys xpr driver7seg  # 导出一个 program
./buildsys xpr            # 为所有 program 分别导出工程
```

`xpr [program-id]` 通过 `pytcl-eda` 启动 Vivado batch 模式, 生成 `directories.xpr/<program-id>/<program-id>.xpr`. 工程引用该 program 的源码依赖闭包及 XDC 约束, 设置 FPGA part 和顶层模块, 不启动综合或实现. 重复导出会重新生成同名 Vivado 工程. Windows 中可使用 `buildsys.bat xpr [program-id]`.

导出仅要求 `directories.sources`、`directories.constraints`、`directories.xpr`、program 的 `fpga` / `top-symbol` / `constraints` 和对应 FPGA 的 `part`; 不要求 yosys 的产物路径或 FPGA 本地数据库、PYTHONPATH 配置. 省略目标时, 所有 program 均校验通过后才开始调用 Vivado. `auxiliary` 和 `script` 不会自动导出 Vivado 工程.

## Features

 - 一个统一的构建系统, 支持仿真, 综合, 实现, 比特流生成和烧录.
 - 支持 Icarus Verilog 仿真器.
 - 支持 yosys + nextpnr + fasm2frames + xc7frames2bit 的 FPGA 工具链.
 - 支持 Bash Tab 补全功能, 可以通过 Tab 键补全命令和目标.
 - `compact_json.py`: 压缩 yosys 生成的 JSON 文件, 以减少磁盘占用和提高解析速度.
