import tkinter as tk
from tkinter import messagebox
from core.potential import get_rules, DEFAULT_RULES
from gui.theme import apply_theme
from gui.dialogs import center_dialog


def show_potential_editor(root, dm):
    popup = tk.Toplevel(root)
    popup.withdraw()
    popup.title("锁定基质规则")
    popup.transient(root)
    popup.grab_set()
    popup.resizable(False, False)
    general = tk.LabelFrame(popup, text="锁定与保留", padx=12, pady=10)
    general.pack(fill='x', padx=16, pady=(12, 0))
    keep = tk.BooleanVar(value=dm.data.get('keep_potential', True))
    limited = tk.BooleanVar(value=dm.data.get('enable_grad_limit', False))
    count = tk.StringVar(value=str(dm.data.get('grad_keep_limit', 1)))
    tk.Checkbutton(general, text="保留潜力基质", variable=keep).grid(row=0, column=0, sticky='w', padx=4)
    tk.Checkbutton(general, text="毕业锁定上限", variable=limited).grid(row=0, column=1, padx=8)
    count_entry = tk.Spinbox(general, from_=1, to=999, textvariable=count, width=5)
    count_entry.grid(row=0, column=2)
    tk.Label(general, text="件 / 武器").grid(row=0, column=3, padx=5)
    def update_limit(*args):
        count_entry.configure(state='normal' if limited.get() else 'disabled')
    limited.trace_add('write', update_limit)
    update_limit()
    frame = tk.Frame(popup, padx=16, pady=14)
    frame.pack(fill="both", expand=True)
    tk.Label(frame, text="同品质规则满足任意一条即保留；毕业匹配优先。", anchor="w").grid(row=0, column=0, columnspan=4, sticky="w", pady=6)
    tk.Label(frame, text="特殊词条名称（逗号分隔；留空按两字词条识别）").grid(row=1, column=0, columnspan=4, sticky="w")
    rules = get_rules(dm.data)
    names = tk.StringVar(value="，".join(rules['skill_names']))
    tk.Entry(frame, textvariable=names, width=48).grid(row=2, column=0, columnspan=4, sticky="ew", pady=8)
    for col, text in enumerate(("启用", "品质", "总等级至少", "特殊词条等级等于")):
        tk.Label(frame, text=text).grid(row=3, column=col, padx=10, pady=6)
    fields = []
    for rarity, title in (("gold", "金色"), ("purple", "紫色")):
        for rule in rules[rarity]:
            row = len(fields)+4
            enabled = tk.BooleanVar(value=rule['enabled'])
            total = tk.StringVar(value=str(rule['total']))
            level = tk.StringVar(value=str(rule['level']))
            tk.Checkbutton(frame, variable=enabled).grid(row=row, column=0)
            tk.Label(frame, text=title, fg="#A27311" if rarity == 'gold' else '#8054A5').grid(row=row, column=1)
            for col, variable, upper in ((2, total, 18), (3, level, 6)):
                tk.Spinbox(frame, from_=0, to=upper, textvariable=variable, width=6).grid(row=row, column=col, pady=5)
            fields.append((rarity, enabled, total, level))
    footer = len(fields)+4
    tk.Label(frame, text="0 表示不限；每条规则都要求存在特殊词条。", fg="#64748B").grid(row=footer, column=0, columnspan=4, pady=8)
    def save():
        try:
            result = {"skill_names": [x.strip() for x in names.get().replace('，', ',').split(',') if x.strip()], 'gold': [], 'purple': []}
            for rarity, enabled, total, level in fields:
                result[rarity].append(dict(enabled=enabled.get(), total=int(total.get()), level=int(level.get())))
            get_rules({'potential_rules': result})
            limit = int(count.get())
            if not 1 <= limit <= 999:
                raise ValueError('毕业锁定上限应为1–999件')
        except ValueError as error:
            messagebox.showerror("规则未保存", str(error), parent=popup)
            return
        dm.data['potential_rules'] = result
        dm.data.update(keep_potential=keep.get(), enable_grad_limit=limited.get(), grad_keep_limit=limit)
        dm.save_config()
        popup.destroy()
    def reset():
        names.set('')
        keep.set(True)
        limited.set(False)
        count.set('1')
        indexes = {'gold': 0, 'purple': 0}
        for rarity, enabled, total, level in fields:
            default = DEFAULT_RULES[rarity][indexes[rarity]]
            indexes[rarity] += 1
            enabled.set(default['enabled']); total.set(str(default['total'])); level.set(str(default['level']))
    tk.Button(frame, text="恢复默认", command=reset).grid(row=footer+1, column=0, columnspan=2, pady=8)
    tk.Button(frame, text="保存规则", command=save, bg="#2E7D32", fg="white", padx=20, pady=6).grid(row=footer+1, column=2, columnspan=2)
    apply_theme(popup)
    center_dialog(popup, root)
    popup.deiconify()
    return popup
