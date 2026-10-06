import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock
from gui.records_view import show_records


class RecordsViewTests(unittest.TestCase):
    def test_records_are_displayed_without_modification(self):
        root = tk.Tk()
        root.withdraw()
        dm = Mock(best_records={'测试武器': [12, 9]})
        try:
            popup = show_records(root, dm)
            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)
            table = next(widget for widget in descendants(popup) if isinstance(widget, ttk.Treeview))
            self.assertEqual(table.item(table.get_children()[0], 'values'), ('测试武器', '2', '12、9'))
            self.assertEqual(dm.best_records, {'测试武器': [12, 9]})
            dm.save_records.assert_not_called()
        finally:
            root.destroy()
