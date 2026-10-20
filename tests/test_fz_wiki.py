"""Exercise real, minimized public FZ Wiki response fixtures without network I/O."""

from copy import deepcopy
import csv
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import requests

from core.fz_wiki import (
    ARTICLE_API, WeaponUpdateCancelled, _fetch_article,
    fetch_weapon_rows, parse_catalog, parse_weapon_detail,
)
from core.update import UpdateWeapon
from core.weapon_store import CSV_FIELDS, WEAPON_FIELDS, WeaponDataError


FIXTURES = Path(__file__).parent / 'fixtures' / 'fz-wiki'


def fixture(name):
    return json.loads((FIXTURES / f'{name}.json').read_text(encoding='utf-8'))


class FzWikiTests(unittest.TestCase):
    def setUp(self):
        self.catalog = fixture('catalog')
        self.entries = {entry.name: entry for entry in parse_catalog(self.catalog)}

    def roster(self, payload=None):
        return (payload or self.catalog)['revision']['contentJson']['content'][0]['attrs']['entries']

    def local_rows(self):
        # The former 63-weapon library, built without reading or writing personal data.
        rows = []
        for entry in self.entries.values():
            row = entry.row()
            if row and entry.name not in ('点心时刻', '苦难的尽头'):
                if entry.name == '黄金时代':
                    row = ['黄金时代', '6星', '意志提升', '治疗效率提升', '追袭']
                rows.append({**dict(zip(WEAPON_FIELDS, row)), '屏蔽': '1'})
        return rows

    def response_for(self, url, **kwargs):
        self.assertEqual(url, ARTICLE_API)
        self.assertEqual(kwargs['params']['ns'], 0)
        self.assertEqual(kwargs['params']['withRevision'], 1)
        self.assertFalse(kwargs['allow_redirects'])
        self.assertEqual(kwargs['timeout'], 10)
        title = kwargs['params']['title']
        data = self.catalog if title == '武器' else fixture(title.removeprefix('武器/'))
        return Mock(status_code=200, json=Mock(return_value=data))

    def test_complete_catalog_filters_low_stars_and_normalizes_labels(self):
        self.assertEqual(len(self.roster()), 84)
        self.assertEqual(len(self.entries), 69)
        self.assertNotIn('达尔霍夫7', self.entries)
        self.assertEqual(self.entries['白夜新星'].terms[1], '源石技艺强度提升')
        self.assertEqual(self.entries['遗忘'].terms[1], '法术提升')
        self.assertIsNone(self.entries['聚合工业'].terms)

    def test_real_details_preserve_attribute_and_skill_categories(self):
        expected = {
            '白夜新星': ['6星', '主能力提升', '源石技艺强度提升', '附术'],
            '遗忘': ['6星', '智识提升', '法术提升', '夜幕'],
            '黄金时代': ['6星', '意志提升', '治疗效率提升', '追袭'],
            '点心时刻': ['5星', '力量提升', '治疗效率提升', '医疗'],
            '苦难的尽头': ['6星', '敏捷提升', '自然伤害提升', '迸发'],
        }
        for name, fields in expected.items():
            with self.subTest(name=name):
                self.assertEqual(parse_weapon_detail(fixture(name), self.entries[name]), [name, *fields])
        self.assertNotEqual(self.entries['黄金时代'].row(), ['黄金时代', *expected['黄金时代']])

    def test_all_four_preview_details_have_complete_terms(self):
        expected = {
            '聚合工业': ['意志提升', '电磁伤害提升', '迸发'],
            '唤月': ['意志提升', '攻击提升', '附术'],
            '悠久传承': ['智识提升', '寒冷伤害提升', '效益'],
            '玉中身': ['智识提升', '寒冷伤害提升', '效益'],
        }
        for name, terms in expected.items():
            with self.subTest(name=name):
                self.assertEqual(parse_weapon_detail(fixture(name), self.entries[name]), [name, '6星', *terms])

    def test_duplicate_variant_without_terms_keeps_complete_row(self):
        data = deepcopy(self.catalog)
        row = next(entry for entry in self.roster(data) if entry['name'] == '宏愿')
        variant = deepcopy(row)
        variant.update(termsMain=[], termsSub=[], termsSkill=[])
        self.roster(data).append(variant)
        entries = {entry.name: entry for entry in parse_catalog(data)}
        self.assertEqual(entries['宏愿'].terms, ('敏捷提升', '攻击提升', '附术'))
        self.assertEqual(len(entries), len(self.entries))

    def test_conflicting_duplicate_rows_are_rejected(self):
        data = deepcopy(self.catalog)
        row = next(entry for entry in self.roster(data) if entry['name'] == '宏愿')
        conflict = deepcopy(row)
        conflict['termsSkill'] = ['迸发']
        self.roster(data).append(conflict)
        with self.assertRaises(WeaponDataError):
            parse_catalog(data)

    def test_invalid_api_envelopes_are_rejected(self):
        samples = [None, [], {'error': 'unavailable'}, {'code': 10001, 'message': 'invalid device'}]
        for part, key, value in (
            ('article', 'title', '干员'), ('article', 'status', 'DELETED'),
            ('article', 'readVisibility', 'PRIVATE'), ('article', 'namespace', 1),
            ('revision', 'id', 'stale'), ('revision', 'articleId', 'different'),
            ('revision', 'contentJson', {}),
        ):
            sample = deepcopy(self.catalog)
            sample[part][key] = value
            samples.append(sample)
        for sample in samples:
            with self.subTest(sample=sample), self.assertRaises(WeaponDataError):
                parse_catalog(sample)

    def test_missing_duplicate_and_empty_rosters_are_rejected(self):
        for kind in ('missing', 'duplicate', 'empty', 'low_only'):
            data = deepcopy(self.catalog)
            content = data['revision']['contentJson']['content']
            if kind == 'missing':
                content.clear()
            elif kind == 'duplicate':
                content.append(deepcopy(content[0]))
            else:
                content[0]['attrs']['entries'] = [] if kind == 'empty' else [e for e in self.roster() if e['rarity'] < 5]
            with self.subTest(kind=kind), self.assertRaises(WeaponDataError):
                parse_catalog(data)

    def test_malformed_entries_fail_instead_of_silently_disappearing(self):
        mutations = [('rarity', None), ('rarity', True), ('rarity', '6'), ('rarity', 7),
                     ('name', ''), ('title', 'https://unrelated.invalid/'),
                     ('termsMain', None), ('termsSub', '攻击提升'),
                     ('termsSkill', ['强攻', '效益']), ('termsSkill', ['效益·完整技能'])]
        for key, value in mutations:
            data = deepcopy(self.catalog)
            self.roster(data)[0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(WeaponDataError):
                parse_catalog(data)
        data = deepcopy(self.catalog)
        self.roster(data).append(deepcopy(self.roster(data)[0]))
        with self.assertRaises(WeaponDataError):
            parse_catalog(data)

    def test_detail_identity_and_revision_must_match(self):
        for part, key, value in (('article', 'title', '武器/其他'), ('revision', 'id', 'old')):
            data = fixture('聚合工业')
            data[part][key] = value
            with self.assertRaises(WeaponDataError):
                parse_weapon_detail(data, self.entries['聚合工业'])
        for key, value in (('name', '其他'), ('rarity', 5), ('rarity', '6')):
            data = fixture('聚合工业')
            data['revision']['contentJson']['content'][0]['attrs'][key] = value
            with self.assertRaises(WeaponDataError):
                parse_weapon_detail(data, self.entries['聚合工业'])

    def test_missing_ambiguous_or_unseparated_skills_are_rejected(self):
        for mode in ('missing_attribute', 'missing_skill', 'duplicate_skill', 'no_separator', 'missing_category'):
            data = fixture('黄金时代')
            block = data['revision']['contentJson']['content'][1]
            if mode == 'missing_attribute':
                block['attrs']['attributeTable']['rows'].pop()
            elif mode == 'missing_skill':
                block['content'].clear()
            elif mode == 'duplicate_skill':
                block['content'].append(deepcopy(block['content'][0]))
            else:
                block['content'][0]['attrs']['data']['name'] = '追袭大英雄' if mode == 'no_separator' else '·大英雄'
            with self.subTest(mode=mode), self.assertRaises(WeaponDataError):
                parse_weapon_detail(data, self.entries['黄金时代'])

    def test_explicit_skill_category_is_not_truncated_to_two_characters(self):
        data = fixture('黄金时代')
        data['revision']['contentJson']['content'][1]['content'][0]['attrs']['data']['name'] = '未来分类·大英雄'
        self.assertEqual(parse_weapon_detail(data, self.entries['黄金时代'])[-1], '未来分类')

    def test_preview_missing_or_ambiguous_terms_are_rejected(self):
        for value in ('', '意志提升；迸发', '意志提升；；迸发', '意志提升；攻击提升；迸发；效益', '意志提升/攻击提升/迸发'):
            data = fixture('聚合工业')
            data['revision']['contentJson']['content'][0]['attrs']['meta'][1]['value'] = value
            with self.subTest(value=value), self.assertRaises(WeaponDataError):
                parse_weapon_detail(data, self.entries['聚合工业'])

    def test_collect_checks_new_changed_and_preview_details(self):
        with patch('core.fz_wiki.requests.Session') as factory:
            session = factory.return_value.__enter__.return_value
            session.get.side_effect = self.response_for
            rows = fetch_weapon_rows(self.local_rows())
        self.assertEqual(len(rows), 69)
        self.assertEqual(len({r[0] for r in rows}), 69)
        self.assertEqual(session.get.call_count, 8)
        self.assertIn(['黄金时代', '6星', '意志提升', '治疗效率提升', '追袭'], rows)

    def test_http_redirect_error_invalid_json_and_timeout_are_rejected(self):
        for status in (302, 429, 503):
            session = Mock()
            session.get.return_value.status_code = status
            if status >= 400:
                session.get.return_value.raise_for_status.side_effect = requests.HTTPError(str(status))
            with self.subTest(status=status), self.assertRaises((WeaponDataError, requests.HTTPError)):
                _fetch_article(session, '武器', lambda: False)
            session.get.return_value.json.assert_not_called()
        session = Mock()
        session.get.return_value.status_code = 200
        session.get.return_value.json.side_effect = ValueError('HTML instead of JSON')
        with self.assertRaises(WeaponDataError):
            _fetch_article(session, '武器', lambda: False)
        session.get.side_effect = requests.Timeout()
        with self.assertRaises(requests.Timeout):
            _fetch_article(session, '武器', lambda: False)

    def test_cancellation_before_and_during_request_stops_collection(self):
        session = Mock()
        with self.assertRaises(WeaponUpdateCancelled):
            _fetch_article(session, '武器', lambda: True)
        session.get.assert_not_called()
        cancelled = False

        def response(url, **kwargs):
            nonlocal cancelled
            cancelled = True
            return self.response_for(url, **kwargs)

        with patch('core.fz_wiki.requests.Session') as factory:
            factory.return_value.__enter__.return_value.get.side_effect = response
            with self.assertRaises(WeaponUpdateCancelled):
                fetch_weapon_rows(self.local_rows(), lambda: cancelled)

    def test_late_detail_failure_preserves_entire_library_then_retry_succeeds(self):
        previous_flag = UpdateWeapon._has_updated_this_session
        self.addCleanup(setattr, UpdateWeapon, '_has_updated_this_session', previous_flag)
        UpdateWeapon._has_updated_this_session = False
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'weapons.csv'
            memory = self.local_rows()
            with path.open('w', encoding='utf-8-sig', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
                writer.writeheader()
                writer.writerows(memory)
            before = path.read_bytes()
            dm = SimpleNamespace(csv_file=path, weapon_list=memory)
            updater = UpdateWeapon(dm, {})

            def failed_response(url, **kwargs):
                if kwargs['params']['title'] == '武器/玉中身':
                    raise requests.Timeout('last detail failed')
                return self.response_for(url, **kwargs)

            with patch('core.fz_wiki.requests.Session') as factory:
                session = factory.return_value.__enter__.return_value
                session.get.side_effect = failed_response
                self.assertFalse(updater.__run__())
                self.assertFalse(UpdateWeapon._has_updated_this_session)
                self.assertIs(dm.weapon_list, memory)
                self.assertEqual(path.read_bytes(), before)
                session.get.side_effect = self.response_for
                self.assertTrue(updater.__run__())
            self.assertEqual(len(dm.weapon_list), 69)
            by_name = {r['武器']: r for r in dm.weapon_list}
            self.assertTrue(all(by_name[r['武器']]['屏蔽'] == '1' for r in memory))
            self.assertEqual(by_name['聚合工业']['屏蔽'], '')


if __name__ == '__main__':
    unittest.main()
