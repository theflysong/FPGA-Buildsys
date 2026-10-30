# FPGA Buildsystem

一个针对 FPGA 项目的构建系统, 基于 python 3.11+. 支持仿真, 综合, 实现, 生成比特流和烧录. 支持 Icarus Verilog 仿真器, 以及 Yosys 和 Vivado 两种 FPGA 工具链.

## How to use

该项目要求 Python 3.11+, 前置库见 requirements.txt.
要使用该系统, 请将仓库克隆到你的项目目录的子目录中.

使用 Vivado 时, 将其加入 PATH; `xpr` 导出还需要先初始化 buildsys 自己的虚拟环境:

```sh
./buildsys init-venv
```

`init-venv` 会在 `main.py` 所在的 buildsys 目录创建 `.venv/`, 并在其中安装 `requirements.txt` 的 `pytcl-eda`. 之后 `buildsys`、`buildsys.sh` 和 `buildsys.bat` 检测到该环境时会自动激活并使用其中的 Python; 没有该目录时仍使用系统 Python.

## 运行示例

先为项目选择工具链, 选择会保存到项目根目录的 `.buildsys/toolchain.json`:

```sh
./buildsys toolchain yosys
./buildsys toolchain          # 查看当前选择
./buildsys script
```

也可以使用 `python3 main.py --project <项目目录> toolchain yosys`。
`toolchain` 命令省略 `--project` 时使用当前目录；通过安装的入口调用时使用入口对应的项目目录。
状态文件格式为 `{"name": "yosys"}`，也可选择 `vivado`。未选择时查询返回非零状态并提示选择命令。
选择不依赖 `configuration.toml`、已安装的 FPGA 工具或许可证。

`auxiliary`、`script` 必须先选择任意一种工具链；
`synthesis`、`implementation`、`bitstream`、`program` 根据当前选择路由到对应工具链：

| 通用命令 | `toolchain yosys` | `toolchain vivado` |
| --- | --- | --- |
| `synthesis` | `yosys-synthesis` | `xpr-synthesis` |
| `implementation` | `yosys-implementation` | `xpr-implementation` |
| `bitstream` | `yosys-bitstream` | `xpr-bitstream` |
| `program` | `yosys-program` | `xpr-program` |

Yosys 路由接收 `[[project]]` 的 id，Vivado 路由接收 `[[xpr]]` 的 id。
`program` 的参数和帮助也按工具链切换：Yosys 必须指定 `--protocol`，可用 `--busdev-num` 或 `--ftdi-serial`；
Vivado 使用 `--hw-server` 和 `--device`，默认 Hardware Server 为 `localhost:3121`。
显式的 `yosys-*` 命令必须选择 `yosys`；
`xpr` 和全部 `xpr-*` 命令必须选择 `vivado`。
未选择、状态文件损坏或所选工具链不匹配时，在配置和生成文件之前返回错误，提示重新选择。
`build`、`simulate`、`model`、`clean`、`cleandist`、`init`、`init-venv`、`install`、`completion` 及帮助不要求选择。

切换时再次执行 `toolchain yosys` 或 `toolchain vivado`，只更新当前选择，不删除已有产物。
`cleandist` 保留工具链选择。新生成的 Yosys FPGA 任务脚本在直接调用时也检查选择；升级后请重新生成旧脚本。
将 `.buildsys/` 加入项目的 `.gitignore`，模板项目已默认忽略。

专属任务分别位于 `task/yosys/` 和 `task/vivado/`，通用配置、源码模型、仿真和清理入口保留在 `task/`。
选择 `yosys` 时，`auxiliary/script` 生成原有仿真及 FPGA 任务；选择 `vivado` 时，这两个命令只生成通用仿真任务，
不要求 Yosys 的综合/实现/bitstream 配置，也不创建 FPGA 本地设置。Vivado 工程通过 `xpr` 导出，阶段可通过通用命令或 `xpr-*` 执行。
重新运行 `script` 或阶段命令生成的 `jobs.sh` 同样支持通用阶段路由及 `yosys-*` 名称。
直接执行已有的 `build/jobs/<id>/*.sh` 仍是对应的 Yosys 任务，并检查当前工具链。

你可以通过 python3 脚本运行该构建系统, 如:

