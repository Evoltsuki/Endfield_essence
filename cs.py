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
from rapidocr_onnxruntime import RapidOCR
from opencc import OpenCC
from pynput import keyboard
import pygetwindow as gw
import ctypes
import threading
import difflib
import sys
import traceback

import win32gui
import win32ui
import win32con


# --- 跨屏幕坐标修复 ---
class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_int), ("top", ctypes.c_int),
                ("right", ctypes.c_int), ("bottom", ctypes.c_int)]


def run_as_admin():
    try:
        if ctypes.windll.shell32.IsUserAnAdmin(): return True
        executable = sys.executable
        if executable.endswith("python.exe"): executable = executable.replace("python.exe", "pythonw.exe")
        ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, __file__, None, 1)
        return False
    except:
        return False


try:
    # 强制开启 Per-Monitor DPI Aware，确保所有坐标单位均为物理像素
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except:
        pass

pydirectinput.PAUSE = 0.01
pyautogui.FAILSAFE = False


# --- 修复版：独立置顶引导蒙版 ---
class SelectionCanvas:
    def __init__(self, root, img_name, callback):
        self.root = root
        self.callback = callback
        # 获取所有显示器的联合区域（虚拟屏幕）用于蒙版覆盖
        self.mon = mss.mss().monitors[0]
        # 获取主显示器用于图片居中显示
        self.primary_mon = mss.mss().monitors[1] if len(mss.mss().monitors) > 1 else self.mon

        # 1. 创建全屏蒙版 (半透明)
        self.top = tk.Toplevel(root)
        self.top.attributes("-alpha", 0.6, "-topmost", True)
        # 几何设置：宽度x高度+左偏移+上偏移
        self.top.geometry(f"{self.mon['width']}x{self.mon['height']}+{self.mon['left']}+{self.mon['top']}")
        self.top.overrideredirect(True)
        self.top.configure(bg="white")
        self.canvas = tk.Canvas(self.top, cursor="crosshair", bg="white", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # 2. 创建独立教程图 (修复坐标偏移)
        self.img_win = None
        img_path = os.path.join("img", img_name)
        if os.path.exists(img_path):
            self.img_win = tk.Toplevel(root)
            self.img_win.attributes("-topmost", True)
            self.img_win.overrideredirect(True)
            img = Image.open(img_path)
            img.thumbnail((700, 500))
            self.tk_img = ImageTk.PhotoImage(img)

            # --- 核心修复：使用主显示器坐标来居中图片 ---
            # 使用 primary_mon 而非虚拟屏幕 mon，确保图片在主显示器上居中
            pos_x = self.primary_mon['left'] + (self.primary_mon['width'] - img.width) // 2
            pos_y = self.primary_mon['top'] + (self.primary_mon['height'] - img.height) // 2

            self.img_win.geometry(f"{img.width}x{img.height}+{pos_x}+{pos_y}")
            tk.Label(self.img_win, image=self.tk_img, bg="white", relief="solid", bd=2).pack()
            # 强制刷新并提升层级
            self.img_win.update_idletasks()
            self.root.after(50, lambda: self.img_win.lift() if self.img_win else None)

        self.start_x = self.start_y = self.rect = None
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Button-3>", lambda e: self.close())
        self.top.bind("<Escape>", lambda e: self.close())

    def on_press(self, event):
        # 用户点击即表示准备框选，立即销毁教程图，防止遮挡
        if self.img_win and self.img_win.winfo_exists():
            self.img_win.destroy()
            self.img_win = None
        self.start_x, self.start_y = event.x, event.y
        self.rect = self.canvas.create_rectangle(self.start_x, self.start_y, event.x, event.y, outline="blue", width=4)

    def on_drag(self, event):
        self.canvas.coords(self.rect, self.start_x, self.start_y, event.x, event.y)

    def on_release(self, event):
        x1, x2, y1, y2 = min(self.start_x, event.x), max(self.start_x, event.x), min(self.start_y, event.y), max(
            self.start_y, event.y)
        self.close()
        # 将相对于蒙版左上角的局部坐标还原为屏幕全局坐标
        if (x2 - x1) > 10 and (y2 - y1) > 10:
            self.callback(x1 + self.mon['left'], y1 + self.mon['top'], x2 - x1, y2 - y1)

    def close(self):
        if self.img_win and self.img_win.winfo_exists(): self.img_win.destroy()
        if self.top.winfo_exists(): self.top.destroy()


class Matrixassistant:
    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                return json.load(open(self.config_file, 'r', encoding='utf-8'))
            except:
                pass
        return {"roi": None, "grid": None, "lock": None, "matrix_size": None, "speed": "0.3",
                "scroll_pixel_dist": "200"}

    def load_corrections(self):
        return json.load(open(self.corrections_file, 'r', encoding='utf-8')) if os.path.exists(
            self.corrections_file) else {}

    def load_weapon_csv(self):
        ws = []
        if os.path.exists(self.csv_file):
            with open(self.csv_file, 'r', encoding='utf-8-sig') as f:
                r = csv.DictReader(f);
                [ws.append({k.strip(): v.strip() for k, v in row.items() if k}) for row in r]
        return ws

    def update_config_status(self):
        ready = all(self.data.get(k) is not None for k in ["roi", "grid", "lock", "matrix_size"])
        if hasattr(self, 'top_status_var'): self.top_status_var.set("✅ 配置已就绪" if ready else "❌ 配置不全")

    def save_config(self):
        try:
            self.data.update({"speed": self.speed_var.get(), "scroll_pixel_dist": self.dist_var.get()})
        except:
            pass
        json.dump(self.data, open(self.config_file, 'w', encoding='utf-8'), ensure_ascii=False, indent=4);
        self.update_config_status()

    # --- 按钮校准函数 ---
    def set_matrix_roi(self):
        SelectionCanvas(self.root, "guide_matrix.png",
                        lambda x, y, w, h: [self.data.update({"matrix_size": (w, h)}), self.save_config()])

    def set_roi(self):
        SelectionCanvas(self.root, "guide_roi.png", lambda x, y, w, h: [
            self.data.update({"roi": (x - self.get_game_rect()[0], y - self.get_game_rect()[1], w, h)}),
            self.save_config()])

    def set_grid(self):
        def p3(rx, ry): gx, gy = self.get_game_rect(); p11 = self.data["grid"]["p11"]; self.data["grid"].update(
            {"rx": p11[0] - gx, "ry": p11[1] - gy, "rdx": self.data["grid"]["p12"][0] - p11[0],
             "rdy": ry - p11[1]}); self.save_config()

        def p2(rx, ry): self.data["grid"]["p12"] = (rx, ry); self.get_click("点：(2, 1)中心", p3, "guide_grid.png")

        def p1(rx, ry): self.data["grid"] = {"p11": (rx, ry)}; self.get_click("点：(1, 2)中心", p2, "guide_grid.png")

        self.get_click("点：(1, 1)中心", p1, "guide_grid.png")

    def set_lock(self):
        self.get_click("点击锁定图标中心", lambda rx, ry: [
            self.data.update({"lock": (rx - self.get_game_rect()[0], ry - self.get_game_rect()[1])}),
            self.save_config()], "guide_lock.png")

    def add_weapon_popup(self):
        p = tk.Toplevel(self.root);
        p.title("添加武器数据");
        p.geometry("320x450");
        p.attributes("-topmost", True)
        fields = [("武器名称:", "name"), ("星级 (5或6):", "star"), ("毕业词条1:", "c1"), ("毕业词条2:", "c2"),
                  ("毕业词条3:", "c3")]
        ents = {k: tk.Entry(p, width=30) for _, k in fields}
        for (lbl, k) in fields: tk.Label(p, text=lbl, font=("微软雅黑", 9)).pack(pady=(10, 2)); ents[k].pack()

        def confirm():
            n, s = ents["name"].get().strip(), ents["star"].get().strip()
            c = [ents[x].get().strip() for x in ["c1", "c2", "c3"]]
            if not n or s not in ["5", "6"] or not c[0]: messagebox.showwarning("提示", "必填项缺失"); return
            new = {"武器": n, "星级": f"{s}星", "毕业词条1": c[0], "毕业词条2": c[1], "毕业词条3": c[2]}
            with open(self.csv_file, 'a', encoding='utf-8-sig', newline='') as f: csv.DictWriter(f, fieldnames=["武器",
                                                                                                                "星级",
                                                                                                                "毕业词条1",
                                                                                                                "毕业词条2",
                                                                                                                "毕业词条3"]).writerow(
                new)
            self.weapon_list.append(new);
            messagebox.showinfo("成功", f"武器 {n} 已添加");
            p.destroy()

        tk.Button(p, text="确认添加", command=confirm, bg="#2E7D32", fg="white", font=("微软雅黑", 10, "bold"),
                  width=20).pack(pady=25)

    def add_correction_popup(self):
        p = tk.Toplevel(self.root);
        p.title("错字纠正");
        p.geometry("300x180");
        p.attributes("-topmost", True)
        w_ent, r_ent = tk.Entry(p, width=15), tk.Entry(p, width=15)
        tk.Label(p, text="错误文字").grid(row=0, column=0, padx=10, pady=10);
        tk.Label(p, text="正确文字").grid(row=0, column=1, padx=10, pady=10)
        w_ent.grid(row=1, column=0, padx=10, pady=5);
        r_ent.grid(row=1, column=1, padx=10, pady=5)

        def confirm():
            w, r = w_ent.get().strip(), r_ent.get().strip()
            if w and r: self.corrections[w] = r; json.dump(self.corrections,
                                                           open(self.corrections_file, 'w', encoding='utf-8'),
                                                           ensure_ascii=False, indent=4); p.destroy()

        tk.Button(p, text="确认添加", command=confirm, bg="#2E7D32", fg="white", width=15).grid(row=2, column=0,
                                                                                                columnspan=2, pady=20)

    # --- 核心识别引擎 ---
    def capture_window_bg(self, hwnd):
        try:
            l, t, r, b = win32gui.GetClientRect(hwnd);
            w, h = r - l, b - t
            hDC = win32gui.GetWindowDC(hwnd);
            mDC = win32ui.CreateDCFromHandle(hDC);
            sDC = mDC.CreateCompatibleDC();
            sBM = win32ui.CreateBitmap()
            sBM.CreateCompatibleBitmap(mDC, w, h);
            sDC.SelectObject(sBM);
            ctypes.windll.user32.PrintWindow(hwnd, sDC.GetSafeHdc(), 2)
            bits = sBM.GetBitmapBits(True);
            img = np.frombuffer(bits, dtype='uint8');
            img.shape = (h, w, 4)
            win32gui.DeleteObject(sBM.GetHandle());
            sDC.DeleteDC();
            mDC.DeleteDC();
            win32gui.ReleaseDC(hwnd, hDC)
            return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        except:
            return None

    def is_already_locked_bg(self, window_img, lock_pos):
        try:
            lx, ly = int(lock_pos[0]), int(lock_pos[1])
            search_scope = window_img[max(0, ly - 35):ly + 35, max(0, lx - 35):lx + 35]
            t_p = os.path.join("img", "unlocked.png")
            if os.path.exists(t_p):
                template = cv2.imread(t_p)
                if template is not None:
                    res = cv2.matchTemplate(search_scope, template, cv2.TM_CCOEFF_NORMED)
                    if cv2.minMaxLoc(res)[1] > 0.75: return False
            return np.mean(cv2.cvtColor(search_scope, cv2.COLOR_BGR2GRAY)) < 170
        except:
            return False

    def clean_text(self, raw):
        if not raw: return ""
        txt = self.cc.convert(str(raw));
        txt = re.sub(r'[^\u4e00-\u9fff，]', '', txt)
        if self.corrections:
            for w in sorted(self.corrections.keys(), key=len, reverse=True): txt = txt.replace(w, self.corrections[w])
        return txt

    def check_all_attributes(self, weapon, ocr_full):
        ts = [self.clean_text(weapon.get(f'毕业词条{i}', '')) for i in range(1, 4) if weapon.get(f'毕业词条{i}', '')]
        pts = [self.clean_text(p) for p in ocr_full.split("，") if p.strip()]
        if not ts or not pts: return False
        h_hits, p_hits, m_idx = 0, 0, set()
        for t in ts:
            t_c = t.replace("提升", "");
            best_r, b_idx = 0, -1
            for i, p in enumerate(pts):
                if i in m_idx: continue
                r = difflib.SequenceMatcher(None, t_c, p.replace("提升", "")).ratio()
                if r > best_r: best_r, b_idx = r, i
            if best_r >= 0.85:
                h_hits += 1;
                m_idx.add(b_idx)
            elif best_r >= 0.6:
                p_hits += 1;
                m_idx.add(b_idx)
        return (h_hits == len(ts)) or (h_hits >= len(ts) - 1 and (h_hits + p_hits) >= len(ts))

    def is_gold(self, bgr):
        try:
            h, w = bgr.shape[:2];
            strip = bgr[int(h * 0.70):, :]
            hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV);
            mask = cv2.inRange(hsv, np.array([15, 100, 100]), np.array([35, 255, 255]))
            return (np.sum(mask > 0) / mask.size) > 0.05
        except:
            return False

    # --- 扫描主逻辑 ---
    def start_thread(self):
        if not all(
                self.data.get(k) is not None for k in ["roi", "grid", "lock", "matrix_size"]): messagebox.showwarning(
            "提示", "配置未完成"); return
        self.save_config();
        self.corrections = self.load_corrections();
        self.log_area.delete('1.0', tk.END);
        self.lock_list_area.delete('1.0', tk.END)
        self.gui_log("[系统] 扫描启动，按 'B' 键停止", "blue");
        self.running = True;
        self.run_btn.config(state="disabled", text="正在扫描...")
        threading.Thread(target=self.run_task, daemon=True).start()

    def run_task(self):
        try:
            roi, grid, lock, ms = self.data["roi"], self.data["grid"], self.data["lock"], self.data.get("matrix_size",
                                                                                                        (100, 100))
            hwnd = win32gui.FindWindow(None, 'Endfield') or win32gui.FindWindow(None, '终末地')
            curr_row = 0
            while self.running:
                time.sleep(0.01);
                spd, dist = float(self.speed_var.get() or 0.3), int(self.dist_var.get() or 200)
                win_img = self.capture_window_bg(hwnd)
                if win_img is None: self.gui_log("[错误] 后台截图失败", "red"); break
                for c in range(9):
                    if not self.running: break
                    rx, ry = int(grid["rx"] + c * grid["rdx"]), int(grid["ry"] + min(curr_row, 4) * grid["rdy"])
                    if self.debug_gold_var.get() or self.is_gold(win_img[max(0, ry - int(ms[1] / 2)):ry + int(
                            ms[1] / 2), max(0, rx - int(ms[0] / 2)):rx + int(ms[0] / 2)]):
                        self.gui_log(f"--- 检查: {curr_row + 1}-{c + 1} ---");
                        wr = self.get_game_rect()
                        pydirectinput.click(int(wr[0] + rx), int(wr[1] + ry));
                        time.sleep(spd)
                        scr = self.capture_window_bg(hwnd);
                        o_img = scr[int(roi[1]):int(roi[1] + roi[3]), int(roi[0]):int(roi[0] + roi[2])]
                        res, _ = self.ocr(cv2.cvtColor(
                            cv2.resize(cv2.cvtColor(o_img, cv2.COLOR_BGR2GRAY), None, fx=1.5, fy=1.5,
                                       interpolation=cv2.INTER_NEAREST), cv2.COLOR_GRAY2BGR))
                        ft = "，".join([line[1] for line in res]) if res else ""
                        if ft:
                            self.gui_log(f"识别结果: {self.clean_text(ft)}", "green")
                            matches = [w for w in self.weapon_list if self.check_all_attributes(w, ft)]
                            if matches:
                                self.gui_log("检测到毕业基质！", "gold")
                                if self.is_already_locked_bg(scr, lock):
                                    self.gui_log("该基质已锁定，跳过", "red")
                                else:
                                    # 单次点击动作，绝不重试，避免循环解锁
                                    pydirectinput.click(int(wr[0] + lock[0]), int(wr[1] + lock[1]))
                                    self.gui_log("-> 已执行锁定指令", "blue")
                                    time.sleep(0.4)
                                    pydirectinput.moveRel(50, 50)
                                self.add_to_lock_list(matches, f"{curr_row + 1}-{c + 1}")
                        else:
                            self.gui_log("-> 未读到词条")
                    else:
                        self.gui_log(f"非金色基质，停止扫描");
                        self.running = False;
                        break
                if not self.running: break
                if curr_row >= 4:
                    self.gui_log(f"[翻页] 向上滑动 {dist} 像素...", "black");
                    wr = self.get_game_rect()
                    sx, sy = int(wr[0] + grid["rx"] + 4 * grid["rdx"]), int(wr[1] + grid["ry"] + 4 * grid["rdy"])
                    pydirectinput.moveTo(sx, sy);
                    pydirectinput.mouseDown();
                    time.sleep(0.1)
                    for s in range(16): pydirectinput.moveTo(sx, int(sy - (dist * (s / 15)))); time.sleep(0.01)
                    pydirectinput.mouseUp();
                    time.sleep(1.2)
                curr_row += 1
        except Exception as e:
            self.gui_log(f"[异常] {e}", "red")
        finally:
            self.root.after(0, lambda: self.run_btn.config(state="normal", text="▶ 开始自动扫描"))

    # --- 工具方法 ---
    def gui_log(self, m, tag="black"):
        self.log_area.insert(tk.END, m + "\n", tag);
        self.log_area.see(tk.END)

    def add_to_lock_list(self, ms, p):
        for w in ms: self.lock_list_area.insert(tk.END, f"{w.get('武器', '未知')} ",
                                                "red_text" if "6" in w.get('星级', '6') else "gold_text")
        self.lock_list_area.insert(tk.END, " " + "，".join(
            [ms[0].get(f'毕业词条{i}', '') for i in range(1, 4) if ms[0].get(f'毕业词条{i}', '')]) + " ", "green_text");
        self.lock_list_area.insert(tk.END, "坐标" + p + "\n", "black_text");
        self.lock_list_area.see(tk.END)

    def on_press(self, k):
        if hasattr(k, 'char') and k.char == 'b' and self.running: self.gui_log("[停止] 任务已中止",
                                                                               "red"); self.running = False

    def get_game_rect(self):
        try:
            wins = gw.getWindowsWithTitle('Endfield') or gw.getWindowsWithTitle('终末地')
            if not wins: return None
            hwnd, rect = wins[0]._hWnd, RECT();
            ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect))
            return (rect.left, rect.top)
        except:
            return None

    # --- 修复后的独立图层置顶方法 ---
    def get_click(self, p, cb, img_n=None):
        mon = mss.mss().monitors[0]
        # 获取主显示器用于图片居中显示
        primary_mon = mss.mss().monitors[1] if len(mss.mss().monitors) > 1 else mon
        # 1. 蒙版窗口
        ov = tk.Toplevel(self.root)
        ov.attributes("-alpha", 0.6, "-topmost", True)
        ov.geometry(f"{mon['width']}x{mon['height']}+{mon['left']}+{mon['top']}")
        ov.overrideredirect(True);
        ov.configure(bg="white")

        # 2. 图片独立窗口 (100% 不透明)
        img_w = None
        if img_n and os.path.exists(os.path.join("img", img_n)):
            img_w = tk.Toplevel(self.root)
            img_w.attributes("-topmost", True);
            img_w.overrideredirect(True)
            pi = Image.open(os.path.join("img", img_n));
            pi.thumbnail((700, 500))
            tki = ImageTk.PhotoImage(pi)

            # 修复：使用主显示器坐标来居中图片
            pos_x = primary_mon['left'] + (primary_mon['width'] - pi.width) // 2
            pos_y = primary_mon['top'] + (primary_mon['height'] - pi.height) // 2
            img_w.geometry(f"{pi.width}x{pi.height}+{pos_x}+{pos_y}")

            tk.Label(img_w, image=tki, bg="white", relief="solid", bd=2).pack()
            img_w.image = tki
            # 延迟提升层级确保压在蒙版上
            self.root.after(50, lambda: img_w.lift())

        def onc(e):
            if img_w: img_w.destroy()
            ov.destroy();
            cb(e.x_root, e.y_root)

        ov.bind("<Button-1>", onc);
        tk.Label(ov, text=p, font=("微软雅黑", 22, "bold"), fg="red", bg="white").pack(expand=True)

    def __init__(self, root):
        self.root = root
        self.root.title("毕业基质自动识别工具beta v1.2 -by洁柔厨")
        self.root.geometry("540x880");
        self.root.attributes("-topmost", True)
        self.config_file, self.csv_file, self.corrections_file = "config.json", "weapon_data.csv", "Jiucuo.json"
        try:
            self.ocr = RapidOCR(intra_op_num_threads=4);
            self.cc = OpenCC('t2s')
        except Exception as e:
            messagebox.showerror("初始化失败", str(e))
        self.running = False;
        self.data = self.load_config();
        self.weapon_list = self.load_weapon_csv();
        self.corrections = self.load_corrections()

        # UI 双分栏
        header = tk.Frame(root);
        header.pack(anchor="nw", padx=10, pady=5, fill="x")
        lf = tk.Frame(header);
        lf.pack(side="left", anchor="nw")
        self.top_status_var = tk.StringVar();
        self.update_config_status()
        tk.Label(lf, textvariable=self.top_status_var, font=("微软雅黑", 9), fg="green").pack(anchor="w")
        tk.Button(lf, text="添加错字纠正", command=self.add_correction_popup, font=("微软雅黑", 8), bg="#F5F5F5",
                  padx=2, pady=0).pack(anchor="w", pady=(2, 0))
        tk.Button(lf, text="添加武器数据", command=self.add_weapon_popup, font=("微软雅黑", 8), bg="#F5F5F5", padx=2,
                  pady=0).pack(anchor="w", pady=(2, 0))
        self.debug_gold_var = tk.BooleanVar(value=False);
        tk.Checkbutton(lf, text="关闭金色识别", variable=self.debug_gold_var, font=("微软雅黑", 8)).pack(anchor="w",
                                                                                                         pady=(2, 0))

        rf = tk.Frame(header);
        rf.pack(side="left", anchor="nw", padx=(10, 0))
        r1 = tk.Frame(rf);
        r1.pack(anchor="w")
        tk.Label(r1, text=" | 速度:").pack(side="left")
        self.speed_var = tk.StringVar(value=self.data.get("speed", "0.3"));
        tk.Entry(r1, textvariable=self.speed_var, width=5).pack(side="left", padx=2)
        tk.Label(r1, text=" | 滑动:").pack(side="left")
        self.dist_var = tk.StringVar(value=self.data.get("scroll_pixel_dist", "200"));
        tk.Entry(r1, textvariable=self.dist_var, width=5).pack(side="left", padx=2)
        r2 = tk.Frame(rf);
        r2.pack(anchor="w", pady=(2, 0))
        tk.Label(r2, text="推荐 0.2-0.5", font=("微软雅黑", 8), fg="#888888").pack(side="left", padx=(15, 0))
        tk.Label(r2, text="1080p推荐110 2k推荐140", font=("微软雅黑", 8), fg="#888888").pack(side="left", padx=(13, 0))
        self.run_btn = tk.Button(rf, text="▶ 开始自动扫描", command=self.start_thread, bg="#2E7D32", fg="white",
                                 font=("微软雅黑", 12, "bold"), width=15, height=1);
        self.run_btn.pack(anchor="center", pady=(10, 0))

        mid = tk.Frame(root);
        mid.pack(pady=5)
        tk.Button(mid, text="基质框选", command=self.set_matrix_roi, width=12).grid(row=0, column=0, padx=5, pady=5)
        tk.Button(mid, text="框选识别区", command=self.set_roi, width=12).grid(row=0, column=1, padx=5, pady=5)
        tk.Button(mid, text="校准网格", command=self.set_grid, width=12).grid(row=1, column=0, padx=5, pady=5)
        tk.Button(mid, text="校准锁定键", command=self.set_lock, width=12).grid(row=1, column=1, padx=5, pady=5)

        self.log_area = scrolledtext.ScrolledText(root, height=10, width=60, font=("微软雅黑", 12));
        self.log_area.pack(padx=10, pady=5)
        for t, c in [("black", "black"), ("green", "#2E7D32"), ("gold", "#FF9800"), ("red", "red"),
                     ("blue", "blue")]: self.log_area.tag_config(t, foreground=c)
        tk.Label(root, text="已锁定列表:", font=("微软雅黑", 11, "bold")).pack(anchor="w", padx=10)
        self.lock_list_area = scrolledtext.ScrolledText(root, height=8, width=60, font=("微软雅黑", 12), bg="#F9F9F9");
        self.lock_list_area.pack(padx=10, pady=5, fill="x")
        for t, c in [("red_text", "red"), ("gold_text", "#FF9800"), ("green_text", "#2E7D32"),
                     ("black_text", "black")]: self.lock_list_area.tag_config(t, foreground=c)
        self.kb = keyboard.Listener(on_press=self.on_press);
        self.kb.start()
        tk.Label(root, text="群号: 1006580737\n本工具完全免费", font=("微软雅黑", 9, "bold"), fg="#FF5722",
                 justify="right").place(relx=1.0, x=-10, y=10, anchor="ne")


if __name__ == "__main__":
    if run_as_admin():
        root = tk.Tk()


        def handle_exception(exc_type, exc_value, exc_traceback):
            messagebox.showerror("运行错误", "".join(traceback.format_exception(exc_type, exc_value, exc_traceback)))


        sys.excepthook = handle_exception;
        app = Matrixassistant(root);
        root.mainloop()