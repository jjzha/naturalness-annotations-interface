"""Data loading, annotation storage and export (no Streamlit dependency)."""

from __future__ import annotations

import csv
import html
import io
import json
import math
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from markdown_it import MarkdownIt

# (machine key, label shown to annotators). Order = display order.
CATEGORIES: list[tuple[str, str]] = [
    ("grammar", "Grammar"),
    ("spelling", "Spelling"),
    ("punctuation", "Punctuation"),
    ("word_choice", "Word choice"),
    ("other_language", "Other language"),
    ("awkward_phrasing", "Awkward phrasing"),
    ("flow_disruptions", "Flow disruptions"),
    ("translationese", "Translationese"),
]
CATEGORY_KEYS = [k for k, _ in CATEGORIES]
SIDES = ("A", "B")

# Each side needs an explicit answer: one or more issues, or "No issues".
NO_ISSUES = "none"
NO_ISSUES_LABEL = "No issues"
ISSUE_OPTIONS = [NO_ISSUES] + CATEGORY_KEYS
ISSUE_LABELS = {NO_ISSUES: NO_ISSUES_LABEL, **dict(CATEGORIES)}

# Overall preference: (stored value, label shown to annotators). Order = display order.
PREFERENCES: list[tuple[str, str]] = [
    ("A", "A is better"),
    ("both_good", "Equally good"),
    ("both_bad", "Equally bad"),
    ("B", "B is better"),
]
PREFERENCE_KEYS = [k for k, _ in PREFERENCES]

# Accepted column names (after lower-casing and turning spaces/hyphens into "_").
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "id": ("id", "item_id", "uid", "example_id"),
    "prompt": ("prompt", "instruction", "question", "input"),
    "response_a": ("response_a", "responsea", "output_a", "answer_a"),
    "response_b": ("response_b", "responseb", "output_b", "answer_b"),
}
REQUIRED_FIELDS = ("prompt", "response_a", "response_b")
SUPPORTED_SUFFIXES = (".jsonl", ".json", ".csv", ".tsv")


class DataError(Exception):
    """The input data file cannot be used."""