```sh
python3 main.py --project [path-to-your-project] toolchain yosys
python3 main.py --project [path-to-your-project] model
python3 main.py --project [path-to-your-project] auxiliary
python3 main.py --project [path-to-your-project] script
python3 main.py --project [path-to-your-project] build [target]
python3 main.py --project [path-to-your-project] simulate [target]
```

也可以将快捷入口安装到已有的项目目录中, 这样可以直接使用 `./buildsys` 来运行构建系统:

```sh
python3 main.py install buildsys [path-to-your-project]
cd [path-to-your-project]
./buildsys toolchain yosys
./buildsys script
./buildsys.sh auxiliary
./buildsys build [target]
./buildsys simulate [target]
```

安装命令同时生成 `buildsys`、`buildsys.sh` 和 `buildsys.bat`. 三个入口都会将参数转发给 `main.py`, 并自动将脚本所在目录作为 `--project` 参数传递, 因此可以跨目录调用. 入口会根据 `main.py` 的位置选择 buildsys 的 `.venv`; 没有该环境时 Bash 使用 PATH 中的 `python3`, Windows 批处理入口使用 PATH 中的 `python`.

Windows 命令提示符中可使用:

```bat
python main.py install buildsys C:\path\to\project
C:\path\to\project\buildsys.bat toolchain vivado
C:\path\to\project\buildsys.bat xpr driver7seg
C:\path\to\project\buildsys.bat xpr-simulation driver7seg
C:\path\to\project\buildsys.bat xpr-bitstream driver7seg
```

`auxiliary` 命令和 `build/auxiliary/` 目录使用完整名称, 避免 Windows 保留名限制. 已有项目升级后请重新运行 `script` 生成新路径的任务文件. `.bat` 提供 Windows 命令入口; 执行原有 Bash 构建与清理任务仍需要 Bash 及相应工具环境. `xpr` 和 `xpr-*` 直接通过 Python 调用 Vivado, 不需要 Bash 或 WSL.

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

此外, 还可以安装 Bash 或 PowerShell 的 Tab 补全功能:

```text
./buildsys install completion [directory] [--terminal=bash|powershell]
```

`--terminal` 在 Windows 默认是 `powershell`, Linux 及其他非 Windows 平台默认是 `bash`;
也接受 `--terminal powershell` 写法. 该参数仅用于 `install completion`.

Bash 默认安装到 `/usr/share/bash-completion/completions`, 写入系统目录通常需要 `sudo`;
也可指定已有的 Bash 补全搜索目录:

```sh
sudo python3 main.py install completion --terminal=bash
# 或者指定安装目录
sudo python3 main.py install completion /usr/share/bash-completion/completions --terminal=bash
```

安装后打开新终端, 或在当前终端执行:

```sh
source /usr/share/bash-completion/completions/buildsys
```

PowerShell 中可使用（Windows 默认选择 PowerShell）:

```powershell
./buildsys install completion
# 显式选择, 或安装到已有目录
./buildsys install completion --terminal=powershell
./buildsys install completion 'C:\my completions' --terminal=powershell
```

安装程序通过 PATH 检测 Windows PowerShell 5.1 (`powershell`) 和 PowerShell 7 (`pwsh`),
为所有检测到的版本自动配置当前用户的 `$PROFILE.CurrentUserAllHosts`.
默认补全脚本位于各 profile 所在目录的 `completions/buildsys.ps1`, 目录不存在时自动创建;
指定安装目录时, 各版本 profile 都加载该目录中的 `buildsys.ps1`.
重复安装会更新标记块而不重复添加, 保留原有 profile 内容和编码; 新文件使用 UTF-8 BOM.
安装后打开新终端, 或执行安装程序输出的 `. '.../buildsys.ps1'` 命令在当前会话加载.
支持 `buildsys`、`buildsys.bat`、`buildsys.sh` 及相对或绝对路径调用. 安装和补全查询不需要 Bash 或 WSL.
PowerShell 补全查询在与交互终端隔离的子进程中执行, 避免批处理激活虚拟环境时切换代码页影响当前终端显示.

