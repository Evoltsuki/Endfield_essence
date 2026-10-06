import itertools
import unittest
from core.potential import get_rules, matches_potential


class PotentialRulesTests(unittest.TestCase):
    def test_defaults_preserve_previous_decisions(self):
        skills = ['敏捷提升', '攻击提升', '迸发']
        for levels in itertools.product(range(1, 7), repeat=3):
            for gold in (True, False):
                expected = ((sum(levels) >= 6 or levels[2] == 3) if gold else
                            (levels[2] == 3 or levels[2] == 2 and sum(levels) >= 6))
                self.assertEqual(matches_potential({}, skills, levels, gold), expected)
        self.assertFalse(matches_potential({}, ['敏捷提升', '攻击提升', '生命提升'], [6, 6, 6], True))

    def test_custom_rules_names_and_disable(self):
        rules = get_rules({})
        rules['skill_names'] = ['终结技充能效率提升']
        rules['gold'] = [dict(enabled=True, total=10, level=4)]
        data = dict(potential_rules=rules)
        self.assertTrue(matches_potential(data, ['敏捷提升', '终结技充能效率提升', '迸发'], [3, 4, 3], True))
        self.assertFalse(matches_potential(data, ['敏捷提升', '终结技充能效率提升', '迸发'], [3, 3, 4], True))
        data['keep_potential'] = False
        self.assertFalse(matches_potential(data, ['敏捷提升', '终结技充能效率提升', '迸发'], [3, 4, 3], True))

    def test_invalid_rule_is_rejected(self):
        rules = get_rules({})
        rules['purple'][0]['level'] = 7
        with self.assertRaises(ValueError):
            get_rules(dict(potential_rules=rules))
