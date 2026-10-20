"""Read public FZ Wiki articles over HTTP; no login or browser is required."""

from dataclasses import dataclass
import re

import requests

from core.weapon_store import WEAPON_FIELDS, WeaponDataError


ARTICLE_API = "https://api.fz.wiki/api/v1/articles/by-title"
WEAPON_PAGE = "https://www.fz.wiki/wiki/武器"
TERM_FIELDS = ("termsMain", "termsSub", "termsSkill")
# Verified against the attribute labels in 白夜新星 and 遗忘 detail articles.
TERM_ALIASES = {"源石技艺提升": "源石技艺强度提升", "法术伤害提升": "法术提升"}


class WeaponUpdateCancelled(Exception):
    pass


@dataclass(frozen=True)
class WeaponEntry:
    name: str
    rarity: int
    title: str
    terms: tuple[str, str, str] | None

    def row(self):
        return [self.name, f"{self.rarity}星", *self.terms] if self.terms else None


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise WeaponDataError(f"FZ Wiki {label}为空或格式错误")
    return value.strip()


def _term(value, position):
    text = _text(value, "词条")
    text = TERM_ALIASES.get(text, text)
    # A description, full skill name or multi-value field is not a substrate term.
    if not re.fullmatch(r"[\u4e00-\u9fff]{2,24}", text):
        raise WeaponDataError(f"FZ Wiki 词条格式无法确认: {text}")
    if position < 2 and not text.endswith("提升"):
        raise WeaponDataError(f"FZ Wiki 属性词条无法确认: {text}")
    if position == 2 and text.endswith("提升"):
        raise WeaponDataError(f"FZ Wiki 特殊词条无法确认: {text}")
    return text


def _nodes(node):
    if not isinstance(node, dict):
        raise WeaponDataError("FZ Wiki 文档节点格式错误")
    yield node
    children = node.get("content", [])
    if not isinstance(children, list):
        raise WeaponDataError("FZ Wiki 文档内容格式错误")
    for child in children:
        yield from _nodes(child)


def _document(payload, title):
    if not isinstance(payload, dict):
        raise WeaponDataError("FZ Wiki 响应不是文章对象")
    article, revision = payload.get("article"), payload.get("revision")
    if not isinstance(article, dict) or not isinstance(revision, dict):
        raise WeaponDataError("FZ Wiki 缺少文章或当前修订")
    if (article.get("title") != title or type(article.get("namespace")) is not int
            or article["namespace"] != 0
            or article.get("status") != "ACTIVE" or article.get("readVisibility") != "PUBLIC"):
        raise WeaponDataError(f"FZ Wiki 返回的不是公开有效条目: {title}")
    article_id = _text(article.get("id"), "文章编号")
    revision_id = _text(article.get("currentRevisionId"), "修订编号")
    if revision.get("id") != revision_id or revision.get("articleId") != article_id:
        raise WeaponDataError(f"FZ Wiki 文章与修订不一致: {title}")
    doc = revision.get("contentJson")
    if not isinstance(doc, dict) or doc.get("type") != "doc" or not isinstance(doc.get("content"), list):
        raise WeaponDataError(f"FZ Wiki 文章内容不完整: {title}")
    return doc


def parse_catalog(payload):
    """The by-title API returns the whole roster in one article, without paging."""
    doc = _document(payload, "武器")
    tables = [n for n in _nodes(doc) if n.get("type") == "wikiIndexTable"
              and isinstance(n.get("attrs"), dict) and n["attrs"].get("id") == "roster"]
    if len(tables) != 1:
        raise WeaponDataError("FZ Wiki 武器总表缺失或不唯一")
    entries = tables[0]["attrs"].get("entries")
    if not isinstance(entries, list) or not entries:
        raise WeaponDataError("FZ Wiki 武器总表为空或格式错误")
    by_name = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise WeaponDataError("FZ Wiki 武器记录格式错误")
        name = _text(entry.get("name"), "武器名称")
        title = _text(entry.get("title"), "详情标题")
        rarity = entry.get("rarity")
        if type(rarity) is not int or rarity not in range(1, 7):
            raise WeaponDataError(f"FZ Wiki 星级无法确认: {name}")
        if title != f"武器/{name}":
            raise WeaponDataError(f"FZ Wiki 详情关联错误或武器重复: {name}")
        if rarity < 5:
            continue
        fields = [entry.get(key) for key in TERM_FIELDS]
        if any(not isinstance(field, list) or len(field) > 1 for field in fields):
            raise WeaponDataError(f"FZ Wiki 总表词条格式错误: {name}")
        terms = tuple(_term(field[0], i) for i, field in enumerate(fields)) if all(fields) else None
        candidate = WeaponEntry(name, rarity, title, terms)
        previous = by_name.get(name)
        if previous is None:
            by_name[name] = candidate
            continue
        # The roster can repeat a name for a skin/variant article that publishes
        # no terms (for example 宏愿 and the *_ink row). Keep the canonical row
        # that actually carries terms; any other disagreement is still an error.
        if (previous.rarity == candidate.rarity
                and previous.terms != candidate.terms
                and (previous.terms is None) != (candidate.terms is None)):
            by_name[name] = candidate if candidate.terms else previous
            continue
        raise WeaponDataError(f"FZ Wiki 详情关联错误或武器重复: {name}")
    result = list(by_name.values())
    if not result:
        raise WeaponDataError("FZ Wiki 没有五星或六星武器")
    return result