两种终端共享 Python 候选生成逻辑, 按 Tab 时通过 `buildsys completion` 查询.
普通接口 `completion -- <words...>` 逐行输出候选, 最后一个参数是当前输入前缀;
PowerShell 使用 `completion --json`, 从标准输入读取字符串数组并输出 JSON 候选数组, 保留空参数及中文路径.
`install completion` 还补全 `--terminal` 及 `bash`、`powershell` 两个取值.

仿真 id 合并 `build/auxiliary/*.f` 与 `configuration.toml` 中的 simulation id, 设计 id 合并 `build/auxiliary/*.ys` 与配置中的 project id, 并去重. `xpr` 命令仅补全 `[[xpr]]` 的 id. 配置中的 id 通过独立的 `completion_ids.py` 只读获取, 不要求目标的其他字段完整. 因此首次构建前、仅构建部分目标后、全项目 `cleandist` 后也能补全所有已配置目标. 删除或改名后仍可能补全旧辅助文件的 id, 可先清除旧辅助文件.

`toolchain` 补全 `yosys`、`vivado`，无需已有选择。通用阶段命令按当前工具链补全 project 或 xpr id，`program` 补全对应工具链的选项。
未选择工具链或选择文件损坏时，通用阶段的补全仍提供 Yosys 候选；补全不会创建或修改选择文件。
`yosys-*` 始终补全 project id，`xpr-*` 始终补全 `[[xpr]]` 的 id；`xpr-simulation <xpr-id>` 后只补全该 xpr 引用的 simulation id，`xpr-program` 补全 `--hw-server`、`--device`，不连接硬件。

补全不会执行 configure、生成文件、读取 FPGA 本地设置或探测 USB; 配置缺失或无效时静默跳过配置候选, 仍可使用已有辅助文件的 id. 跨目录调用快捷入口时仍读取该入口对应项目的配置.

## 构建流程

该构建系统的构建流程如下所示:

```
configure -> model -> auxiliary -> script ---|---> build -> simulate
                 |
                 |---> synthesis -> implementation -> bitstream -> program
```

指定中间环节的任意一个(除program)都会触发前置环节的执行. 例如, `build` 会先执行 `configure`、`model`、`auxiliary` 和 `script`, 再开始构建. `model` 可单独生成符号表和文件依赖图; `auxiliary` 继续生成编译器辅助文件, `script` 继续生成任务脚本. `xpr` 执行 `configure → model → xpr`, 清理、烧录和补全跳过 model. `xpr-*` 执行 `configure → Vivado Tcl`, 在 Tcl 中处理所需 run 依赖, 不触发 model 或工程导出.

指定目标时, 配置校验和文件生成按目标及命令阶段进行. 例如 `simulate tb_example` 不要求其他 project 的构建字段或 FPGA 本地设置正确; `yosys-synthesis coreprog` 不要求实现、约束或比特流配置完整. 通用阶段采用路由后命令的流程和配置要求，各命令要求如下:

| 命令 | 需要的配置 |
| --- | --- |
| `model` | 公共项目配置、源码目录及全部源码元数据; 无需任务构建字段或 FPGA 本地设置 |
| `build` / `simulate` | 当前 simulation、vvp/vcd 路径、顶层模块及其源码依赖 |
| `yosys-synthesis` | 当前 project 的顶层和源码依赖、综合输出、引用 FPGA 及本地构建设置 |
| `yosys-implementation` | 综合所需配置, 加实现输出和已有约束文件 |
| `yosys-bitstream` | 实现所需配置, 加 bitstream/frames 输出 |
| `yosys-program` | 已有 bitstream 的路径、FPGA 引用、可选工具路径、显式 protocol; 无需源码、约束、数据库或 PYTHONPATH |
| `xpr` | 当前 xpr 引用的 project、simulations、源码依赖、约束、FPGA part 和 xpr 输出目录 |
| `xpr-simulation` / `xpr-synthesis` / `xpr-implementation` / `xpr-bitstream` / `xpr-program` | 公共配置、所选 xpr 的 project/simulations 引用、`directories.xpr` 和已有 `.xpr`; 无需源码、约束、FPGA part 或本地设置；`xpr-program` 还需要有效 bitstream 和可用 Hardware Server |
| `clean` / `cleandist` | 所选目标的产物路径; 无需源码、约束或 FPGA 本地设置 |
| `auxiliary` / `script` | 已选择工具链、全部源码依赖；Yosys 校验全量仿真/FPGA 配置和本地设置格式，Vivado 校验通用仿真配置 |

