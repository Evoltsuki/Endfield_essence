# Endfield_essence

《明日方舟：终末地》的**基质自动识别工具**。基于模块化架构开发，集成了 MaaEnd 的分辨率适配逻辑与智能决策引擎。



## 🛠️ 核心功能

* **📐 全自动分辨率适配**
    * 采用 `MAA` 720p 基准坐标映射技术。
    * 自动识别游戏窗口尺寸并进行物理坐标缩放。
    * 支持范围：1080p、2k、4k 及各种非常规比例窗口。

* **🔍 轻量化 OCR 识别**
    * 基于 `RapidOCR` 引擎，极致精简。
    * 无需部署庞大的深度学习环境，即可实现精准的中文字符识别。

* **📸 后台遮挡识别**
    * 核心基于 `Windows BitBlt` 技术。
    * 只要游戏窗口不最小化，即便被其他窗口完全覆盖，依然能稳定抓取画面并执行逻辑。



## 环境要求

- Python 3.12

- Windows 10/11

  

## 安装步骤

```
# 克隆仓库
git clone [项目地址]
cd [项目目录]

# 安装依赖
pip install -r requirements.txt
```



## 使用方法

运行主程序：

```
python main.py
```



## 文件说明
```text
├── main.py             # 主程序
├── core/
│   ├── layout.py       # 物理坐标基准库与分辨率，取自MaaEnd
│   └── analyzer.py     # 图像预处理、OCR解析、模糊匹配决策
│   └── scanner.py      # 实时日志推送、逻辑调度
├── device/
│   └── controller.py   # 截图、DPI适配、模拟鼠标操作
├── gui/
│   ├── app.py          # 主操作界面
│   └── windows.py      # 词条编辑器、纠错字典
├── utils/
│   ├── data_manager.py # 配置文件读写
│   └── sys_helper.py   # DPI 适配、提权与路径处理
├── data/               # 数据库 (配置文件、武器词条表、纠错字典)
└── img/                # 资源库 (图标、状态判定模板图)