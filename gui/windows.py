import csv
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
from gui.theme import apply_theme
from gui.dialogs import center_dialog
from gui.records_view import show_records


def _trash_icon(master):
    """用固定像素图标避免 emoji 字体的额外留白。"""
    icon = tk.PhotoImage(master=master, width=16, height=16)
    for rect in ((3, 4, 13, 5), (6, 2, 10, 3), (4, 6, 5, 13),
                 (11, 6, 12, 13), (4, 13, 12, 14), (7, 7, 8, 12),
                 (9, 7, 10, 12)):
        icon.put('#A3222C', to=rect)
    return icon

def show_add_correction_popup(root, dm):
    """显示新增错字纠正内容的弹窗"""
    p = tk.Toplevel(root)
    p.withdraw()
    p.title("错字纠正")
    p.attributes("-topmost", True)
    p.transient(root)
    p.grab_set()

    w, h = 380, 230
    w_ent, r_ent = tk.Entry(p, width=15), tk.Entry(p, width=15)
    tk.Label(p, text="错误文字").grid(row=0, column=0, padx=10, pady=10)
    tk.Label(p, text="正确文字").grid(row=0, column=1, padx=10, pady=10)
    w_ent.grid(row=1, column=0, padx=10, pady=5)
    r_ent.grid(row=1, column=1, padx=10, pady=5)

    def confirm():
        w_text, r_text = w_ent.get().strip(), r_ent.get().strip()
        if not w_text or not r_text:
            messagebox.showwarning("请填写完整", "请输入错误文字和正确文字。", parent=p)
            (w_ent if not w_text else r_ent).focus_set()
            return
        if w_text == r_text:
            messagebox.showwarning("无需纠正", "错误文字与正确文字相同，请检查。", parent=p)
            r_ent.focus_set()
            return
        dm.corrections[w_text] = r_text
        dm.save_corrections()
        messagebox.showinfo("成功", "错字纠正已保存！", parent=p)
        p.destroy()

    def on_closing():
        if w_ent.get().strip() or r_ent.get().strip():
            ans = messagebox.askyesnocancel("提示", "有更改尚未保存，是否保存？", parent=p)
            if ans is True:
                confirm()
            elif ans is False:
                p.destroy()
        else:
            p.destroy()

    p.protocol("WM_DELETE_WINDOW", on_closing)
    tk.Button(p, text="保存纠正", command=confirm, bg="#2E7D32", fg="white", width=15, pady=6).grid(row=2, column=0, columnspan=2, pady=20)
    p.columnconfigure(0, weight=1)
    p.columnconfigure(1, weight=1)
    p.bind("<Return>", lambda event: confirm())
    p.bind("<Escape>", lambda event: on_closing())
    apply_theme(p)
    center_dialog(p, root, w, h)
    p.deiconify()
    w_ent.focus_set()


