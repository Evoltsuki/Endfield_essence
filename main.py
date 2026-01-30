import os
import cv2
import numpy as np
import pydirectinput
import pyautogui
import mss
import time
import json
import csv
import re
import tkinter as tk
from tkinter import scrolledtext, messagebox
import ddddocr
from pynput import keyboard
import pygetwindow as gw
import ctypes
import threading
import difflib
import sys


# --- 权限与窗口管理逻辑 ---

def hide_console():
    """隐藏控制台窗口"""
    whnd = ctypes.windll.kernel32.GetConsoleWindow()
    if whnd != 0:
        # SW_HIDE = 0
        ctypes.windll.user32.ShowWindow(whnd, 0)
        ctypes.windll.kernel32.FreeConsole()


def run_as_admin():
    """强制请求管理员权限启动"""
    try:
        if ctypes.windll.shell32.IsUserAnAdmin():
            return True
        else:
            executable = sys.executable
            if executable.endswith("python.exe"):
                executable = executable.replace("python.exe", "pythonw.exe")

            ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, __file__, None, 1)
            return False
    except:
        return False


# 适配高分屏，防止坐标偏移
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except:
    ctypes.windll.user32.SetProcessDPIAware()

pydirectinput.PAUSE = 0.02
pyautogui.FAILSAFE = False


