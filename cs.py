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
from PIL import Image, ImageTk
import ddddocr
from pynput import keyboard
import pygetwindow as gw
import ctypes
import threading
import difflib
import sys

# --- 跨屏幕/超宽屏坐标修复类 ---
class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_int), ("top", ctypes.c_int),
                ("right", ctypes.c_int), ("bottom", ctypes.c_int)]

# --- 权限与窗口管理逻辑 ---

def hide_console():
    """隐藏控制台窗口"""
    whnd = ctypes.windll.kernel32.GetConsoleWindow()
    if whnd != 0:
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


try:
    # 修复：设置为 2 (Per Monitor DPI Aware)，解决多屏幕缩放不一致导致的坐标错位
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except:
    ctypes.windll.user32.SetProcessDPIAware()

pydirectinput.PAUSE = 0.02
pyautogui.FAILSAFE = False


# --- 带有不透明教学图片和蓝色粗线框的全屏蒙版 ---

class SelectionCanvas:
    def __init__(self, root, img_name, callback):
        self.root = root
        self.callback = callback
        # 修复：mss monitors[0] 是虚拟显示器（全屏幕集合），适合多屏覆盖
        self.mon = mss.mss().monitors[0]

        self.top = tk.Toplevel(root)
        self.top.attributes("-alpha", 0.6, "-topmost", True)
        self.top.geometry(f"{self.mon['width']}x{self.mon['height']}+{self.mon['left']}+{self.mon['top']}")
        self.top.overrideredirect(True)
        self.top.configure(bg="white")

        self.canvas = tk.Canvas(self.top, cursor="crosshair", bg="white", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.img_win = None
        img_path = os.path.join("img", img_name)
        if os.path.exists(img_path):
            self.img_win = tk.Toplevel(self.root)
            self.img_win.attributes("-topmost", True)
            self.img_win.overrideredirect(True)

            img = Image.open(img_path)
            img.thumbnail((800, 600))
            self.tk_img = ImageTk.PhotoImage(img)

            pw, ph = img.width, img.height
            self.img_win.geometry(f"{pw}x{ph}+{(self.mon['width'] - pw) // 2}+{self.mon['top'] + (self.mon['height'] - ph) // 2}")
            lbl = tk.Label(self.img_win, image=self.tk_img, bg="white", highlightthickness=0)
            lbl.image = self.tk_img  # 保持引用
            lbl.pack()

            self.img_win.lift()
            self.top.lift()
            self.img_win.lift()

        self.start_x = None
        self.start_y = None
        self.rect = None

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Button-3>", lambda e: self.close())
        self.top.bind("<Escape>", lambda e: self.close())

    def on_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        # 蓝色线条，宽度 4
        self.rect = self.canvas.create_rectangle(self.start_x, self.start_y, event.x, event.y, outline="blue", width=4)

    def on_drag(self, event):
        self.canvas.coords(self.rect, self.start_x, self.start_y, event.x, event.y)

    def on_release(self, event):
        end_x, end_y = event.x, event.y
        x1, x2 = min(self.start_x, end_x), max(self.start_x, end_x)
        y1, y2 = min(self.start_y, end_y), max(self.start_y, end_y)
        w, h = x2 - x1, y2 - y1
        self.close()
        if w > 10 and h > 10:
            # 这里的坐标已经是基于全屏偏移的
            self.callback(x1 + self.mon['left'], y1 + self.mon['top'], w, h)

    def close(self):
        if self.img_win and self.img_win.winfo_exists():
            self.img_win.destroy()
        if self.top.winfo_exists():
            self.top.destroy()


class Matrixassistant:
    def __init__(self, root):
        self.root = root
        self.root.title("毕业基质自动识别工具beta v1.0 -by洁柔厨")
        self.root.geometry("540x880")
        self.root.attributes("-topmost", True)

        try:
            self.ocr = ddddocr.DdddOcr(show_ad=False, beta=True)
        except Exception as e:
            messagebox.showerror("OCR初始化失败", f"错误: {e}")

        self.config_file = "config.json"
        self.csv_file = "weapon_data.csv"
        self.corrections_file = "Jiucuo.json"

        self.running = False
        self.data = self.load_config()
        self.weapon_list = self.load_weapon_csv()
        self.corrections = self.load_corrections()

        # --- UI 顶部区域：分栏容器 ---
        header_container = tk.Frame(root)
        header_container.pack(anchor="nw", padx=10, pady=5, fill="x")

        # 1. 左侧分栏：配置状态 + 功能按钮
        left_status_frame = tk.Frame(header_container)
        left_status_frame.pack(side="left", anchor="nw")

        self.top_status_var = tk.StringVar()
        self.update_config_status()
        tk.Label(left_status_frame, textvariable=self.top_status_var, font=("微软雅黑", 9), fg="green").pack(anchor="w")

        self.fix_btn = tk.Button(left_status_frame, text="添加错字纠正", command=self.add_correction_popup,
                                 font=("微软雅黑", 8), bg="#F5F5F5", padx=2, pady=0)
        self.fix_btn.pack(anchor="w", pady=(2, 0))

        self.add_weapon_btn = tk.Button(left_status_frame, text="添加武器数据", command=self.add_weapon_popup,
                                        font=("微软雅黑", 8), bg="#F5F5F5", padx=2, pady=0)
        self.add_weapon_btn.pack(anchor="w", pady=(2, 0))

        # 2. 右侧分栏：输入框 + 推荐语 + 开始按钮
        right_input_frame = tk.Frame(header_container)
        right_input_frame.pack(side="left", anchor="nw", padx=(10, 0))

        row1 = tk.Frame(right_input_frame)
        row1.pack(anchor="w")
        tk.Label(row1, text=" | 速度:", font=("微软雅黑", 9)).pack(side="left")
        self.speed_var = tk.StringVar(value=self.data.get("speed", "0.3"))
        tk.Entry(row1, textvariable=self.speed_var, width=5).pack(side="left", padx=2)

        tk.Label(row1, text=" | 滑动像素:", font=("微软雅黑", 9)).pack(side="left")
        self.dist_var = tk.StringVar(value=self.data.get("scroll_pixel_dist", "200"))
        tk.Entry(row1, textvariable=self.dist_var, width=5).pack(side="left", padx=2)

        row2 = tk.Frame(right_input_frame)
        row2.pack(anchor="w", pady=(2, 0))
        tk.Label(row2, text="推荐 0.3-0.5", font=("微软雅黑", 8), fg="#888888").pack(side="left", padx=(15, 0))
        tk.Label(row2, text="1080p推荐110 2k推荐140", font=("微软雅黑", 8), fg="#888888").pack(side="left",
                                                                                               padx=(13, 0))

        self.run_btn = tk.Button(right_input_frame, text="▶ 开始自动扫描", command=self.start_thread,
                                 bg="#2E7D32", fg="white", font=("微软雅黑", 12, "bold"),
                                 width=15, height=1)
        self.run_btn.pack(anchor="center", pady=(10, 0))

        tk.Label(right_input_frame, text="( 按 'B' 键可提前停止扫描 )", font=("微软雅黑", 9), fg="#666666").pack()

        # --- 中间校准按钮区 ---
        btn_frame = tk.Frame(root)
        btn_frame.pack(pady=5)
        tk.Button(btn_frame, text="基质框选", command=self.set_matrix_roi, width=12).grid(row=0, column=0, padx=5,
                                                                                          pady=5)
        tk.Button(btn_frame, text="框选识别区", command=self.set_roi, width=12).grid(row=0, column=1, padx=5, pady=5)
        tk.Button(btn_frame, text="校准网格", command=self.set_grid, width=12).grid(row=1, column=0, padx=5, pady=5)
        tk.Button(btn_frame, text="校准锁定键", command=self.set_lock, width=12).grid(row=1, column=1, padx=5, pady=5)

        # --- 日志标题行 ---
        log_header_frame = tk.Frame(root)
        log_header_frame.pack(anchor="w", padx=10)
        tk.Label(log_header_frame, text="实时日志:", font=("微软雅黑", 11)).pack(side="left")
        tk.Label(log_header_frame, text="           识别过程中请勿遮挡基质和词条区域",
                 font=("微软雅黑", 9, "bold"), fg="red").pack(side="left", padx=(10, 0))

        self.log_area = scrolledtext.ScrolledText(root, height=10, width=60, font=("微软雅黑", 12))
        self.log_area.pack(padx=10, pady=5)
        self.log_area.tag_config("black", foreground="black")
        self.log_area.tag_config("green", foreground="#2E7D32")
        self.log_area.tag_config("gold", foreground="#FF9800")
        self.log_area.tag_config("red", foreground="red")
        self.log_area.tag_config("blue", foreground="blue")

        # --- 锁定列表区 ---
        tk.Label(root, text="已锁定列表:", font=("微软雅黑", 11, "bold")).pack(anchor="w", padx=10)
        self.lock_list_area = scrolledtext.ScrolledText(root, height=8, width=60, font=("微软雅黑", 12), bg="#F9F9F9")
        self.lock_list_area.pack(padx=10, pady=5, fill="x")
        self.lock_list_area.tag_config("red_text", foreground="red")
        self.lock_list_area.tag_config("gold_text", foreground="#FF9800")
        self.lock_list_area.tag_config("green_text", foreground="#2E7D32")
        self.lock_list_area.tag_config("black_text", foreground="black")

        self.kb = keyboard.Listener(on_press=self.on_press)
        self.kb.start()

        # --- 右侧信息标注 ---
        self.info_label = tk.Label(root, text="群号: 1006580737\n本工具完全免费",
                                   font=("微软雅黑", 9, "bold"), fg="#FF5722", justify="right")
        self.info_label.place(relx=1.0, x=-10, y=10, anchor="ne")
        self.info_label.lift()  # 强制提升

    def add_weapon_popup(self):
        popup = tk.Toplevel(self.root)
        popup.title("添加武器数据");
        popup.geometry("320x450");
        popup.attributes("-topmost", True)
        fields = [("武器名称:", "name"), ("星级 (5或6):", "star"), ("毕业词条1:", "c1"), ("毕业词条2:", "c2"),
                  ("毕业词条3:", "c3")]
        entries = {}
        for label_text, key in fields:
            tk.Label(popup, text=label_text, font=("微软雅黑", 9)).pack(pady=(10, 2))
            entry = tk.Entry(popup, width=30);
            entry.pack();
            entries[key] = entry

        def confirm():
            name, star = entries["name"].get().strip(), entries["star"].get().strip()
            c_vals = [entries["c1"].get().strip(), entries["c2"].get().strip(), entries["c3"].get().strip()]
            if not name or not star or not c_vals[0]: messagebox.showwarning("提示", "必填项缺失");
            return
            if star not in ["5", "6"]:
                messagebox.showwarning("提示", "星级只能输入 5 或 6");
                return

            save_star = f"{star}星"
            new_row = {"武器": name, "星级": save_star, "毕业词条1": c_vals[0], "毕业词条2": c_vals[1],
                       "毕业词条3": c_vals[2]}
            try:
                file_exists = os.path.isfile(self.csv_file)
                with open(self.csv_file, 'a', encoding='utf-8-sig', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=["武器", "星级", "毕业词条1", "毕业词条2", "毕业词条3"])
                    if not file_exists: writer.writeheader()
                    writer.writerow(new_row)
                self.weapon_list.append(new_row)
                messagebox.showinfo("成功", f"武器 {name} 已添加")
                popup.destroy()
            except Exception as e:
                messagebox.showerror("保存失败", f"错误: {e}")

        tk.Button(popup, text="确认添加武器数据", command=confirm, bg="#2E7D32", fg="white",
                  font=("微软雅黑", 10, "bold"), width=20).pack(pady=25)

    def add_correction_popup(self):
        popup = tk.Toplevel(self.root);
        popup.title("错字纠正");
        popup.geometry("300x180");
        popup.attributes("-topmost", True)
        tk.Label(popup, text="错误文字").grid(row=0, column=0, padx=10, pady=10);
        tk.Label(popup, text="正确文字").grid(row=0, column=1, padx=10, pady=10)
        w_ent = tk.Entry(popup, width=15);
        w_ent.grid(row=1, column=0, padx=10, pady=5)
        r_ent = tk.Entry(popup, width=15);
        r_ent.grid(row=1, column=1, padx=10, pady=5)

        def confirm():
            w, r = w_ent.get().strip(), r_ent.get().strip()
            if w and r:
                self.corrections[w] = r
                with open(self.corrections_file, 'w', encoding='utf-8') as f: json.dump(self.corrections, f,
                                                                                        ensure_ascii=False, indent=4)
                messagebox.showinfo("成功", "纠正已保存");
                popup.destroy()

        tk.Button(popup, text="确认添加", command=confirm, bg="#2E7D32", fg="white", width=15).grid(row=2, column=0,
                                                                                                    columnspan=2,
                                                                                                    pady=20)

    def load_corrections(self):
        if os.path.exists(self.corrections_file):
            try:
                with open(self.corrections_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {}

    def is_already_locked(self, sct, lock_pos, win_rect):
        try:
            abs_x, abs_y = int(win_rect[0] + lock_pos[0]), int(win_rect[1] + lock_pos[1])
            lock_snap = np.array(sct.grab({"left": abs_x - 15, "top": abs_y - 15, "width": 40, "height": 40}))
            gray = cv2.cvtColor(cv2.cvtColor(lock_snap, cv2.COLOR_BGRA2BGR), cv2.COLOR_BGR2GRAY)
            return np.mean(gray) < 130
        except:
            return False

    def start_thread(self):
        if not all(self.data.get(k) is not None for k in ["roi", "grid", "lock", "matrix_size"]):
            messagebox.showwarning("提示", "配置未完成");
            return
        self.save_config();
        self.corrections = self.load_corrections()
        self.log_area.delete('1.0', tk.END);
        self.lock_list_area.delete('1.0', tk.END)
        self.gui_log("[系统] 扫描启动，按 'B' 键停止", "blue")
        self.running = True;
        self.run_btn.config(state="disabled", text="正在扫描...")
        threading.Thread(target=self.run_task, daemon=True).start()

    def gui_log(self, message, color_tag="black"):
        self.log_area.insert(tk.END, message + "\n", color_tag);
        self.log_area.see(tk.END)

    def add_to_lock_list(self, matches, pos):
        for w in matches:
            w_name, star = w.get('武器', '未知'), w.get('星级', '6')
            self.lock_list_area.insert(tk.END, f"{w_name} ", "red_text" if "6" in star else "gold_text")
        first = matches[0]
        attr_list = [first.get(f'毕业词条{i}', '') for i in range(1, 4)]
        attrs_display = " " + "，".join([a for a in attr_list if a]) + " "
        self.lock_list_area.insert(tk.END, attrs_display, "green_text")
        self.lock_list_area.insert(tk.END, "坐标" + pos + "\n", "black_text");
        self.lock_list_area.see(tk.END)

    def on_press(self, key):
        try:
            if hasattr(key, 'char') and key.char == 'b':
                if self.running: self.gui_log("[停止] 任务已中止", "red"); self.running = False
        except:
            pass

    def load_weapon_csv(self):
        weapons = []
        if os.path.exists(self.csv_file):
            try:
                with open(self.csv_file, 'r', encoding='utf-8-sig') as f:
                    reader = csv.DictReader(f)
                    for row in reader: weapons.append({k.strip(): v.strip() for k, v in row.items() if k})
            except:
                pass
        return weapons

    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {"roi": None, "grid": None, "lock": None, "matrix_size": None, "speed": "0.3",
                "scroll_pixel_dist": "200"}

    def save_config(self):
        try:
            self.data["speed"], self.data["scroll_pixel_dist"] = self.speed_var.get(), self.dist_var.get()
        except:
            pass
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=4)
        self.update_config_status()

    def update_config_status(self):
        ready = all(self.data.get(k) is not None for k in ["roi", "grid", "lock", "matrix_size"])
        self.top_status_var.set("✅ 配置已就绪" if ready else "❌ 配置不全")

    def clean_text(self, raw_text):
        if not raw_text: return ""
        txt = re.sub(r'[^\u4e00-\u9fa5]', '', str(raw_text))
        if self.corrections:
            for wrong, right in self.corrections.items(): txt = txt.replace(wrong, right)
        return txt

    def check_all_attributes(self, weapon, ocr_full_text):
        targets = [self.clean_text(weapon.get(f'毕业词条{i}', '')) for i in range(1, 4)]
        targets = [t for t in targets if t]
        if not targets: return False
        for t in targets:
            if t in ocr_full_text: continue
            best_match_ratio = 0
            for i in range(len(ocr_full_text) - len(t) + 1):
                ratio = difflib.SequenceMatcher(None, t, ocr_full_text[i:i + len(t)]).ratio()
                if ratio > best_match_ratio: best_match_ratio = ratio
            if best_match_ratio < (0.82 if len(t) > 2 else 0.88): return False
        return True

    def is_gold(self, cell_bgr):
        try:
            h, w = cell_bgr.shape[:2]
            # 修复：采样底部 15% 区域
            strip = cell_bgr[int(h * 0.85):, :]
            hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
            lower_gold = np.array([15, 100, 100])
            upper_gold = np.array([35, 255, 255])
            mask = cv2.inRange(hsv, lower_gold, upper_gold)
            gold_rate = np.sum(mask > 0) / mask.size
            return gold_rate > 0.05
        except Exception as e:
            return False

    def run_task(self):
        roi, grid, lock = self.data["roi"], self.data["grid"], self.data["lock"]
        m_size = self.data.get("matrix_size", (100, 100));
        self.weapon_list = self.load_weapon_csv()
        with mss.mss() as sct:
            current_row = 0
            while self.running:
                try:
                    current_speed = float(self.speed_var.get())
                    move_pixel = int(float(self.dist_var.get()))
                    if move_pixel == 90: move_pixel = 91
                except:
                    current_speed, move_pixel = 0.3, 200
                for c in range(9):
                    if not self.running: break
                    cur_win = self.get_game_rect()
                    if not cur_win: break
                    abs_x, abs_y = int(cur_win[0] + grid["rx"] + c * grid["rdx"]), int(
                        cur_win[1] + grid["ry"] + min(current_row, 4) * grid["rdy"])
                    snap = np.array(sct.grab(
                        {"left": abs_x - int(m_size[0] / 2), "top": abs_y - int(m_size[1] / 2), "width": int(m_size[0]),
                         "height": int(m_size[1])}))
                    if self.is_gold(cv2.cvtColor(snap, cv2.COLOR_BGRA2BGR)):
                        self.gui_log(f"--- 检查: {current_row + 1}-{c + 1} ---")
                        pydirectinput.click(abs_x, abs_y);
                        time.sleep(current_speed)
                        ocr_snap = np.array(sct.grab(
                            {"left": int(cur_win[0] + roi[0]), "top": int(cur_win[1] + roi[1]), "width": int(roi[2]),
                             "height": int(roi[3])}))
                        gray = cv2.cvtColor(cv2.cvtColor(ocr_snap, cv2.COLOR_BGRA2BGR), cv2.COLOR_BGR2GRAY)
                        scaled = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
                        _, binary = cv2.threshold(scaled, 150, 255, cv2.THRESH_BINARY_INV)
                        full_txt, clean_list, h = "", [], binary.shape[0];
                        slice_h = h // 3
                        for i in range(3):
                            part = binary[max(0, i * slice_h):min(h, (i + 1) * slice_h), :]
                            _, img_bytes = cv2.imencode('.png', part)
                            res = self.ocr.classification(img_bytes.tobytes())
                            if res:
                                txt = self.clean_text(res)
                                if txt: clean_list.append(txt)
                        full_txt = "，".join(clean_list)
                        if full_txt:
                            self.gui_log(f"识别结果: {full_txt}", "green")
                            matches = [w for w in self.weapon_list if self.check_all_attributes(w, full_txt)]

                            # --- 毕业输出 ---
                            if matches:
                                self.gui_log("检测到毕业基质！", "gold")
                                if self.is_already_locked(sct, lock, cur_win):
                                    self.gui_log("该基质已锁定，跳过", "red")
                                else:
                                    pydirectinput.click(int(cur_win[0] + lock[0]), int(cur_win[1] + lock[1]));
                                    time.sleep(0.4)
                                self.add_to_lock_list(matches, f"{current_row + 1}-{c + 1}")
                        else:
                            self.gui_log("-> 未读到有效词条")
                    else:
                        self.gui_log(f"非金色基质，停止扫描"); self.running = False; break
                if not self.running: break
                current_row += 1
                if current_row >= 5:
                    self.gui_log(f"[翻页] 向上滑动 {move_pixel} 像素...", "black")
                    cur_win = self.get_game_rect();
                    start_x = int(cur_win[0] + grid["rx"] + 4 * grid["rdx"])
                    start_y = int(cur_win[1] + grid["ry"] + 4 * grid["rdy"])
                    pydirectinput.moveTo(start_x, start_y);
                    pydirectinput.mouseDown();
                    time.sleep(0.1)
                    for s in range(16): pydirectinput.moveTo(start_x,
                                                             int(start_y - (move_pixel * (s / 15)))); time.sleep(0.01)
                    pydirectinput.mouseUp();
                    time.sleep(1.5)
        self.run_btn.config(state="normal", text="▶ 开始自动扫描")

    # 修复：使用 DwmGetWindowAttribute 获取真实物理坐标，解决超宽屏/缩放导致的 8 像素偏移
    def get_game_rect(self):
        try:
            wins = gw.getWindowsWithTitle('Endfield')
            if not wins: return None
            hwnd = wins[0]._hWnd
            rect = RECT()
            DWMWA_EXTENDED_FRAME_BOUNDS = 9
            ctypes.windll.dwmapi.DwmGetWindowAttribute(
                hwnd, DWMWA_EXTENDED_FRAME_BOUNDS,
                ctypes.byref(rect), ctypes.sizeof(rect)
            )
            return (rect.left, rect.top)
        except:
            # 降级方案
            return (wins[0].left, wins[0].top) if wins else None

    def get_click(self, prompt, callback, img_name=None):
        rect = self.get_game_rect();
        mon = mss.mss().monitors[0]
        ov = tk.Toplevel(self.root);
        ov.attributes("-alpha", 0.6, "-topmost", True)
        ov.geometry(f"{mon['width']}x{mon['height']}+{mon['left']}+{mon['top']}");
        ov.overrideredirect(True);
        ov.configure(bg="white")
        img_win = None
        if img_name:
            img_path = os.path.join("img", img_name)
            if os.path.exists(img_path):
                img_win = tk.Toplevel(self.root);
                img_win.attributes("-topmost", True);
                img_win.overrideredirect(True)
                img = Image.open(img_path);
                img.thumbnail((800, 600));
                tk_img = ImageTk.PhotoImage(img)
                pw, ph = img.width, img.height;
                img_win.geometry(f"{pw}x{ph}+{(mon['width'] - pw) // 2}+{mon['top'] + (mon['height'] - ph) // 2}")

                lbl = tk.Label(img_win, image=tk_img, bg="white");
                lbl.image = tk_img;
                lbl.pack()

                img_win.lift();
                ov.lift();
                img_win.lift()

        def on_click(e):
            if img_win: img_win.destroy()
            ov.destroy();
            # 修复：加上全屏监控器的物理偏移坐标，确保点击位置正确
            callback(e.x_root, e.y_root)

        ov.bind("<Button-1>", on_click);
        lbl_p = tk.Label(ov, text=prompt, font=("微软雅黑", 22, "bold"), fg="red", bg="white")
        lbl_p.pack(expand=True);
        lbl_p.bind("<Button-1>", on_click)

    def set_matrix_roi(self):
        SelectionCanvas(self.root, "guide_matrix.png",
                        lambda x, y, w, h: [self.data.update({"matrix_size": (w, h)}), self.save_config()])

    def set_roi(self):
        # 修复：计算相对于游戏窗口的绝对偏移
        SelectionCanvas(self.root, "guide_roi.png", lambda x, y, w, h: [self.data.update({"roi": (
            x - (self.get_game_rect()[0] if self.get_game_rect() else 0),
            y - (self.get_game_rect()[1] if self.get_game_rect() else 0), w, h)}), self.save_config()])

    def set_grid(self):
        # 修复：计算相对于游戏窗口的绝对坐标
        def p3(rx, ry):
            gx, gy = self.get_game_rect()
            p11 = self.data["grid"]["p11"]
            self.data["grid"]["rx"], self.data["grid"]["ry"] = p11[0] - gx, p11[1] - gy
            self.data["grid"]["rdx"] = self.data["grid"]["p12"][0] - p11[0]
            self.data["grid"]["rdy"] = ry - p11[1]
            self.save_config()

        def p2(rx, ry): self.data["grid"]["p12"] = (rx, ry); self.get_click("点：(2, 1)中心", p3, "guide_grid.png")

        def p1(rx, ry): self.data["grid"] = {"p11": (rx, ry)}; self.get_click("点：(1, 2)中心", p2, "guide_grid.png")

        self.get_click("点：(1, 1)中心", p1, "guide_grid.png")

    def set_lock(self):
        def save_lock(rx, ry):
            gx, gy = self.get_game_rect()
            self.data.update({"lock": (rx - gx, ry - gy)})
            self.save_config()
        self.get_click("点击锁定图标", save_lock, "guide_lock.png")


if __name__ == "__main__":
    if run_as_admin():
        hide_console(); root = tk.Tk(); app = Matrixassistant(root); root.mainloop()
    else:
        sys.exit()