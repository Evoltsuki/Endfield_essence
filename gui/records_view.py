import tkinter as tk
from tkinter import ttk
from gui.dialogs import center_dialog
from gui.theme import apply_theme


def show_records(root, dm):
    popup = tk.Toplevel(root)
    popup.withdraw()
    popup.title('当前基质记录')
    popup.transient(root)
    popup.grab_set()
    tk.Label(popup, text='各武器已保留的词条总等级记录', padx=14, pady=12).pack(anchor='w')
    table_frame = tk.Frame(popup)
    table_frame.pack(fill='both', expand=True, padx=14, pady=(0, 14))
    table = ttk.Treeview(table_frame, columns=('weapon', 'count', 'scores'), show='headings')
    for key, label, width in (('weapon', '武器', 180), ('count', '记录数', 65), ('scores', '词条总等级', 260)):
        table.heading(key, text=label)
        table.column(key, width=width, minwidth=50)
    scroll = ttk.Scrollbar(table_frame, command=table.yview)
    table.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right', fill='y')
    table.pack(fill='both', expand=True)
    for name, scores in sorted(dm.best_records.items()):
        table.insert('', 'end', values=(name, len(scores), '、'.join(map(str, scores))))
    if not dm.best_records:
        table.insert('', 'end', values=('暂无基质记录', '', ''))
    apply_theme(popup)
    center_dialog(popup, root, 560, 380)
    popup.deiconify()
    popup.bind('<Escape>', lambda event: popup.destroy())
    return popup
