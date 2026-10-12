import csv

import requests

from core.fz_wiki import WeaponUpdateCancelled, fetch_weapon_rows
from core.weapon_store import WEAPON_FIELDS, WeaponDataError, merge_weapon_updates


class UpdateWeapon:
    _has_updated_this_session = False

    def __init__(self, dm, callbacks):
        self.dm = dm
        self.log_cb = callbacks.get('log', lambda m, t="black": None)
        self.cancelled = callbacks.get('cancelled', lambda: False)

    def export_weapon_rows(self, weapons, csv_filename=None):
        """Validate and save a whole batch before publishing success."""
        if self.cancelled():
            raise WeaponUpdateCancelled()
        result = merge_weapon_updates(csv_filename or self.dm.csv_file, weapons)
        self.dm.weapon_list = [
            {key: value.strip() for key, value in row.items()} for row in result.rows
        ]
        UpdateWeapon._has_updated_this_session = True

        for action, rows, color in (("新增", result.additions, "green"),
                                    ("修改", result.modifications, "blue")):
            if rows:
                lines = [f"已{action}武器："]
                lines.extend(" ".join(row[field] for field in WEAPON_FIELDS) for row in rows)
                self.log_cb("\n".join(lines), color)
        if result.additions or result.modifications:
            self.log_cb("[系统] 已完成武器列表更新", "blue")
        else:
            self.log_cb("[系统] 武器数据已是最新", "blue")
        return True

    def __run__(self):
        if UpdateWeapon._has_updated_this_session:
            return True

        self.log_cb("[系统] 正在从 FZ Wiki 获取武器列表...", "blue")
        try:
            weapons = fetch_weapon_rows(self.dm.weapon_list, self.cancelled)
            return self.export_weapon_rows(weapons)
        except WeaponUpdateCancelled:
            self.log_cb("[系统] 已取消武器更新", "blue")
        except requests.RequestException as exc:
            self.log_cb(f"[警告] 网络请求失败，跳过武器更新: {exc}", "red")
        except (WeaponDataError, csv.Error, UnicodeError, OSError) as exc:
            self.log_cb(f"[警告] 武器更新未完成，保留本地武器库: {exc}", "gold")
        return False