所有项目命令仍要求公共配置的 TOML 语法、项目基本信息及 simulation/project 任务 id 合法且唯一. `[[xpr]]` 的 id 使用独立命名空间, 可以与 project id 相同; 导出时要求全部 xpr id 合法且唯一. model 阶段扫描全部源码元数据以建立符号索引, 因此元数据必须存在、格式正确且导出符号唯一; 未被当前目标引用的缺失 import 或依赖环不会阻塞该目标. `model` / `auxiliary` / `script` 会检查全部源码依赖, 可用于检查整个项目. 公开配置及源码验证通过后才初始化 FPGA 本地设置; 单独运行 `model` 不读取或创建这些设置.

每个源文件生成两份 JSON: `build/symbol/<hash>.json` 保存 `path`、`import`、`export`, `build/model/<hash>.json` 保存 `path`、`dependencies`、`closure`. `path` 及所有依赖路径均相对于 `configuration.toml` 所在目录, 使用 `/` 分隔; `<hash>` 是该源文件相对路径 UTF-8 字节的 SHA-256 完整十六进制值. `dependencies` 为去重的直接依赖, `closure` 为依赖优先排列的全部前置文件, 两者都不包含自身. 同文件导出的符号之间引用不会产生文件依赖.

`model` / `auxiliary` / `script` 更新全部模型并移除失效的哈希 JSON; 单目标构建和 xpr 仅更新所选目标可达文件的模型. 内容未变的 JSON 保留修改时间. `auxiliary` 仅生成 `.f`、`.ys`, 不再生成旧的项目级 `.map` / `.dep`; 已有旧文件可由全项目 `cleandist` 清除.

单目标命令只刷新当前阶段及其前置阶段的文件, 保留其他目标的模型、辅助文件和脚本. `jobs.sh` 仍列出全部任务 id, 但尚未生成脚本的任务会提示先运行对应的 buildsys 目标命令或全量 `script`. 项目级及各目标的清理脚本由全量 `script` 生成; CLI 清理使用临时脚本, 不需要预先生成任务脚本.

无目标的 `clean` / `cleandist` 校验全部目标的产物路径后才开始删除; 任一产物路径配置错误时不会删除文件. `clean` 和单目标 `cleandist` 保留共享模型; 全项目 `cleandist` 删除 `build/model/` 和 `build/symbol/`. FPGA 本地设置始终保留.

## 如何配置项目

一个最简单的项目结构如下:

```toml
name = "Example testbench"
id = "example"

[directories]
sources = ["src/modules/"]
simulation = ["sim/"]
vvp = "build/vvp"
vcd = "build/vcd"

[[simulation]]
id = "tb_example"
top-symbol = "tb_example"
timescale = "1ns/1ps"
vvp = "tb_example.vvp"
vcd = "tb_example.vcd"
```

`[directories]` 中的产物目录 `vvp`、`vcd`、`synthesis`、`implementation`、`bitstream` 使用单个非空字符串，例如 `vvp = "build/vvp"`; 原来的数组写法会报配置错误。输入目录 `sources`、可选的 `simulation`、`constraints` 使用字符串数组，`constraints` 当前要求一个目录。model 扫描 `sources` 与 `simulation` 中的 `.v` / `.sv`, 重叠路径去重。构建与仿真仍兼容将测试台目录列入 `sources` 的旧配置; Vivado 导出则按目录区分归属: `sources` 中的文件放入设计文件集, 显式列入 `simulation` 的目录用于仿真文件集（重叠时优先按 simulation 归类）。所有路径以项目根目录为基准。

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

需要在 `configuration.toml` 中用 `[[fpga]]` 配置器件、用 `[[project]]` 配置设计, 例如:

```toml
[[fpga]]
id = "ego1"
part = "xc7a35tcsg324-1"

[[project]]
id = "driver7seg"
fpga = "ego1"
top-symbol = "Driver7Seg"
synthesis = "driver7seg.json"
implementation = "driver7seg.fasm"
bitstream = "driver7seg.bit"
constraints = "xilinx.xdc"
```