class Matrixassistant:
    def __init__(self, root):
        self.root = root
        self.root.title("毕业基质自动识别助手beta v0.2 -by洁柔厨")
        self.root.geometry("540x820")
        self.root.attributes("-topmost", True)

        # 初始化 ddddocr
        try:
            self.ocr = ddddocr.DdddOcr(show_ad=False, beta=True)
        except Exception as e:
            messagebox.showerror("OCR初始化失败", f"错误: {e}")

        self.config_file = "config.json"
        self.csv_file = "weapon_data.csv"
        self.running = False
        self.data = self.load_config()
        self.weapon_list = self.load_weapon_csv()

        # --- UI 顶部栏 ---
        top_frame = tk.Frame(root)
        top_frame.pack(fill="x", padx=10, pady=5)  # 加上 fill="x" 确保撑满宽度

        # 1. 左侧：配置状态
        self.top_status_var = tk.StringVar()
        self.update_config_status()
        tk.Label(top_frame, textvariable=self.top_status_var, font=("微软雅黑", 9), fg="green").pack(side="left")

        # 2. 右侧：群号和免费声明 (关键点：先 pack 右边的元素)
        group_info = "群号:1006580737 | 本工具完全免费"  # 这里换成你的群号
        tk.Label(top_frame, text=group_info, font=("微软雅黑", 9, "bold"), fg="#1565C0").pack(side="right")

        # 3. 中间：扫描速度（依然紧跟在左侧状态后面）
        initial_speed = self.data.get("speed", "0.3")
        self.speed_var = tk.StringVar(value=initial_speed)

        tk.Label(top_frame, text=" | 速度:", font=("微软雅黑", 9)).pack(side="left", padx=(5, 0))
        self.speed_entry = tk.Entry(top_frame, textvariable=self.speed_var, width=5)
        self.speed_entry.pack(side="left", padx=2)
        tk.Label(top_frame, text="秒", font=("微软雅黑", 9)).pack(side="left")

        # 运行按钮
        self.run_btn = tk.Button(root, text="▶ 开始自动扫描", command=self.start_thread,
                                 bg="#2E7D32", fg="white", font=("微软雅黑", 12, "bold"),
                                 width=15, height=1)
        self.run_btn.pack(pady=10)

        tk.Label(root, text="( 随时按 'B' 键强制停止扫描 )", font=("微软雅黑", 9), fg="#666666").pack()

        btn_frame = tk.Frame(root)
        btn_frame.pack(pady=5)
        tk.Button(btn_frame, text="框选识别区", command=self.set_roi, width=12).grid(row=0, column=0, padx=5, pady=5)
        tk.Button(btn_frame, text="校准网格", command=self.set_grid, width=12).grid(row=0, column=1, padx=5, pady=5)
        tk.Button(btn_frame, text="校准锁定键", command=self.set_lock, width=12).grid(row=1, column=0, padx=5, pady=5)
        tk.Button(btn_frame, text="重置配置", command=self.clear_config, width=12).grid(row=1, column=1, padx=5, pady=5)

        tk.Label(root, text="实时日志:", font=("微软雅黑", 11)).pack(anchor="w", padx=10)
        self.log_area = scrolledtext.ScrolledText(root, height=10, width=60, font=("微软雅黑", 12))
        self.log_area.pack(padx=10, pady=5)
        self.log_area.tag_config("black", foreground="black")
        self.log_area.tag_config("green", foreground="#2E7D32")
        self.log_area.tag_config("gold", foreground="#FF9800")
        self.log_area.tag_config("red", foreground="red")
        self.log_area.tag_config("blue", foreground="blue")

        tk.Label(root, text="已锁定列表:", font=("微软雅黑", 11, "bold")).pack(anchor="w", padx=10)
        self.lock_list_area = scrolledtext.ScrolledText(root, height=8, width=60, font=("微软雅黑", 12), bg="#F9F9F9")
        self.lock_list_area.pack(padx=10, pady=5, fill="x")
        self.lock_list_area.tag_config("red_text", foreground="red")
        self.lock_list_area.tag_config("gold_text", foreground="#FF9800")
        self.lock_list_area.tag_config("green_text", foreground="#2E7D32")
        self.lock_list_area.tag_config("black_text", foreground="black")

        self.kb = keyboard.Listener(on_press=self.on_press)
        self.kb.start()

    def is_already_locked(self, sct, lock_pos, win_rect):
        try:
            abs_x, abs_y = int(win_rect[0] + lock_pos[0]), int(win_rect[1] + lock_pos[1])
            lock_snap = np.array(sct.grab({"left": abs_x - 15, "top": abs_y - 15, "width": 30, "height": 30}))
            gray = cv2.cvtColor(cv2.cvtColor(lock_snap, cv2.COLOR_BGRA2BGR), cv2.COLOR_BGR2GRAY)
            return np.mean(gray) < 120
        except:
            return False

    def start_thread(self):
        if not all(self.data.get(k) is not None for k in ["roi", "grid", "lock"]):
            messagebox.showwarning("提示", "请先完成初始化配置")
            return
        self.save_config()
        self.log_area.delete('1.0', tk.END)
        self.lock_list_area.delete('1.0', tk.END)
        self.gui_log("[系统] 扫描启动，按 'B' 键可停止", "blue")
        self.running = True
        self.run_btn.config(state="disabled", text="正在扫描...")
        threading.Thread(target=self.run_task, daemon=True).start()

    def gui_log(self, message, color_tag="black"):
        self.log_area.insert(tk.END, message + "\n", color_tag)
        self.log_area.see(tk.END)

    def add_to_lock_list(self, w_name, attrs, pos, star):
        name_tag = "red_text" if "6" in star else "gold_text"
        self.lock_list_area.insert(tk.END, w_name + " ", name_tag)
        self.lock_list_area.insert(tk.END, attrs + " ", "green_text")
        self.lock_list_area.insert(tk.END, "坐标" + pos + "\n", "black_text")
        self.lock_list_area.see(tk.END)

    def on_press(self, key):
        try:
            if hasattr(key, 'char') and key.char == 'b':
                if self.running:
                    self.gui_log("[停止] 任务已中止", "red")
                    self.running = False
        except:
            pass

    def load_weapon_csv(self):
        weapons = []
        if os.path.exists(self.csv_file):
            try:
                # 使用 utf-8-sig 处理可能的 BOM 报头
                with open(self.csv_file, 'r', encoding='utf-8-sig') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        clean_row = {k.strip(): v.strip() for k, v in row.items() if k}
                        weapons.append(clean_row)
            except:
                pass
        return weapons

    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    conf = json.load(f)
                    if "speed" not in conf: conf["speed"] = "0.3"
                    return conf
            except:
                pass
        return {"roi": None, "grid": None, "lock": None, "speed": "0.3"}

    def save_config(self):
        try:
            self.data["speed"] = self.speed_var.get()
        except:
            self.data["speed"] = "0.3"
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=4)
        self.update_config_status()

    def update_config_status(self):
        ready = all(self.data.get(k) is not None for k in ["roi", "grid", "lock"])
        self.top_status_var.set("✅ 配置已载入" if ready else "❌ 配置未就绪")

    def clear_config(self):
        self.data = {"roi": None, "grid": None, "lock": None, "speed": "0.3"}
        if os.path.exists(self.config_file): os.remove(self.config_file)
        self.speed_var.set("0.3")
        self.update_config_status()

    def clean_text(self, raw_text):
        if not raw_text: return ""
        txt = re.sub(r'[^\u4e00-\u9fa5]', '', str(raw_text))
        # 内部纠错字典：针对游戏词条全方位防御
        char_map = {
            "玫": "攻", "政": "攻", "放": "攻", "公": "攻",
            "绞": "效", "校": "效", "郊": "效",
            "串": "率", "卒": "率", "律": "率",
            "辐": "力量", "撮": "力量", "帚": "量", "是": "量", "最": "量", "刀": "力", "品":"量",
            "厚": "源", "原": "源",
            "木": "术", "禾": "术",
            "美": "主", "王": "主", "玉": "主", "住": "主",
            "丑": "升", "开": "升", "井": "升",
            "装": "袭", "西": "袭", "席": "袭",
            "失": "生", "牛": "生",
            "谈": "识", "职": "识", "只": "识", "式": "识",
            "嘉": "幕", "寞": "幕", "慕": "幕", "暮": "幕",
            "统": "终", "中": "终", "钟": "终",
            "进": "迸", "拼": "迸", "并": "迸",
            "燥": "爆", "曝": "爆", "瀑": "爆",
            "令": "冷", "玲": "冷",
            "烈": "热", "列": "热",
            "田": "电", "由": "电",
            "沄": "法", "去": "法",
            "勿": "物", "匆": "物",
            "庄": "压", "厓": "压",
            "辽": "疗", "了": "疗",
            "冶": "治", "台": "治",
            "白": "自", "目": "自",
            "卬": "昂", "仰": "昂",
            "亏": "巧",
            "粹": "碎", "翠": "碎",
            "迫": "追", "椎": "追",
            "兹": "磁", "慈": "磁"
        }
        for wrong, right in char_map.items():
            txt = txt.replace(wrong, right)
        return txt

    def check_all_attributes(self, weapon, ocr_full_text):
        """
        核心判定逻辑：分段校验。
        确保 CSV 里的每一个非空词条都能在 OCR 结果中找到较高的局部相似度。
        这能有效解决“长词稀释短词”导致的误锁问题。
        """
        c1 = self.clean_text(weapon.get('毕业词条1', ''))
        c2 = self.clean_text(weapon.get('毕业词条2', ''))
        c3 = self.clean_text(weapon.get('毕业词条3', ''))

        targets = [t for t in [c1, c2, c3] if t]
        if not targets: return False

        # 1. 逐个词条进行局部相似度检查
        for t in targets:
            # 直接包含判定
            if t in ocr_full_text:
                continue

            # 模糊相似度判定 (针对单个词条)
            ratio = difflib.SequenceMatcher(None, t, ocr_full_text).ratio()

            # 动态阈值：长词（含“提升”）要求 0.45 即可，短词要求 0.6
            limit = 0.45 if len(t) > 2 else 0.60
            if ratio < limit:
                return False

        # 2. 整体拼接字符串再次校验比例，防止极端干扰
        full_target = "".join(targets)
        overall_ratio = difflib.SequenceMatcher(None, full_target, ocr_full_text).ratio()
        return overall_ratio >= 0.65

    def is_gold(self, cell_bgr):
        try:
            h, w = cell_bgr.shape[:2]
            strip = cell_bgr[int(h * 0.70):, :]
            hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
            lower_gold = np.array([15, 100, 100])
            upper_gold = np.array([35, 255, 255])
            mask = cv2.inRange(hsv, lower_gold, upper_gold)
            return (np.sum(mask > 0) / mask.size) > 0.06
        except:
            return False

    def run_task(self):
        roi, grid, lock = self.data["roi"], self.data["grid"], self.data["lock"]
        self.weapon_list = self.load_weapon_csv()
        with mss.mss() as sct:
            current_row = 0
            while self.running:
                try:
                    current_speed = float(self.speed_var.get())
                except:
                    current_speed = 0.3

                for c in range(9):
                    if not self.running: break
                    cur_win = self.get_game_rect()
                    if not cur_win: break
                    abs_x = int(cur_win[0] + grid["rx"] + c * grid["rdx"])
                    abs_y = int(cur_win[1] + grid["ry"] + min(current_row, 4) * grid["rdy"])

                    snap = np.array(sct.grab({"left": abs_x - 80, "top": abs_y - 70, "width": 140, "height": 140}))

                    if self.is_gold(cv2.cvtColor(snap, cv2.COLOR_BGRA2BGR)):
                        self.gui_log(f"--- 检查: {current_row + 1}-{c + 1} ---")
                        pydirectinput.click(abs_x, abs_y)
                        time.sleep(current_speed)

                        ocr_snap = np.array(sct.grab({"left": int(cur_win[0] + roi[0]), "top": int(cur_win[1] + roi[1]),
                                                      "width": int(roi[2]), "height": int(roi[3])}))

                        gray = cv2.cvtColor(cv2.cvtColor(ocr_snap, cv2.COLOR_BGRA2BGR), cv2.COLOR_BGR2GRAY)
                        scaled = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
                        _, binary = cv2.threshold(scaled, 150, 255, cv2.THRESH_BINARY_INV)

                        h, w = binary.shape
                        slice_h, full_txt, clean_list = h // 3, "", []
                        for i in range(3):
                            y_start = max(0, i * slice_h)
                            y_end = min(h, (i + 1) * slice_h)
                            part = binary[y_start:y_end, :]

                            _, img_bytes = cv2.imencode('.png', part)
                            res = self.ocr.classification(img_bytes.tobytes())
                            if res:
                                txt = self.clean_text(res)
                                if txt:
                                    clean_list.append(txt)
                                    full_txt += txt

                        if full_txt:
                            self.gui_log(f"识别结果: {'，'.join(clean_list)}", "green")

                            is_matched = False
                            for weapon in self.weapon_list:
                                if self.check_all_attributes(weapon, full_txt):
                                    self.gui_log("检测到毕业基质！", "gold")
                                    if self.is_already_locked(sct, lock, cur_win):
                                        self.gui_log("该基质已锁定，跳过点击", "red")
                                    else:
                                        pydirectinput.click(int(cur_win[0] + lock[0]), int(cur_win[1] + lock[1]))
                                        time.sleep(0.4)

                                    attrs_display = f"{weapon.get('毕业词条1', '')},{weapon.get('毕业词条2', '')},{weapon.get('毕业词条3', '')}"
                                    self.add_to_lock_list(weapon['武器'], attrs_display,
                                                          f"{current_row + 1}-{c + 1}", weapon.get('星级', '6'))
                                    is_matched = True
                                    break
                        else:
                            self.gui_log("-> 未读到有效词条")
                    else:
                        self.gui_log(f"非金色基质，停止扫描")
                        self.running = False
                        break

                if not self.running: break
                current_row += 1

                # 翻页对齐逻辑
                if current_row >= 5:
                    self.gui_log(f"[翻页] 第 {current_row} 行完成，执行滚动对齐...", "black")
                    drag_x = int(cur_win[0] + grid["rx"] + 4 * grid["rdx"])
                    drag_y = int(cur_win[1] + grid["ry"] + 4 * grid["rdy"])
                    pydirectinput.moveTo(drag_x, drag_y)
                    time.sleep(0.2)
                    move_dist = int(grid["rdy"] * 0.76)
                    pydirectinput.mouseDown()
                    time.sleep(0.15)
                    steps = 10
                    for s in range(steps):
                        pydirectinput.moveRel(0, -(move_dist // steps), relative=True)
                        time.sleep(0.01)
                    pydirectinput.mouseUp()
                    time.sleep(1.5)

        self.run_btn.config(state="normal", text="▶ 开始自动扫描")

    def get_game_rect(self):
        wins = gw.getWindowsWithTitle('Endfield')
        return (wins[0].left, wins[0].top) if wins else None

    def get_click(self, prompt, callback):
        rect = self.get_game_rect()
        with mss.mss() as sct:
            mon = sct.monitors[0]
            ov = tk.Toplevel(self.root)
            ov.attributes("-alpha", 0.3, "-topmost", True)
            ov.geometry(f"{mon['width']}x{mon['height']}+{mon['left']}+{mon['top']}")
            ov.overrideredirect(True)
            tk.Label(ov, text=prompt, font=("微软雅黑", 22, "bold"), fg="red", bg="white").pack(expand=True)
            ov.bind("<Button-1>", lambda e: [ov.destroy(), callback(e.x_root - (rect[0] if rect else 0),
                                                                    e.y_root - (rect[1] if rect else 0))])

    def set_roi(self):
        rect = self.get_game_rect()
        with mss.mss() as sct:
            img = np.array(sct.grab(sct.monitors[0]))
            roi = cv2.selectROI("SELECT_ROI", cv2.cvtColor(img, cv2.COLOR_BGRA2BGR), False)
            cv2.destroyAllWindows()
            if roi[2] > 0:
                self.data["roi"] = [int(roi[0] - (rect[0] if rect else 0)), int(roi[1] - (rect[1] if rect else 0)),
                                    int(roi[2]), int(roi[3])]
                self.save_config()

    def set_grid(self):
        def p3(rx, ry):
            p11, p12 = self.data["grid"]["p11"], self.data["grid"]["p12"]
            self.data["grid"] = {"rx": p11[0], "ry": p11[1], "rdx": p12[0] - p11[0], "rdy": ry - p11[1]}
            self.save_config()

        def p2(rx, ry): self.data["grid"]["p12"] = (rx, ry); self.get_click("点：(2, 1) 中心", p3)

        def p1(rx, ry): self.data["grid"] = {"p11": (rx, ry)}; self.get_click("点：(1, 2) 中心", p2)

        self.get_click("点：(1, 1) 中心", p1)

    def set_lock(self):
        self.get_click("点击锁定图标", lambda rx, ry: [self.data.update({"lock": (rx, ry)}), self.save_config()])


if __name__ == "__main__":
    if run_as_admin():
        hide_console()
        root = tk.Tk()
        app = Matrixassistant(root)
        root.mainloop()
    else:
        sys.exit()