def show_weapon_editor_popup(root, dm):
    """显示武器数据的查看和编辑弹窗"""
    editor_win = tk.Toplevel(root)
    editor_win.withdraw()
    editor_win.title("武器数据编辑器")
    editor_win.minsize(800, 400)
    editor_win.attributes("-topmost", True)
    editor_win.transient(root)
    editor_win.grab_set()

    top_bar = tk.Frame(editor_win)
    top_bar.pack(fill="x", padx=10, pady=5)

    search_frame = tk.Frame(top_bar, pady=10)
    search_frame.pack(side="bottom", fill="x")

    tk.Label(search_frame, text="星级筛选:", font=("微软雅黑", 10, "bold")).pack(side="left", padx=(0, 5))
    star_var = tk.StringVar(value="全部")
    star_cb = ttk.Combobox(search_frame, textvariable=star_var, values=["全部", "6星", "5星"], width=6, state="readonly")
    star_cb.pack(side="left", padx=(0, 15))

    tk.Label(search_frame, text="搜索武器或词条:", font=("微软雅黑", 10, "bold")).pack(side="left", padx=(0, 5))
    search_var = tk.StringVar()
    search_ent = tk.Entry(search_frame, textvariable=search_var, font=("微软雅黑", 10), width=30)
    search_ent.pack(side="left")
    tk.Label(search_frame, text="(支持模糊匹配)", fg="#999", font=("微软雅黑", 8)).pack(side="left", padx=5)

    container = tk.Frame(editor_win)
    container.pack(fill="both", expand=True, padx=10, pady=5)

    canvas = tk.Canvas(container, highlightthickness=0)
    scrollbar = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
    horizontal = tk.Scrollbar(editor_win, orient="horizontal", command=canvas.xview)
    horizontal.pack(fill="x", padx=10)
    canvas.configure(xscrollcommand=horizontal.set)
    scrollable_frame = tk.Frame(canvas)

    scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas_frame = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

    is_modified = [False]

    def mark_modified(*args):
        is_modified[0] = True

    def configure_canvas(event):
        canvas.itemconfigure(canvas_frame, width=max(scrollable_frame.winfo_reqwidth(), event.width))

    canvas.bind("<Configure>", configure_canvas)
    canvas.configure(yscrollcommand=scrollbar.set)

    def _on_mousewheel(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    editor_win.bind("<MouseWheel>", _on_mousewheel)

    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    table_rows = []
    select_all_var = tk.BooleanVar(scrollable_frame)

    def toggle_select_all():
        """执行行数据全选/取消全选操作"""
        state = select_all_var.get()
        for row in table_rows:
            if row[1].winfo_ismapped():
                row[0].set(state)

    headers = ["全选", "武器名称", "星级", "毕业词条1", "毕业词条2", "毕业词条3", "状态", "操作"]
    header_widths = [5, 18, 8, 16, 16, 16, 8, 8]

    for i, h in enumerate(headers):
        if i == 0:
            chk = tk.Checkbutton(scrollable_frame, text=h, variable=select_all_var, command=toggle_select_all,
                                 font=("微软雅黑", 9, "bold"))
            chk.grid(row=0, column=i, padx=2, pady=5)
        else:
            tk.Label(scrollable_frame, text=h, font=("微软雅黑", 10, "bold"), width=header_widths[i]).grid(row=0, column=i, padx=2, pady=5)

    row_indices = {"new": 999, "existing": 1000}

    def do_search(*args):
        """执行表格数据过滤显示逻辑"""
        query = search_var.get().strip().lower()
        star_filter = star_var.get()

        for row_list in table_rows:
            try:
                # 重新映射索引
                w_name = row_list[2].get().strip().lower()
                w_star = row_list[3].get().strip()
                w_a1 = row_list[4].get().strip().lower()
                w_a2 = row_list[5].get().strip().lower()
                w_a3 = row_list[6].get().strip().lower()

                match_star = (star_filter == "全部") or (star_filter in w_star)
                match_query = (not query) or (query in w_name) or (query in w_a1) or (query in w_a2) or (query in w_a3)

                for widget in row_list:
                    if isinstance(widget, tk.Widget):
                        if match_star and match_query:
                            widget.grid()
                        else:
                            widget.grid_remove()
            except Exception:
                pass

    search_var.trace_add("write", do_search)
    star_cb.bind("<<ComboboxSelected>>", lambda e: do_search())

    def add_row_ui(data=None, is_new=False):
        """为表格添加新行"""
        if is_new:
            row_idx = row_indices["new"]
            row_indices["new"] -= 1
        else:
            row_idx = row_indices["existing"]
            row_indices["existing"] += 1

        row_widgets = []

        # 全选框
        chk_var = tk.BooleanVar(scrollable_frame)
        chk = tk.Checkbutton(scrollable_frame, variable=chk_var)
        chk.grid(row=row_idx, column=0, padx=5, pady=2)
        row_widgets.extend([chk_var, chk])

        default_vals = data if data else {"武器": "", "星级": "6星", "毕业词条1": "", "毕业词条2": "", "毕业词条3": ""}
        fields = ["武器", "星级", "毕业词条1", "毕业词条2", "毕业词条3"]
        widths = [18, 8, 16, 16, 16]

        # 文本框
        for col, field in enumerate(fields):
            e = tk.Entry(scrollable_frame, width=widths[col], font=("微软雅黑", 10))
            e.input_color = "#FFFFFF" if row_idx % 2 == 0 else "#F2F5F9"
            e.insert(0, default_vals.get(field, ""))
            e.bind("<KeyRelease>", mark_modified)
            e.grid(row=row_idx, column=col + 1, padx=5, pady=2, sticky="ew")
            row_widgets.append(e)

        # 屏蔽按钮
        shield_var = tk.StringVar(value=default_vals.get("屏蔽", ""))
        btn_shield = tk.Button(scrollable_frame, width=8, font=("微软雅黑", 9))

        def toggle_shield(btn, var):
            mark_modified()
            if var.get() == "1":
                var.set("")
                btn.config(bg="#9e9e9e", text="屏蔽", fg="white")
            else:
                var.set("1")
                btn.config(bg="#2E7D32", text="已屏蔽", fg="white")
            style_shield(btn, var)

        if shield_var.get() == "1":
            btn_shield.config(bg="#2E7D32", text="已屏蔽", fg="white")
        else:
            btn_shield.config(bg="#9e9e9e", text="屏蔽", fg="white")

        btn_shield.config(command=lambda b=btn_shield, v=shield_var: toggle_shield(b, v))
        btn_shield.grid(row=row_idx, column=6, padx=5, pady=2)
        row_widgets.extend([shield_var, btn_shield])

        # 删除按钮
        btn_del = tk.Button(scrollable_frame, text="删除", fg="white", bg="#d32f2f", width=6, font=("微软雅黑", 9),
                            command=lambda r=row_widgets: remove_row(r))
        btn_del.grid(row=row_idx, column=7, padx=5, pady=2)
        row_widgets.append(btn_del)
        # 后续分批载入和新增行也应用同一主题，不能只在窗口创建时处理。
        for widget in row_widgets:
            if isinstance(widget, tk.Widget):
                apply_theme(widget)
        style_shield(btn_shield, shield_var)

        if is_new:
            mark_modified()
            table_rows.insert(0, row_widgets)
        else:
            table_rows.append(row_widgets)

    def style_shield(button, variable):
        blocked = variable.get() == "1"
        button.theme_role = "warning" if blocked else "secondary"
        button.config(text="取消屏蔽" if blocked else "屏蔽")
        apply_theme(button)

    def remove_row(row_widgets):
        """删除指定行"""
        mark_modified()
        for w in row_widgets:
            if isinstance(w, tk.Widget):
                w.destroy()
        if row_widgets in table_rows:
            table_rows.remove(row_widgets)

    def batch_delete():
        """执行批量删除确认"""
        rows_to_delete = [row for row in table_rows if row[0].get()]
        if not rows_to_delete:
            messagebox.showwarning("提示", "请先勾选需要删除的数据！", parent=editor_win)
            return

        if messagebox.askyesno("批量删除",
                               f"确定要删除选中的 {len(rows_to_delete)} 项吗？\n注意：需要点击保存才会写入文件。",
                               parent=editor_win):
            for row in rows_to_delete:
                remove_row(row)
            select_all_var.set(False)

    def batch_shield():
        """执行批量屏蔽/取消屏蔽"""
        selected_rows = [row for row in table_rows if row[0].get()]
        if not selected_rows:
            messagebox.showwarning("提示", "请先勾选需要屏蔽的数据！", parent=editor_win)
            return

        all_shielded = all(row[7].get() == "1" for row in selected_rows)

        mark_modified()
        for row in selected_rows:
            shield_var = row[7]
            btn_shield = row[8]

            if all_shielded:
                shield_var.set("")
                btn_shield.config(bg="#9e9e9e", text="屏蔽", fg="white")
            else:
                shield_var.set("1")
                btn_shield.config(bg="#2E7D32", text="已屏蔽", fg="white")
            style_shield(btn_shield, shield_var)

    dm.weapon_list.sort(key=lambda x: str(x.get('星级', '6星')), reverse=True)

    def on_closing():
        if is_modified[0]:
            ans = messagebox.askyesnocancel("提示", "有更改尚未保存，是否保存并退出？", parent=editor_win)
            if ans is True:
                save_all()
            elif ans is False:
                editor_win.destroy()
        else:
            editor_win.destroy()

    editor_win.protocol("WM_DELETE_WINDOW", on_closing)

    def load_chunk(start_idx=0, chunk_size=20):
        if not editor_win.winfo_exists():
            return
        end_idx = min(start_idx + chunk_size, len(dm.weapon_list))
        for i in range(start_idx, end_idx):
            add_row_ui(dm.weapon_list[i], is_new=False)
        do_search()
        if end_idx < len(dm.weapon_list):
            editor_win.after(10, load_chunk, end_idx, chunk_size)

    load_chunk()

    footer = tk.Frame(editor_win)
    footer.pack(fill="x", pady=15, padx=20)
    footer.columnconfigure(5, weight=1)
    button_font = ("Microsoft YaHei UI", 9)

    tk.Button(footer, text="+ 新增一行", command=lambda: add_row_ui(is_new=True),
              bg="#f0f0f0", font=button_font, padx=4, pady=5).grid(row=0, column=0, sticky="nsew", padx=(0, 6))
    editor_win.trash_icon = _trash_icon(editor_win)
    tk.Button(footer, text="批量删除", image=editor_win.trash_icon, compound="left",
              command=batch_delete, bg="#d32f2f", fg="white", font=button_font, padx=4, pady=5).grid(
        row=0, column=1, sticky="nsew", padx=(0, 6))
    tk.Button(footer, text="🚫 批量屏蔽", command=batch_shield, bg="#FF9800", fg="white",
              font=button_font, padx=4, pady=5).grid(row=0, column=2, sticky="nsew", padx=(0, 6))

    def clear_records():
        if messagebox.askyesno("确认", "确定要清空所有的基质记录吗？\n清空后将重新开始记录最高等级。",
                               parent=editor_win):
            dm.best_records.clear()
            dm.save_records()
            messagebox.showinfo("成功", "记录已清空！", parent=editor_win)

    tk.Button(footer, text="当前基质记录", command=lambda: show_records(editor_win, dm),
              font=button_font, padx=4, pady=5).grid(row=0, column=3, sticky="nsew")
    tk.Button(footer, text="清空基质记录", image=editor_win.trash_icon, compound="left",
              command=clear_records, bg="#ffebee", fg="#c62828",
              font=("Microsoft YaHei UI", 9), padx=4, pady=5).grid(
                  row=0, column=4, sticky="nsew", padx=(6, 0))

    def save_all():
        """数据持久化保存"""
        new_data = []
        for row in table_rows:
            try:
                if not row[2].winfo_exists():
                    continue

                weapon_name = row[2].get().strip()
                if not weapon_name:
                    continue

                star_val = row[3].get().strip()
                shield_val = row[7].get()

                new_data.append({
                    "武器": weapon_name,
                    "星级": star_val if "星" in star_val else f"{star_val}星",
                    "毕业词条1": row[4].get().strip(),
                    "毕业词条2": row[5].get().strip(),
                    "毕业词条3": row[6].get().strip(),
                    "屏蔽": shield_val
                })
            except Exception:
                continue

        try:
            with open(dm.csv_file, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=["武器", "星级", "毕业词条1", "毕业词条2", "毕业词条3", "屏蔽"])
                writer.writeheader()
                writer.writerows(new_data)
            dm.weapon_list = new_data
            messagebox.showinfo("成功", "数据已保存！", parent=editor_win)
            editor_win.destroy()
        except Exception as e:
            messagebox.showerror("保存失败", str(e), parent=editor_win)

    tk.Button(footer, text="💾 保存所有修改", command=save_all, bg="#2E7D32", fg="white",
              font=button_font, padx=4, pady=5).grid(row=0, column=6, sticky="nsew", padx=(6, 0))
    apply_theme(editor_win)
    center_dialog(editor_win, root, 1180, 700, screen_center=True)
    editor_win.deiconify()
    search_ent.focus_set()
    return editor_win