旧的 `[[program]]` 必须改为 `[[project]]`; 烧录命令仍为 `buildsys program <project-id>`. 设计还需要 `[directories]` 配置 `constraints` 的单元素目录数组，以及 `synthesis`、`implementation`、`bitstream` 的目录字符串, 完整示例见 `examples/ego1/configuration.toml`.

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

数据库或 `PYTHONPATH` 未填写时, `auxiliary`、`script`、仿真和清理仍可执行; 而 `yosys-synthesis`、`yosys-implementation`、`yosys-bitstream` 在调用工具前报出对应本地文件的位置. 已有比特流的 `yosys-program` 不要求数据库或 `PYTHONPATH`, 但仍必须显式指定 protocol. 烧录时本地文件不存在则使用 PATH; 存在时要求 TOML 可解析, 仅校验并应用 `toolchain-root`, 不设置或检查 PYTHONPATH 目录. 填好设置后重新执行目标命令或 `script` 刷新脚本; 之前生成的 FPGA 构建脚本也会拒绝缺少数据库或 `PYTHONPATH` 的流程, 并提示重新生成.

```sh
./buildsys toolchain yosys
./buildsys script                         # 首次生成本地配置模板和任务脚本
# 编辑 build/fpga/ego1.toml
./buildsys synthesis driver7seg
./buildsys implementation driver7seg
./buildsys bitstream driver7seg
./buildsys program driver7seg --protocol ft2232
# 显式命令等价，例如 ./buildsys yosys-implementation driver7seg
```

## Vivado 工程导出

在 `[directories]` 中配置输出目录, 并用独立的 `[[xpr]]` 声明要导出的工程:

```toml
[directories]
xpr = "build/xpr"

[[xpr]]
id = "driver7seg_vivado"
project = "driver7seg"
simulations = ["bin2bcd", "bcd2seg7", "tb_driver7seg"]
```

```sh
./buildsys toolchain vivado
./buildsys xpr driver7seg_vivado  # 导出指定 xpr
./buildsys xpr                   # 导出所有 [[xpr]]
```

`xpr [xpr-id]` 通过 `pytcl-eda` 启动 Vivado batch 模式, 生成 `directories.xpr/<xpr-id>/<xpr-id>.xpr`. `project` 必须引用一个 `[[project]]` 的 id. 设计顶层与依赖、所选仿真引用的设计依赖统一加入 `sources_1`; 设计引用 `directories.simulation` 中的文件会报配置错误. XDC 约束加入 `constrs_1`, 并设置 FPGA part 和设计顶层模块.

每个 `simulations` id 必须引用一个 `[[simulation]]`, 创建独立的 `sim_<simulation-id>` 文件集, 只加入其依赖闭包中来自 `directories.simulation` 的文件. 来自 `directories.sources` 的模块保留在设计文件集, 通过 `SOURCE_SET = sources_1` 提供给仿真. 未被任何所选仿真引用的设计文件设置 `USED_IN_SIMULATION = false`, 例如仅用于板上设计的 `main.v`. Vivado 的这个用途标记由所有仿真共享, 因此多个仿真可见的设计模块取其依赖并集. 同时设置各仿真的顶层和 `xsim.elaborate.timescale`.

列表中第一个仿真设为当前仿真, 随后移除默认 `sim_1`; 省略 `simulations` 或使用 `[]` 时仅导出设计, 并清空默认仿真的 `SOURCE_SET`. 同一个 project 可以被多个 xpr 引用.

导出不启动综合、实现或仿真. 重复导出会重新生成同名 Vivado 工程. Windows 中可使用 `buildsys.bat xpr [xpr-id]`.

导出后可以直接在已有工程中运行 Vivado 阶段。下面五个命令只打开已有的
`.xpr`, 不会重新导出或覆盖工程；工程不存在时会提示先执行 `xpr`:

```bat
buildsys.bat xpr-simulation driver7seg_vivado [simulation-id]
buildsys.bat xpr-synthesis driver7seg_vivado
buildsys.bat xpr-implementation driver7seg_vivado
buildsys.bat xpr-bitstream driver7seg_vivado
buildsys.bat xpr-program driver7seg_vivado [--hw-server localhost:3121] [--device "xc7*"]
```

选择 `vivado` 后，也可以使用通用命令，目标仍为 xpr id：