class StoreError(Exception):
    """The annotation file exists but cannot be read safely."""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def sanitize_name(name: str) -> str:
    """Turn free text into a safe, case-insensitive file name component."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", (name or "").strip())
    return cleaned.strip("._").lower()[:64]


def _norm_key(key: object) -> str:
    return re.sub(r"[\s\-]+", "_", str(key).strip().lower())


def _to_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, float) and math.isnan(value):
        return ""
    if isinstance(value, (bool, int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, indent=2)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Markdown rendering (for model outputs that use markdown)
# --------------------------------------------------------------------------- #
def _link_open(self, tokens, idx, options, env):
    # Links are shown but not clickable, so a click can't navigate away from
    # the app and lose unsaved work. The target is visible on hover.
    href = tokens[idx].attrGet("href") or ""
    return f'<span class="md-link" title="{html.escape(str(href), quote=True)}">'


def _link_close(self, tokens, idx, options, env):
    return "</span>"


def _image(self, tokens, idx, options, env):
    # Never load external images; show a placeholder with the alt text.
    alt = self.renderInlineAsText(tokens[idx].children or [], options, env)
    return f'<span class="md-img">[image: {html.escape(alt)}]</span>'


_MD = (
    MarkdownIt("commonmark", {"html": False, "breaks": True})  # raw HTML stays literal text
    .enable(["table", "strikethrough"])
)
_MD.add_render_rule("link_open", _link_open)
_MD.add_render_rule("link_close", _link_close)
_MD.add_render_rule("image", _image)


def render_markdown(text: str) -> str:
    """Markdown -> safe HTML. Raw HTML in the input is escaped, single line
    breaks are kept, links are not clickable and images are not loaded."""
    return _MD.render(text)


# --------------------------------------------------------------------------- #
# Loading the (prompt, response A, response B) triples
# --------------------------------------------------------------------------- #
def _read_raw_rows(path: Path) -> list[tuple[str, dict]]:
    suffix = path.suffix.lower()
    rows: list[tuple[str, dict]] = []
    try:
        if suffix == ".jsonl":
            with path.open(encoding="utf-8-sig") as f:
                for lineno, line in enumerate(f, 1):
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError as e:
                        raise DataError(f"line {lineno}: invalid JSON ({e.msg}).") from None
                    if not isinstance(obj, dict):
                        raise DataError(f"line {lineno}: expected a JSON object.")
                    rows.append((f"line {lineno}", obj))
        elif suffix == ".json":
            with path.open(encoding="utf-8-sig") as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError as e:
                    raise DataError(f"invalid JSON at line {e.lineno} ({e.msg}).") from None
            if not isinstance(data, list):
                raise DataError("a .json file must contain a list of objects.")
            for i, obj in enumerate(data, 1):
                if not isinstance(obj, dict):
                    raise DataError(f"item {i}: expected a JSON object.")
                rows.append((f"item {i}", obj))
        elif suffix in (".csv", ".tsv"):
            limit = sys.maxsize
            while True:  # allow very long cells; sys.maxsize overflows on some platforms
                try:
                    csv.field_size_limit(limit)
                    break
                except OverflowError:
                    limit //= 10
            with path.open(encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f, delimiter="\t" if suffix == ".tsv" else ",")
                try:
                    for row in reader:
                        if not any((v or "").strip() for k, v in row.items() if k is not None):
                            continue  # skip completely empty lines
                        rows.append((f"line {reader.line_num}", row))
                except csv.Error as e:
                    raise DataError(f"line {reader.line_num}: {e}") from None
        else:
            raise DataError(
                f"unsupported file type '{suffix}'. Use one of: {', '.join(SUPPORTED_SUFFIXES)}."
            )
    except UnicodeDecodeError:
        raise DataError("file is not valid UTF-8.") from None
    return rows


def load_items(path: str | Path) -> list[dict[str, str]]:
    """Return a list of {"id", "prompt", "response_a", "response_b"} dicts."""
    path = Path(path)
    raw_rows = _read_raw_rows(path)
    if not raw_rows:
        raise DataError("the file contains no items.")

    items: list[dict[str, str]] = []
    has_id: list[bool] = []
    for where, raw in raw_rows:
        norm: dict[str, object] = {}
        for k, v in raw.items():
            if k is None:  # CSV row with more cells than header columns
                continue
            norm.setdefault(_norm_key(k), v)
        picked: dict[str, object] = {}
        for field, aliases in FIELD_ALIASES.items():
            for alias in aliases:
                if alias in norm:
                    picked[field] = norm[alias]
                    break
        missing = [f for f in REQUIRED_FIELDS if f not in picked]
        if missing:
            found = ", ".join(sorted(norm)) or "none"
            raise DataError(
                f"{where}: missing column(s) {', '.join(missing)}. Columns found: {found}."
            )
        item = {f: _to_text(picked[f]) for f in REQUIRED_FIELDS}
        if "id" in picked:
            item_id = _to_text(picked["id"]).strip()
            if not item_id:
                raise DataError(f"{where}: empty id.")
            item["id"] = item_id
            has_id.append(True)
        else:
            has_id.append(False)
        items.append(item)

    if any(has_id) and not all(has_id):
        first_missing = raw_rows[has_id.index(False)][0]
        raise DataError(f"{first_missing}: some items have an id and some do not.")
    if not any(has_id):
        for i, item in enumerate(items, 1):
            item["id"] = str(i)

    seen: dict[str, str] = {}
    for (where, _), item in zip(raw_rows, items):
        if item["id"] in seen:
            raise DataError(f"{where}: duplicate id '{item['id']}' (also at {seen[item['id']]}).")
        seen[item["id"]] = where
    return items


# --------------------------------------------------------------------------- #
# Annotation storage: one JSON file per (dataset, annotator), written atomically
# --------------------------------------------------------------------------- #
def store_path(out_dir: str | Path, data_path: str | Path, annotator: str) -> Path:
    dataset = sanitize_name(Path(data_path).stem) or "dataset"
    return Path(out_dir) / dataset / f"{annotator}.json"


def read_store(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise StoreError(f"cannot read {path}: {e}") from None
    if not isinstance(data, dict) or not isinstance(data.get("annotations"), dict):
        raise StoreError(f"{path} does not look like an annotation file.")
    return {str(k): v for k, v in data["annotations"].items() if isinstance(v, dict)}


def write_store(path: Path, annotator: str, data_file: str, annotations: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "annotator": annotator,
        "data_file": data_file,
        "categories": CATEGORY_KEYS,
        "updated_at": now_iso(),
        "annotations": annotations,
    }
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)  # atomic: the file is never half-written
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def save_annotation(
    path: Path, annotator: str, data_file: str, item_id: str, entry: dict
) -> None:
    """Re-read the file, update one item, write it back."""
    annotations = read_store(path)
    annotations[item_id] = entry
    write_store(path, annotator, data_file, annotations)


def make_entry(issues_a: list[str], issues_b: list[str], preference: str, comment: str) -> dict:
    if preference not in PREFERENCE_KEYS:
        raise ValueError(f"preference must be one of {PREFERENCE_KEYS}, got {preference!r}")
    return {
        "A": [k for k in CATEGORY_KEYS if k in set(issues_a)],
        "B": [k for k in CATEGORY_KEYS if k in set(issues_b)],
        "preference": preference,
        "comment": comment.strip(),
        "updated_at": now_iso(),
    }


def preference_of(entry: dict | None) -> str | None:
    """The saved preference, or None if missing/invalid."""
    if not entry:
        return None
    value = entry.get("preference")
    return value if value in PREFERENCE_KEYS else None


def is_complete(entry: dict | None) -> bool:
    """An item is done once it has been saved with a valid preference."""
    return preference_of(entry) is not None


def selected(entry: dict | None, side: str) -> set[str]:
    """Issue keys ticked for one side of a saved entry (robust to bad data)."""
    if not entry:
        return set()
    values = entry.get(side)
    if not isinstance(values, list):
        return set()
    return {v for v in values if v in CATEGORY_KEYS}


def issue_choice_error(side: str, picked: list[str] | None) -> str | None:
    """Why the issue selection for one side can't be saved, or None if it's fine."""
    picked = [p for p in (picked or []) if p in ISSUE_OPTIONS]
    if not picked:
        return f'Response {side}: select at least one issue, or "{NO_ISSUES_LABEL}".'
    if NO_ISSUES in picked and len(picked) > 1:
        return f'Response {side}: "{NO_ISSUES_LABEL}" can\'t be combined with other issues.'
    return None


def default_issue_choice(entry: dict | None, side: str) -> list[str]:
    """What the issue buttons show for a side: the saved issues, "No issues"
    for a saved side without issues, or nothing for an unsaved item."""
    if not entry:
        return []
    chosen = selected(entry, side)
    return [k for k in CATEGORY_KEYS if k in chosen] or [NO_ISSUES]


def first_unannotated(items: list[dict], annotations: dict, start: int = 0) -> int | None:
    n = len(items)
    for offset in range(n):
        i = (start + offset) % n
        if not is_complete(annotations.get(items[i]["id"])):
            return i
    return None


def count_complete(items: list[dict], annotations: dict) -> int:
    return sum(1 for it in items if is_complete(annotations.get(it["id"])))


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #
CSV_HEADER = (
    ["item_index", "item_id", "annotator", "preference"]
    + [f"{side}_{k}" for side in SIDES for k in CATEGORY_KEYS]
    + ["comment", "updated_at"]
)


def csv_rows(items: list[dict], annotations: dict, annotator: str) -> list[list]:
    rows = []
    for i, item in enumerate(items, 1):
        entry = annotations.get(item["id"])
        if entry is None:
            continue
        flags = []
        for side in SIDES:
            chosen = selected(entry, side)
            flags += [int(k in chosen) for k in CATEGORY_KEYS]
        rows.append(
            [i, item["id"], annotator, preference_of(entry) or ""]
            + flags
            + [_to_text(entry.get("comment", "")), _to_text(entry.get("updated_at", ""))]
        )
    return rows


def to_csv_bytes(rows: list[list]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_HEADER)
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")  # BOM so Excel shows non-ASCII correctly
