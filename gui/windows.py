import csv
import tkinter as tk
from tkinter import messagebox

def show_add_correction_popup(root, dm):
    """显示错字纠正弹窗"""
    p = tk.Toplevel(root)
    p.title("错字纠正")
    p.geometry("300x180")
    p.attributes("-topmost", True)
    w_ent, r_ent = tk.Entry(p, width=15), tk.Entry(p, width=15)
    tk.Label(p, text="错误文字").grid(row=0, column=0, padx=10, pady=10)
    tk.Label(p, text="正确文字").grid(row=0, column=1, padx=10, pady=10)
    w_ent.grid(row=1, column=0, padx=10, pady=5)
    r_ent.grid(row=1, column=1, padx=10, pady=5)

    def confirm():
        w, r = w_ent.get().strip(), r_ent.get().strip()
        if w and r:
            dm.corrections[w] = r
            dm.save_corrections()
            p.destroy()

    tk.Button(p, text="确认添加", command=confirm, bg="#2E7D32", fg="white", width=15).grid(row=2, column=0, columnspan=2, pady=20)

def show_weapon_editor_popup(root, dm):
    """显示武器编辑大窗口"""
    editor_win = tk.Toplevel(root)
    editor_win.title("武器数据编辑器")
    editor_win.geometry("900x650")
    editor_win.minsize(1150, 500)
    editor_win.attributes("-topmost", True)

    top_bar = tk.Frame(editor_win)
    top_bar.pack(fill="x", padx=10, pady=5)

    search_frame = tk.Frame(top_bar, pady=10)
    search_frame.pack(side="bottom", fill="x")
    tk.Label(search_frame, text="搜索武器:", font=("微软雅黑", 10, "bold")).pack(side="left", padx=(0, 5))

    search_var = tk.StringVar()
    search_ent = tk.Entry(search_frame, textvariable=search_var, font=("微软雅黑", 10), width=30)
    search_ent.pack(side="left")
    tk.Label(search_frame, text="(支持模糊匹配)", fg="#999", font=("微软雅黑", 8)).pack(side="left", padx=5)

    container = tk.Frame(editor_win)
    container.pack(fill="both", expand=True, padx=10, pady=5)

    canvas = tk.Canvas(container, highlightthickness=0)
    scrollbar = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
    scrollable_frame = tk.Frame(canvas)

    scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas_frame = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

    def configure_canvas(event):
        if scrollable_frame.winfo_reqwidth() < event.width:
            canvas.itemconfigure(canvas_frame, width=event.width)

    canvas.bind("<Configure>", configure_canvas)
    canvas.configure(yscrollcommand=scrollbar.set)

    def _on_mousewheel(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    canvas.bind('<Enter>', lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
    canvas.bind('<Leave>', lambda e: canvas.unbind_all("<MouseWheel>"))

    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    headers = ["武器名称", "星级", "毕业词条1", "毕业词条2", "毕业词条3", "管理操作"]
    header_widths = [20, 10, 18, 18, 18, 10]
    for i, h in enumerate(headers):
        tk.Label(scrollable_frame, text=h, font=("微软雅黑", 10, "bold"), width=header_widths[i]).grid(row=0, column=i, padx=2, pady=5)

    table_rows = []

    def do_search(*args):
        query = search_var.get().strip().lower()
        for row_list in table_rows:
            weapon_name = row_list[0].get().strip().lower()
            if query in weapon_name:
                for widget in row_list: widget.grid()
            else:
                for widget in row_list: widget.grid_remove()

    search_var.trace_add("write", do_search)

    def add_row_ui(data=None):
        row_idx = len(table_rows) + 1
        row_widgets = []
        default_vals = data if data else {"武器": "", "星级": "", "毕业词条1": "", "毕业词条2": "", "毕业词条3": ""}
        fields = ["武器", "星级", "毕业词条1", "毕业词条2", "毕业词条3"]
        widths = [18, 8, 16, 16, 16]
        for col, field in enumerate(fields):
            e = tk.Entry(scrollable_frame, width=widths[col], font=("微软雅黑", 10))
            e.insert(0, default_vals.get(field, ""))
            e.grid(row=row_idx, column=col, padx=5, pady=2, sticky="ew")
            row_widgets.append(e)

        btn_del = tk.Button(scrollable_frame, text="删除", fg="white", bg="#d32f2f", command=lambda r=row_widgets: remove_row(r))
        btn_del.grid(row=row_idx, column=5, padx=10, pady=2)
        row_widgets.append(btn_del)
        table_rows.append(row_widgets)

    def remove_row(row_widgets):
        for w in row_widgets: w.destroy()
        if row_widgets in table_rows:
            table_rows.remove(row_widgets)

    for weapon in dm.weapon_list:
        add_row_ui(weapon)

    footer = tk.Frame(editor_win)
    footer.pack(fill="x", pady=15)

    def save_all():
        new_data = []
        for row in table_rows:
            try:
                if not row[0].winfo_exists(): continue
                vals = [row[i].get().strip() for i in range(5)]
                if not vals[0]: continue
                new_data.append({
                    "武器": vals[0], "星级": vals[1] if "星" in vals[1] else f"{vals[1]}星",
                    "毕业词条1": vals[2], "毕业词条2": vals[3], "毕业词条3": vals[4]
                })
            except: continue

        try:
            with open(dm.csv_file, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=["武器", "星级", "毕业词条1", "毕业词条2", "毕业词条3"])
                writer.writeheader()
                writer.writerows(new_data)
            dm.weapon_list = new_data
            messagebox.showinfo("成功", "数据已保存！")
            editor_win.destroy()
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    tk.Button(footer, text="+ 新增一行", command=add_row_ui, bg="#f0f0f0", width=15).pack(side="left", padx=30)
    tk.Button(footer, text="💾 保存所有修改", command=save_all, bg="#2E7D32", fg="white", font=("微软雅黑", 10, "bold"), width=20).pack(side="right", padx=30)