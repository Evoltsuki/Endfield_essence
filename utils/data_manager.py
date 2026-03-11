import os
import json
import csv
from tkinter import messagebox


class DataManager:
    def __init__(self):
        self.config_file = "data/config.json"
        self.csv_file = "data/weapon_data.csv"
        self.corrections_file = "data/Jiucuo.json"

        self.data = self.load_config()
        self.weapon_list = self.load_weapon_csv()
        self.corrections = self.load_corrections()

    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                conf = json.load(open(self.config_file, 'r', encoding='utf-8'))
                # 兼容旧配置，如果没有这个键就补上默认值
                if "skip_marked" not in conf: conf["skip_marked"] = True
                return conf
            except:
                pass
        return {"speed": "0.2", "skip_marked": True}

    def save_config(self):
        # 确保保存当前 UI 上的开关状态
        json.dump(self.data, open(self.config_file, 'w', encoding='utf-8'), ensure_ascii=False, indent=4)

    def load_corrections(self):
        return json.load(open(self.corrections_file, 'r', encoding='utf-8')) if os.path.exists(
            self.corrections_file) else {}

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

    def save_config(self):
        json.dump(self.data, open(self.config_file, 'w', encoding='utf-8'), ensure_ascii=False, indent=4)

    def save_corrections(self):
        json.dump(self.corrections, open(self.corrections_file, 'w', encoding='utf-8'), ensure_ascii=False, indent=4)