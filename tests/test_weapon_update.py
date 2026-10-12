"""Persistence and HTTP failure tests; all writes use temporary weapon libraries."""

import csv
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import requests

from core.update import UpdateWeapon
from core.fz_wiki import WeaponUpdateCancelled
from core.weapon_store import CSV_FIELDS, WeaponDataError, merge_weapon_updates


OLD = ["已有武器", "6星", "力量提升", "攻击提升", "压制"]
CHANGED = ["已有武器", "6星", "敏捷提升", "攻击提升", "压制"]
NEW = ["新增武器", "5星", "意志提升", "电磁伤害提升", "迸发"]
CUSTOM = ["自定义武器", "5星", "智识提升", "攻击提升", "巧技"]


class WeaponUpdateTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.base = Path(self.folder.name)
        self.path = self.base / "weapon_data.csv"
        self.write_csv([OLD + ["1"], CUSTOM + ["用户屏蔽"]])
        self.original = self.path.read_bytes()
        self.memory = [{"武器": "原内存数据"}]
        self.dm = SimpleNamespace(csv_file=self.path, weapon_list=self.memory)
        self.log = Mock()
        self.updater = UpdateWeapon(self.dm, {"log": self.log})
        self.previous_session_flag = UpdateWeapon._has_updated_this_session
        UpdateWeapon._has_updated_this_session = False
        self.addCleanup(setattr, UpdateWeapon, "_has_updated_this_session", self.previous_session_flag)

    def write_csv(self, rows, fields=CSV_FIELDS):
        with self.path.open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.writer(handle)
            writer.writerow(fields)
            writer.writerows(rows)

    def assert_untouched(self):
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertIs(self.dm.weapon_list, self.memory)
        self.assertFalse(UpdateWeapon._has_updated_this_session)
        self.assertEqual(list(self.base.glob('*.tmp')), [])

    def test_merge_preserves_shields_custom_rows_and_extra_columns(self):
        fields = (*CSV_FIELDS, "备注")
        self.write_csv([OLD + ["1", "已有备注"], CUSTOM + ["用户屏蔽", "自定义备注"]], fields)
        result = merge_weapon_updates(self.path, [CHANGED, NEW])
        by_name = {row["武器"]: row for row in result.rows}
        self.assertEqual(by_name["已有武器"]["毕业词条1"], "敏捷提升")
        self.assertEqual(by_name["已有武器"]["屏蔽"], "1")
        self.assertEqual(by_name["已有武器"]["备注"], "已有备注")
        self.assertEqual(by_name["新增武器"]["屏蔽"], "")
        self.assertEqual(by_name["自定义武器"]["屏蔽"], "用户屏蔽")
        self.assertEqual(by_name["自定义武器"]["备注"], "自定义备注")
        with self.path.open(encoding='utf-8-sig', newline='') as handle:
            self.assertEqual(list(csv.DictReader(handle)), result.rows)

    def test_legacy_file_without_shield_is_upgraded_when_updated(self):
        self.write_csv([OLD, CUSTOM], CSV_FIELDS[:-1])
        result = merge_weapon_updates(self.path, [CHANGED])
        self.assertTrue(all(row["屏蔽"] == "" for row in result.rows))
        with self.path.open(encoding='utf-8-sig') as handle:
            self.assertIn("屏蔽", csv.DictReader(handle).fieldnames)

    def test_unchanged_data_does_not_rewrite_file(self):
        with patch('core.weapon_store.os.replace') as replace:
            self.assertTrue(self.updater.export_weapon_rows([OLD]))
        replace.assert_not_called()
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertTrue(UpdateWeapon._has_updated_this_session)

    def test_empty_incomplete_unknown_star_and_duplicate_batches_are_rejected(self):
        batches = ([], [["", *NEW[1:]]], [NEW[:-1]], [[*NEW[:4], " "]],
                   [[NEW[0], "未知", *NEW[2:]]], [NEW, NEW], [NEW, [*OLD[:4], None]])
        for batch in batches:
            with self.subTest(batch=batch), self.assertRaises(WeaponDataError):
                self.updater.export_weapon_rows(batch)
            self.assert_untouched()

    def test_malformed_existing_library_is_never_overwritten(self):
        header = ','.join(CSV_FIELDS)
        malformed = ('', '名称,星级\n武器,6星\n', header + '\n缺列,6星\n',
                     header + '\n' + ','.join(OLD + ['1', '多余列']) + '\n',
                     header + '\n' + (','.join(OLD + ['1']) + '\n') * 2,
                     header + ',武器\n', header + '\n,6星,力量提升,攻击提升,压制,\n',
                     header + '\n"未闭合引号')
        for content in malformed:
            with self.subTest(content=content):
                self.path.write_text(content, encoding='utf-8')
                before = self.path.read_bytes()
                with self.assertRaises((WeaponDataError, csv.Error)):
                    self.updater.export_weapon_rows([NEW])
                self.assertEqual(self.path.read_bytes(), before)
                self.assertFalse(UpdateWeapon._has_updated_this_session)

    def test_invalid_local_encoding_is_preserved(self):
        self.path.write_bytes(b'\xff\xfe\x00invalid')
        with self.assertRaises(UnicodeError):
            self.updater.export_weapon_rows([NEW])
        self.assertEqual(self.path.read_bytes(), b'\xff\xfe\x00invalid')
        self.assertFalse(UpdateWeapon._has_updated_this_session)

    def test_replace_failure_keeps_original_file_memory_and_retry_flag(self):
        with patch('core.weapon_store.os.replace', side_effect=PermissionError('file locked')):
            with self.assertRaises(PermissionError):
                self.updater.export_weapon_rows([CHANGED, NEW])
        self.assert_untouched()

    def test_write_failure_keeps_original_file_memory_and_retry_flag(self):
        with patch('core.weapon_store.os.fsync', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.updater.export_weapon_rows([NEW])
        self.assert_untouched()

    def test_missing_library_is_created_only_with_complete_data(self):
        missing = self.base / 'new.csv'
        with self.assertRaises(WeaponDataError):
            merge_weapon_updates(missing, [])
        self.assertFalse(missing.exists())
        result = merge_weapon_updates(missing, [NEW])
        self.assertTrue(missing.exists())
        self.assertEqual(result.rows[0]["武器"], NEW[0])

    def test_cancelled_update_does_not_write(self):
        self.updater.cancelled = lambda: True
        with self.assertRaises(WeaponUpdateCancelled):
            self.updater.export_weapon_rows([NEW])
        self.assert_untouched()
        with patch('core.update.fetch_weapon_rows', side_effect=WeaponUpdateCancelled):
            self.assertFalse(self.updater.__run__())
        self.assert_untouched()

    def test_empty_and_incomplete_updates_are_not_success(self):
        for rows in ([], [NEW, [*OLD[:4], ""]]):
            with self.subTest(rows=rows), patch('core.update.fetch_weapon_rows', return_value=rows):
                self.assertFalse(self.updater.__run__())
                self.assert_untouched()

    def test_http_error_and_timeout_preserve_library(self):
        with patch('core.update.fetch_weapon_rows', side_effect=requests.HTTPError('503 unavailable')):
            self.assertFalse(self.updater.__run__())
        self.assert_untouched()
        with patch('core.update.fetch_weapon_rows', side_effect=requests.Timeout('timeout')):
            self.assertFalse(self.updater.__run__())
        self.assert_untouched()

    def test_failed_save_can_be_retried_and_success_is_cached(self):
        with patch('core.update.fetch_weapon_rows', return_value=[NEW]) as get:
            with patch('core.weapon_store.os.replace', side_effect=PermissionError('locked')):
                self.assertFalse(self.updater.__run__())
            self.assert_untouched()
            self.assertTrue(self.updater.__run__())
            self.assertTrue(UpdateWeapon._has_updated_this_session)
            self.assertTrue(self.updater.__run__())
            self.assertEqual(get.call_count, 2)

    def test_update_does_not_touch_personal_settings_or_records(self):
        files = (self.base / 'config.json', self.base / 'best_records.json')
        for path in files:
            path.write_text('{"personal": true}', encoding='utf-8')
        self.updater.export_weapon_rows([NEW])
        for path in files:
            self.assertEqual(path.read_text(encoding='utf-8'), '{"personal": true}')


if __name__ == '__main__':
    unittest.main()