```bat
buildsys.bat implementation driver7seg_vivado
buildsys.bat bitstream driver7seg_vivado
buildsys.bat program driver7seg_vivado --hw-server localhost:3121 --device "xc7*"
```

省略 simulation id 时使用所选 xpr 配置中第一个仿真, 指定 id 必须属于该 xpr。
仿真使用 `sim_<id>` 文件集, 设置运行时间为 `all`, 等待测试台 `$finish` 或所有事件结束后关闭仿真。
波形 `.wdb` 和仿真日志保留在工程的 `.sim` 目录。Vivado 进程使用 `-mode batch`;
`launch_simulation` 使用兼容 Vivado 2018.3 的 `-mode behavioral`, 因为该版本不接受仿真模式 `batch`。

综合、实现和 bitstream 使用默认 `synth_1`、`impl_1` run。实现先确保综合成功,
bitstream 先确保综合和实现成功, 再执行 `write_bitstream`。通过 run 的状态、进度和
`NEEDS_REFRESH` 判断是否可复用; 失败、过期或不完整的 run 先 reset 再运行并等待完成。
bitstream 还会检查 `PROGRAM.FILE` 或 run 目录内的 `.bit` 文件, 文件丢失时重新生成。
`.runs`、`.sim`、日志和 bitstream 保留在 XPR 工程目录,
不会写入配置中原有的 synthesis/implementation/bitstream 输出路径。

五个阶段命令始终打开已有工程, 配置变更后需显式执行 `xpr <xpr-id>` 重新导出。
阶段 Tcl 脚本、日志和 journal 保存在工程目录的 `.buildsys/` 下, 例如
`.buildsys/synthesis.log`。Tcl 错误、Vivado 错误日志、run 失败或进程异常均返回非零状态,
保留中间产物供检查; 命令默认等待执行完成, 不启动 GUI。

`xpr-program` 只消费已有 bitstream，不会自动生成它；默认连接
`localhost:3121`，`--hw-server` 可指定远程地址, `--device` 按设备名称 glob 选择首个匹配器件,
省略时选择首个器件。没有有效 bitstream、连接失败、没有硬件、设备名称无匹配或编程失败时返回错误。
它使用 Vivado Hardware Manager Tcl, 在 Vivado 2018.3 中使用旧名 `open_hw` / `close_hw`;
现有 openFPGALoader 的 `program` 命令保持不变。自动测试仅模拟硬件, 实际烧录需要连接 FPGA 手工验收。

Windows 下请先运行 Vivado 的 `settings64.bat`, 或将安装目录的 `bin` 加入当前终端的 `PATH`, 然后执行 `buildsys.bat xpr`. 构建系统通过 `cmd.exe` 启动 `vivado.bat`; Vivado 子进程会优先使用运行 buildsys 的 Python 所在目录, 并跳过 Microsoft Store 的应用别名目录, 避免 Tcl 桥接选中无法执行的 `python3` 别名.

导出要求 `directories.sources`、`directories.constraints`、`directories.xpr`、引用 project 的 `fpga` / `top-symbol` / `constraints`、对应 FPGA 的 `part`, 以及引用 simulation 的 `top-symbol` / `timescale`; 不要求 yosys、Icarus 的产物路径或 FPGA 本地数据库、PYTHONPATH 配置. 省略目标时, 所有 xpr 及其引用均校验通过后才开始调用 Vivado. 指定目标时仅校验其引用的设计和仿真, 不要求其他目标的字段完整. `auxiliary` 和 `script` 不会自动导出 Vivado 工程.

## Features

 - 一个统一的构建系统, 支持仿真, 综合, 实现, 比特流生成和烧录.
 - 支持 Icarus Verilog 仿真器.
 - 支持 yosys + nextpnr + fasm2frames + xc7frames2bit 的 FPGA 工具链.
 - 支持 Vivado XPR 工程导出、仿真、综合、实现、比特流生成和烧录；使用 `toolchain yosys|vivado` 按项目切换工具链.
 - 支持 Bash Tab 补全功能, 可以通过 Tab 键补全命令和目标.
 - `compact_json.py`: 压缩 yosys 生成的 JSON 文件, 以减少磁盘占用和提高解析速度.
