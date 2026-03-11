import os
import json
import csv
from tkinter import messagebox


class DataManager:
    def __init__(self):
        self.config_file = "data/config.json"
        self.csv_file = "data/weapon_data.csv"
        self.corrections_file = "data/Jiucuo.json"

        # 确保 data 目录存在，防止写入时报错
        os.makedirs("data", exist_ok=True)

        self.data = self.load_config()
        self.weapon_list = self.load_weapon_csv()
        self.corrections = self.load_corrections()

    def load_config(self):
        # 定义三个开关的默认值
        default_config = {
            "skip_marked": False,
            "ignore_5star": True,
            "debug_gold": False
        }

        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    conf = json.load(f)

                # 兼容机制：把已有的本地配置和默认配置合并
                # 如果本地 json 缺了某个新加的键，就补上默认值
                for k, v in default_config.items():
                    if k not in conf:
                        conf[k] = v
                return conf
            except Exception:
                pass

        # 如果文件不存在或读取失败，返回默认配置
        return default_config

    def save_config(self):
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"保存配置失败: {e}")

    def load_corrections(self):
        if os.path.exists(self.corrections_file):
            with open(self.corrections_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def load_weapon_csv(self):
        ws = []
        if not os.path.exists(self.csv_file):
            messagebox.showwarning("缺少必要文件", f"未检测到武器文件：{self.csv_file}\n请确保文件在程序根目录下！")
            return ws
        try:
            with open(self.csv_file, 'r', encoding='utf-8-sig') as f:
                r = csv.DictReader(f)
                if r.fieldnames and "武器" in r.fieldnames:
                    for row in r: ws.append({k.strip(): v.strip() for k, v in row.items() if k})
                else:
                    messagebox.showerror("文件格式错误", "CSV格式不正确")
        except Exception as e:
            messagebox.showerror("读取失败", str(e))
        return ws

    def save_corrections(self):
        with open(self.corrections_file, 'w', encoding='utf-8') as f:
            json.dump(self.corrections, f, ensure_ascii=False, indent=4)