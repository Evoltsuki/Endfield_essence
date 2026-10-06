# 基质自动识别工具 v4.0

面向《明日方舟：终末地》的 Windows 基质识别与标记工具。通过窗口截图、OCR 和武器词条匹配，自动执行锁定或废弃标记，不执行分解。

**作者：洁柔厨 · 本工具免费 · 群号：1006580737**

## 功能

- 识别当前页面的基质网格，逐件读取词条，完成后自动翻页。
- 按武器词条匹配毕业基质，支持潜力保留规则及毕业锁定数量上限。
- 支持跳过已标记基质、识别紫色基质和排除五星武器锁定。
- 支持编辑武器数据、维护 OCR 错字纠正、查看已保存的基质等级记录。
- 对选中状态、翻页重叠区域和标记结果进行校验；无法可靠识别时跳过标记或停止扫描。
- 自动记录运行日志、逐件结果、阶段耗时及异常信息，保留最近 5 次运行。

## 运行

### 使用发布包

解压发布包，保留可执行文件旁的 `data/` 目录，运行 `Endfield_essence_v4.0.exe`。发布包自带运行依赖，无需安装 Python。

打开游戏的基质背包，设置过滤条件和锁定规则后开始扫描。扫描期间保持游戏前台，避免操作鼠标；按 **B** 或点击停止按钮中止。程序需要管理员权限，由 Windows UAC 提示。

### 从源码运行

运行环境：**Windows 10/11、Python 3.12**。

```powershell
.\start.cmd
```

启动器会定位项目目录、创建或检查 `.venv`，并按 `requirements.txt` 补齐依赖。仅检查环境：

```powershell
.\start.cmd -Mode check
```

也可以手动配置环境：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

## 技术实现

主要技术栈为 Python、Tkinter、OpenCV、RapidOCR / ONNX Runtime、Windows Graphics Capture 和 Win32 API。

### 扫描流程

1. **窗口与截图**：定位游戏窗口，根据分辨率计算坐标布局，获取新截图并检查画面稳定性。
2. **网格识别**：从整页画面构建实际行列，逐件点击；目标选中框需要在连续两张新帧中确认。
3. **词条识别**：优先按相对区域批量识别三行名称和等级；区域、格式或置信度不满足条件时退回完整文字检测流程。
4. **规则判定**：先匹配武器毕业词条，再判断潜力条件及保留数量，生成锁定或废弃操作。
5. **标记确认**：操作后读取新帧确认状态，确认失败时停止，不自动重复点击切换按钮。
6. **翻页对齐**：通过相邻页面的重叠行确定推进量，按全局行列跳过已处理格子。

同名词条或相似缩略图不会直接视为同一件物品。满足唯一性条件时保留一行重叠，否则保留两行；无法确定页面对应关系时停止扫描。

### 潜力规则

规则由 `core/potential.py` 处理，在“锁定基质规则”中配置。金色与紫色分别设置条件，同品质中任意一条启用规则满足即判定为潜力。

| 字段 | 含义 |
| --- | --- |
| `skill_names` | 特殊词条名称列表；为空时使用两字词条作为特殊词条 |
| `enabled` | 是否启用当前条件 |
| `total` | 三条词条的总等级下限，`0` 表示不限 |
| `level` | 特殊词条必须等于的等级，`0` 表示不限 |

每条潜力条件都要求存在特殊词条。关闭“保留潜力基质”后，潜力条件不参与保留判定。

## 项目结构

```text
main.py                     程序入口、工作目录与异常处理
start.cmd                   Windows 一键启动入口
requirements.txt            运行依赖及版本约束
core/
  scanner.py                扫描流程、规则执行与标记确认
  analyzer.py               图像分析、OCR 解析与武器匹配
  ocr_regions.py            词条区域提取
  page_grid.py              网格建模、翻页规划与页面对齐
  selection.py              目标选中状态识别
  frame_wait.py             画面稳定性判断
  potential.py              可配置潜力规则
  layout.py                 窗口坐标布局
  update.py                 武器数据更新
device/                     游戏窗口、截图与输入控制
gui/                        主界面、编辑窗口、输出展示与主题
utils/                      配置读写、日志保留、系统辅助与版本信息
data/                       武器词条库与 OCR 纠错数据
img/                        图标和图像匹配模板
scripts/
  start.ps1                 环境准备与启动编排
  check_dependencies.py     依赖版本检查
  build.py                  PyInstaller 构建与发布包生成
  diagnostics/              扫描、翻页与选中状态诊断
tests/                      自动化回归与测试素材
```

## 数据与日志

| 文件 | 用途 |
| --- | --- |
| `data/weapon_data.csv` | 武器、星级、毕业词条和屏蔽状态 |
| `data/Jiucuo.json` | OCR 错字纠正规则 |
| `data/config.json` | 过滤条件、锁定规则和窗口状态，运行时生成 |
| `data/best_records.json` | 各武器已保存的词条总等级记录，运行时生成 |

个人配置与等级记录不纳入 Git，也不打入分发 ZIP。升级时可保留这两个文件；它们与可执行文件使用同一目录下的 `data/`。

界面显示简洁结果，详细诊断写入运行日志：

- `app.log`：启动环境、完整会话及异常堆栈。
- 每轮 `scan.log`：扫描过程、点击 / 选中 / OCR 耗时与校验信息。
- `results.jsonl`：逐件识别结果、原始 OCR 文本和置信度。
- `summary.json`：扫描配置、计数、耗时及结束状态。

日志按运行会话保留最近 5 次；仍被运行中程序占用的旧目录会延后清理。日志不会自动上传。反馈问题时，可通过“日志目录”获取对应扫描记录，并注明游戏分辨率、系统缩放及复现步骤。

## 开发与构建

运行回归测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

测试覆盖 OCR 解析、默认及自定义潜力规则、选中确认、页面对齐、停止流程、日志保留和 Tk 控件交互。模拟与截图测试不能替代不同分辨率下的游戏实测。

构建 Windows 发布包：

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\python.exe scripts/build.py
```

构建脚本使用 PyInstaller 生成单文件程序，打包 OCR 模型、图像模板及必要依赖，并在项目根目录输出版本目录和同名 ZIP。分发内容包括可执行文件、共享数据和使用说明。版本号统一维护在 `utils/version.py`。

可执行文件支持启动自检，只验证界面、OCR 模型及资源加载，不操作游戏：

```powershell
.\Endfield_essence_v4.0\Endfield_essence_v4.0.exe --self-check
```

## 实现边界

- OCR、选中状态或页面对齐存在歧义时，工具不会据此继续标记。
- 停止请求不会撤销已发送到游戏的操作；若在标记确认期间停止，最后一件的实际状态需人工检查。
- 毕业保留记录存储的是词条总等级，不是游戏物品的唯一标识。
- 游戏界面更新、分辨率和系统缩放变化可能影响模板匹配，需要重新验证。