def parse_weapon_detail(payload, entry):
    doc = _document(payload, entry.title)
    nodes = list(_nodes(doc))
    heroes = [n.get("attrs") for n in nodes if n.get("type") == "endfieldCardWeaponHero"]
    if len(heroes) != 1 or not isinstance(heroes[0], dict):
        raise WeaponDataError(f"FZ Wiki 武器资料缺失或重复: {entry.name}")
    hero = heroes[0]
    if hero.get("name") != entry.name or type(hero.get("rarity")) is not int or hero["rarity"] != entry.rarity:
        raise WeaponDataError(f"FZ Wiki 详情名称或星级与目录不一致: {entry.name}")
    skills = [n for n in nodes if n.get("type") == "endfieldCardWeaponSkills"]
    if len(skills) > 1:
        raise WeaponDataError(f"FZ Wiki 技能区域不唯一: {entry.name}")
    if skills:
        block = skills[0]
        attrs = block.get("attrs")
        table = attrs.get("attributeTable") if isinstance(attrs, dict) else None
        rows = table.get("rows") if isinstance(table, dict) else None
        if not isinstance(rows, list) or len(rows) != 2 or any(not isinstance(row, dict) for row in rows):
            raise WeaponDataError(f"FZ Wiki 基础或附加属性不完整: {entry.name}")
        labels = [_text(row.get("label"), "属性名称") for row in rows]
        terms = [re.sub(r"·(?:小|中|大)$", "", label) for label in labels]
        special = [n.get("attrs", {}).get("data") for n in _nodes(block)
                   if n.get("type") == "wikiCardItem" and isinstance(n.get("attrs"), dict)
                   and n["attrs"].get("itemType") == "endfieldCardWeaponSkills__skills"]
        if len(special) != 1 or not isinstance(special[0], dict):
            raise WeaponDataError(f"FZ Wiki 特殊技能缺失或重复: {entry.name}")
        name = _text(special[0].get("name"), "特殊技能名称")
        parts = name.split("·")
        if len(parts) != 2 or not all(part.strip() for part in parts):
            raise WeaponDataError(f"FZ Wiki 特殊技能分类无法确认: {entry.name}")
        # The explicit separator identifies the whole category, never the first two characters.
        terms.append(parts[0])
    else:
        # Preview articles publish three named terms in the hero metadata.
        meta = hero.get("meta")
        if not isinstance(meta, list):
            raise WeaponDataError(f"FZ Wiki 预告技能缺失: {entry.name}")
        values = [row.get("value") for row in meta if isinstance(row, dict) and row.get("label") == "技能"]
        if len(values) != 1:
            raise WeaponDataError(f"FZ Wiki 预告技能缺失或重复: {entry.name}")
        terms = re.split("[；;]", _text(values[0], "预告技能"))
        if len(terms) != 3:
            raise WeaponDataError(f"FZ Wiki 预告三条技能不完整: {entry.name}")
    return [entry.name, f"{entry.rarity}星", *(_term(term, i) for i, term in enumerate(terms))]


def _check_cancelled(cancelled):
    if cancelled():
        raise WeaponUpdateCancelled()


def _fetch_article(session, title, cancelled):
    _check_cancelled(cancelled)
    response = session.get(
        ARTICLE_API, params={"ns": 0, "title": title, "withRevision": 1},
        headers={"Accept": "application/json", "Cache-Control": "no-cache"},
        timeout=10, allow_redirects=False,
    )
    response.raise_for_status()
    if response.status_code != 200:
        raise WeaponDataError(f"FZ Wiki 接口状态异常: HTTP {response.status_code}")
    _check_cancelled(cancelled)
    try:
        return response.json()
    except ValueError as exc:
        raise WeaponDataError("FZ Wiki 返回的不是有效 JSON") from exc


def fetch_weapon_rows(existing_rows=(), cancelled=lambda: False):
    """Verify additions/changes in their detail articles before any library write.

    A roster row already matching the local library needs no detail request.
    Preview rows and differing rows always use details, since the roster can lag
    behind an edited detail (as observed for 黄金时代).
    """
    existing = {row["武器"]: [row.get(k, "").strip() for k in WEAPON_FIELDS]
                for row in existing_rows}
    with requests.Session() as session:
        entries = parse_catalog(_fetch_article(session, "武器", cancelled))
        weapons = []
        for entry in entries:
            _check_cancelled(cancelled)
            row = entry.row()
            if row is None or existing.get(entry.name) != row:
                row = parse_weapon_detail(_fetch_article(session, entry.title, cancelled), entry)
            weapons.append(row)
    _check_cancelled(cancelled)
    return weapons
