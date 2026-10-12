"""Validate and atomically merge weapon updates without touching personal data."""

import csv
from dataclasses import dataclass
import os
from pathlib import Path
import tempfile


WEAPON_FIELDS = ("武器", "星级", "毕业词条1", "毕业词条2", "毕业词条3")
CSV_FIELDS = (*WEAPON_FIELDS, "屏蔽")


class WeaponDataError(ValueError):
    """The update or existing library is incomplete; keep the original file."""


@dataclass
class WeaponMergeResult:
    rows: list[dict[str, str]]
    additions: list[dict[str, str]]
    modifications: list[dict[str, str]]


def _validate_incoming(weapons):
    incoming = []
    names = set()
    for weapon in weapons:
        if len(weapon) != len(WEAPON_FIELDS) or any(
            not isinstance(value, str) or not value.strip() for value in weapon
        ):
            raise WeaponDataError("武器名称、星级或三条毕业词条不完整")
        row = dict(zip(WEAPON_FIELDS, (value.strip() for value in weapon)))
        if row["星级"] not in ("5星", "6星"):
            raise WeaponDataError(f"武器星级不符合更新范围: {row['武器']}")
        if row["武器"] in names:
            raise WeaponDataError(f"更新数据中存在重复武器: {row['武器']}")
        names.add(row["武器"])
        incoming.append(row)
    if not incoming:
        raise WeaponDataError("未获取到完整的五星或六星武器数据")
    return incoming


def _read_existing(path):
    if not path.exists():
        return list(CSV_FIELDS), []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, strict=True)
        fields = next(reader, [])
        if (not set(WEAPON_FIELDS).issubset(fields)
                or len(fields) != len(set(fields)) or any(not f.strip() for f in fields)):
            raise WeaponDataError("本地武器库表头不完整或重复，已保留原文件")
        rows = []
        names = set()
        for values in reader:
            if not values:
                continue
            if len(values) != len(fields):
                raise WeaponDataError(f"本地武器库第 {reader.line_num} 行列数不正确")
            row = dict(zip(fields, values))
            name = row["武器"].strip()
            if not name or name in names:
                raise WeaponDataError(f"本地武器库第 {reader.line_num} 行名称为空或重复")
            names.add(name)
            row.setdefault("屏蔽", "")
            rows.append(row)
        if "屏蔽" not in fields:
            fields.append("屏蔽")
    return fields, rows


def _atomic_write(path, fields, rows):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8-sig", newline="", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def merge_weapon_updates(csv_filename, weapons):
    """Save a complete update; retain local-only rows, shields and extra columns.

    The caller supplies source records in WEAPON_FIELDS order. Any malformed
    record rejects the batch before writing. Returned rows can refresh the
    in-memory library without a second fallible file read.
    """
    incoming = _validate_incoming(weapons)
    path = Path(csv_filename)
    fields, existing = _read_existing(path)
    by_name = {row["武器"].strip(): row for row in existing}
    additions = []
    modifications = []
    modified_names = set()
    for weapon in incoming:
        name = weapon["武器"]
        old = by_name.get(name)
        if old is None:
            additions.append({**dict.fromkeys(fields, ""), **weapon})
        elif any(old[field].strip() != weapon[field] for field in WEAPON_FIELDS):
            modifications.append({**old, **weapon})
            modified_names.add(name)
    rows = additions + modifications + [
        row for row in existing if row["武器"].strip() not in modified_names
    ]
    if additions or modifications:
        _atomic_write(path, fields, rows)
    return WeaponMergeResult(rows, additions, modifications)
