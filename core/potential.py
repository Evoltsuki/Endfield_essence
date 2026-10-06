"""可配置潜力规则；默认值兼容原金色/紫色保留策略。"""
from copy import deepcopy

DEFAULT_RULES = {
    "skill_names": [],
    "gold": [{"enabled": True, "total": 6, "level": 0}, {"enabled": True, "total": 0, "level": 3}],
    "purple": [{"enabled": True, "total": 0, "level": 3}, {"enabled": True, "total": 6, "level": 2}],
}


def get_rules(data):
    rules = deepcopy(data.get("potential_rules", DEFAULT_RULES))
    if not isinstance(rules, dict) or not isinstance(rules.get("skill_names"), list):
        raise ValueError("潜力规则格式错误")
    if not all(isinstance(name, str) and name.strip() for name in rules['skill_names']):
        raise ValueError("特殊词条名称不能为空")
    for rarity in ("gold", "purple"):
        if not isinstance(rules.get(rarity), list):
            raise ValueError("潜力规则缺少品质分类")
        for rule in rules[rarity]:
            if (type(rule.get("enabled")) is not bool or type(rule.get("total")) is not int
                    or type(rule.get("level")) is not int or not 0 <= rule['total'] <= 18
                    or not 0 <= rule['level'] <= 6):
                raise ValueError("总等级应为0–18，特殊词条等级应为0–6")
    return rules


def matches_potential(data, skills, levels, gold):
    if not data.get("keep_potential", True):
        return False
    rules = get_rules(data)
    names = rules['skill_names']
    special = [level for skill, level in zip(skills, levels)
               if (skill in names if names else len(skill) == 2)]
    return bool(special) and any(rule['enabled'] and sum(levels) >= rule['total']
                                and (rule['level'] == 0 or rule['level'] in special)
                                for rule in rules['gold' if gold else 'purple'])
