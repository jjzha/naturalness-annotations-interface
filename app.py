"""Side-by-side naturalness annotation of two model responses.

Run:
    streamlit run app.py -- --data data/sample.jsonl --out annotations
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
import threading
from datetime import datetime
from pathlib import Path

import streamlit as st

import core

APP_DIR = Path(__file__).resolve().parent
DEFAULT_DATA = APP_DIR / "data" / "sample.jsonl"
DEFAULT_OUT = APP_DIR / "annotations"
# Annotation guidelines, linked on the login screen, in the sidebar and next to
# the issue categories. Override with the ANNOTATION_GUIDELINES environment
# variable; set it to an empty string to hide the link.
GUIDELINES_URL = os.environ.get(
    "ANNOTATION_GUIDELINES",
    "https://docs.google.com/document/d/1Aw6SI6h3ji3qMfIlFZQ89nJTuBN0x09aMKzgJsRqMls/"
    "edit?tab=t.0#heading=h.ruz56gdbvim4",
).strip()
GUIDELINES_LABEL = "Annotation guidelines"


# --------------------------------------------------------------------------- #
# Config / cached resources
# --------------------------------------------------------------------------- #
def get_config() -> tuple[Path, Path]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--data", default=os.environ.get("ANNOTATION_DATA", str(DEFAULT_DATA)))
    parser.add_argument("--out", default=os.environ.get("ANNOTATION_OUT", str(DEFAULT_OUT)))
    args, _ = parser.parse_known_args(sys.argv[1:])
    return Path(args.data).expanduser().resolve(), Path(args.out).expanduser().resolve()


@st.cache_data(show_spinner=False)
def load_items_cached(path: str, mtime_ns: int, size: int) -> list[dict[str, str]]:
    # mtime/size are part of the cache key so an edited data file is reloaded.
    return core.load_items(path)


@st.cache_resource
def write_lock() -> threading.Lock:
    # One lock shared by all browser sessions of this server process.
    return threading.Lock()


# --------------------------------------------------------------------------- #
# Rendering helpers
# --------------------------------------------------------------------------- #
def md_escape(text: str) -> str:
    """Escape text so Streamlit markdown shows it literally."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|<>~$:=])", r"\\\1", str(text))


# Reading text size for the prompt and responses: key -> (label, CSS size).
TEXT_SIZES: dict[str, tuple[str, str]] = {
    "s": ("S", "0.9rem"),
    "m": ("M", "1rem"),
    "l": ("L", "1.25rem"),
    "xl": ("XL", "1.5rem"),
}
DEFAULT_TEXT_SIZE = "m"


def current_text_size() -> str:
    key = st.session_state.get("text_size")
    return TEXT_SIZES[key if key in TEXT_SIZES else DEFAULT_TEXT_SIZE][1]


def render_markdown_on() -> bool:
    return st.session_state.get("render_md", True) is not False


def text_box(text: str, max_height: str) -> None:
    """Show a prompt/response. With "Render markdown" on, markdown is formatted
    safely (see core.render_markdown); off, the text is shown exactly as
    written. Either way, raw HTML in the text is never executed."""
    if not text.strip():
        body, cls, ws = '<span style="opacity:.6;font-style:italic">(empty)</span>', "", "pre-wrap"
    elif render_markdown_on():
        body, cls, ws = core.render_markdown(text), "md-body", "normal"
    else:
        body, cls, ws = html.escape(text), "", "pre-wrap"
    st.html(
        f'<div dir="auto" class="{cls}" style="white-space:{ws};overflow-wrap:anywhere;'
        f"line-height:1.6;font-size:{current_text_size()};padding:.85rem 1rem;"
        "border:1.5px solid color-mix(in srgb, currentColor 35%, transparent);"
        "background:color-mix(in srgb, currentColor 4%, transparent);border-radius:.5rem;"
        f'max-height:{max_height};overflow-y:auto;">{body}</div>'
    )


# Issue buttons with a tick-box in front, plus stronger contrast. Colours are
# derived from the theme's text colour (currentColor), so they work in light and
# dark mode alike. Purely cosmetic: if a future Streamlit version renames these
# attributes, the pills still work and fall back to Streamlit's default look.
PILL_CSS = """
<style>
:is([data-testid="stForm"], .st-key-preference_box) button[data-variant="pills"] {
  position: relative;
  min-height: 2.75rem;
  padding: 0.45rem 1rem 0.45rem 2.35rem;   /* room on the left for the box */
  font-size: 1rem;
  border: 1.5px solid color-mix(in srgb, currentColor 45%, transparent);
  background-color: color-mix(in srgb, currentColor 5%, transparent);
}
:is([data-testid="stForm"], .st-key-preference_box) button[data-variant="pills"]:hover {
  border-color: #2563eb;
  background-color: color-mix(in srgb, #2563eb 12%, transparent);
}
/* The tick-box: always present (so the pill never changes size), empty when
   off, a white box with a blue checkmark when on. */
:is([data-testid="stForm"], .st-key-preference_box) button[data-variant="pills"]::before {
  content: "";
  position: absolute;
  left: 0.8rem;
  top: 50%;
  transform: translateY(-50%);
  width: 1.05rem;
  height: 1.05rem;
  box-sizing: border-box;
  border: 2px solid color-mix(in srgb, currentColor 75%, transparent);
  border-radius: 0.25rem;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.8rem;
  font-weight: 800;
  line-height: 1;
}
:is([data-testid="stForm"], .st-key-preference_box) button[data-variant="pills"]:is([aria-pressed="true"], [aria-checked="true"]) {
  background-color: #2563eb;
  border-color: #2563eb;
  color: #ffffff;
}
:is([data-testid="stForm"], .st-key-preference_box) button[data-variant="pills"]:is([aria-pressed="true"], [aria-checked="true"]):hover {
  background-color: #1d4ed8;
  border-color: #1d4ed8;
  color: #ffffff;
}
:is([data-testid="stForm"], .st-key-preference_box) button[data-variant="pills"]:is([aria-pressed="true"], [aria-checked="true"])::before {
  content: "\\2713";
  background-color: #ffffff;
  border-color: #ffffff;
  color: #2563eb;
}
/* "No issues" (the first issue button) turns green instead of blue. */
[data-testid="stForm"] [role="toolbar"] > button[data-variant="pills"]:first-child:is([aria-pressed="true"]),
[data-testid="stForm"] [role="toolbar"] > button[data-variant="pills"]:first-child:is([aria-pressed="true"]):hover {
  background-color: #15803d;
  border-color: #15803d;
  color: #ffffff;
}
[data-testid="stForm"] [role="toolbar"] > button[data-variant="pills"]:first-child[aria-pressed="true"]::before {
  color: #15803d;
}
/* Overall preference: only one choice, so a round marker instead of a box. */
.st-key-preference_box button[data-variant="pills"]::before {
  border-radius: 50%;
}
.st-key-preference_box button[data-variant="pills"]:is([aria-pressed="true"], [aria-checked="true"])::before {
  content: "";
  background: radial-gradient(circle, #2563eb 0 40%, #ffffff 46%);
}
/* Rendered markdown inside the text boxes. Sizes are in em, so they follow
   the S / M / L / XL text size. */
/* Streamlit's page styles give p/li a fixed size; follow the chosen size. */
.md-body p, .md-body ul, .md-body ol, .md-body li, .md-body table,
.md-body thead, .md-body tbody, .md-body tr, .md-body td, .md-body th,
.md-body blockquote, .md-body pre, .md-body span, .md-body strong,
.md-body em, .md-body s {
  font-size: inherit !important; line-height: inherit;
}
.md-body > :first-child { margin-top: 0; }
.md-body > :last-child { margin-bottom: 0; }
.md-body p, .md-body ul, .md-body ol, .md-body pre, .md-body blockquote,
.md-body table { margin: 0 0 0.75em 0; }
.md-body h1, .md-body h2, .md-body h3, .md-body h4, .md-body h5, .md-body h6 {
  margin: 0.9em 0 0.4em 0; padding: 0; line-height: 1.3; font-weight: 700;
}
.md-body h1 { font-size: 1.45em; }
.md-body h2 { font-size: 1.3em; }
.md-body h3 { font-size: 1.15em; }
.md-body h4, .md-body h5, .md-body h6 { font-size: 1em; }
.md-body ul, .md-body ol { padding-left: 1.6em; }
.md-body li { margin: 0.15em 0; }
.md-body code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.9em; padding: 0.1em 0.35em; border-radius: 0.3em;
  background: color-mix(in srgb, currentColor 10%, transparent);
}
.md-body pre {
  white-space: pre-wrap; padding: 0.7em 0.9em; border-radius: 0.4em;
  background: color-mix(in srgb, currentColor 8%, transparent);
}
.md-body pre code { padding: 0; background: none; font-size: 0.9em; }
.md-body blockquote {
  margin-left: 0; padding-left: 0.85em;
  border-left: 3px solid color-mix(in srgb, currentColor 40%, transparent);
}
.md-body table { border-collapse: collapse; display: block; overflow-x: auto; }
.md-body th, .md-body td {
  border: 1px solid color-mix(in srgb, currentColor 35%, transparent);
  padding: 0.3em 0.65em; text-align: left;
}
.md-body hr {
  border: 0; margin: 1em 0;
  border-top: 1px solid color-mix(in srgb, currentColor 35%, transparent);
}
.md-link { text-decoration: underline dotted; cursor: help; }
.md-img { font-style: italic; opacity: 0.75; }
/* Bigger headings above the buttons. */
:is([data-testid="stForm"], .st-key-preference_box) [data-testid="stButtonGroup"] [data-testid="stWidgetLabel"] p {
  font-size: 1.05rem;
}
</style>
"""


def wkey(annotator: str, item_id: str, *parts: str) -> str:
    # Widget keys include annotator + item id, so state never leaks between items.
    return "|".join(("w", annotator, item_id, *parts))


# --------------------------------------------------------------------------- #
# Callbacks (run before the script re-executes)
# --------------------------------------------------------------------------- #
def cb_go(index: int, n: int) -> None:
    st.session_state.idx = max(0, min(n - 1, index))


def cb_goto(n: int) -> None:
    value = st.session_state.get("goto")
    if value is not None:
        st.session_state.idx = max(0, min(n - 1, int(value) - 1))


def cb_switch_annotator() -> None:
    size = st.session_state.get("text_size")
    md_on = st.session_state.get("render_md")
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.query_params.clear()
    # Keep the reader's display settings.
    if size in TEXT_SIZES:
        st.session_state.text_size = size
        st.query_params["text"] = size
    if isinstance(md_on, bool):
        st.session_state.render_md = md_on
        st.query_params["md"] = "1" if md_on else "0"


def cb_render_md() -> None:
    st.query_params["md"] = "1" if render_markdown_on() else "0"


def cb_text_size() -> None:
    # Remember the choice in the URL so it survives a page reload.
    size = st.session_state.get("text_size")
    if size in TEXT_SIZES:
        st.query_params["text"] = size


def cb_save(
    annotator: str,
    item_id: str,
    path: str,
    data_file: str,
    next_index: int | None,
    is_last: bool,
) -> None:
    ss = st.session_state
    preference = ss.get(wkey(annotator, item_id, "preference"))
    if preference not in core.PREFERENCE_KEYS:
        ss.flash = ("error", "Not saved: choose an overall judgement (A better, equally good, "
                             "equally bad or B better) first.")
        return
    issues, problems = {}, []
    for side in core.SIDES:
        picked = ss.get(wkey(annotator, item_id, side, "issues")) or []
        problem = core.issue_choice_error(side, picked)
        if problem:
            problems.append(problem)
        issues[side] = [k for k in core.CATEGORY_KEYS if k in picked]
    if problems:
        ss.flash = ("error", "Not saved. " + " ".join(problems))
        return
    comment = ss.get(wkey(annotator, item_id, "comment"), "") or ""
    entry = core.make_entry(issues["A"], issues["B"], preference, comment)
    try:
        with write_lock():
            core.save_annotation(Path(path), annotator, data_file, item_id, entry)
    except (core.StoreError, OSError) as e:
        ss.flash = ("error", f"NOT saved: {e}")
        return
    if next_index is not None:
        ss.idx = next_index
        ss.flash = ("success", "Saved.")
    elif is_last:
        ss.flash = ("success", "Saved. That was the last item.")
    else:
        ss.flash = ("success", "Saved.")


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #
def login(items: list[dict], data_path: Path, out_dir: Path) -> None:
    ss = st.session_state
    from_url = core.sanitize_name(st.query_params.get("annotator", ""))
    if from_url:
        name = from_url
    else:
        st.title("Naturalness annotation")
        st.write(f"Data file: `{data_path.name}` ({len(items)} items)")
        if GUIDELINES_URL:
            st.markdown(f"Please read the [{GUIDELINES_LABEL}]({GUIDELINES_URL}) before you start.")
        with st.form("login"):
            raw = st.text_input("Annotator ID", key="login_name", placeholder="e.g. your initials")
            submitted = st.form_submit_button("Start", type="primary", key="login_btn")
        if not submitted:
            st.stop()
        name = core.sanitize_name(raw)
        if not name:
            st.error("Please enter an annotator ID (letters, digits, '-', '_' or '.').")
            st.stop()

    try:
        annotations = core.read_store(core.store_path(out_dir, data_path, name))
    except core.StoreError as e:
        st.error(f"Cannot open the annotation file for this annotator: {md_escape(e)}")
        st.stop()
    ss.annotator = name
    start = core.first_unannotated(items, annotations)
    ss.idx = start if start is not None else 0
    st.query_params["annotator"] = name
    st.rerun()


def main() -> None:
    st.set_page_config(page_title="Naturalness annotation", page_icon="📝", layout="wide")
    st.html(PILL_CSS)
    ss = st.session_state
    data_path, out_dir = get_config()

    # ---- data ---------------------------------------------------------------
    if not data_path.is_file():
        st.error(f"Data file not found: {md_escape(data_path)}")
        st.stop()
    try:
        stat = data_path.stat()
        items = load_items_cached(str(data_path), stat.st_mtime_ns, stat.st_size)
    except core.DataError as e:
        st.error(f"Problem in data file {md_escape(data_path.name)}: {md_escape(e)}")
        st.stop()
    except OSError as e:
        st.error(f"Cannot read data file: {md_escape(e)}")
        st.stop()
    n = len(items)

    # ---- annotator ----------------------------------------------------------
    if "annotator" not in ss:
        login(items, data_path, out_dir)  # stops or reruns
    annotator: str = ss.annotator
    path = core.store_path(out_dir, data_path, annotator)
    try:
        annotations = core.read_store(path)
    except core.StoreError as e:
        st.error(
            f"Cannot read annotation file, so nothing will be saved to avoid data loss: "
            f"{md_escape(e)}"
        )
        st.stop()

    ss.idx = max(0, min(n - 1, int(ss.get("idx", 0))))
    idx: int = ss.idx
    item = items[idx]
    item_id = item["id"]
    saved = annotations.get(item_id)
    done = core.count_complete(items, annotations)

    flash = ss.pop("flash", None)
    if flash:
        st.toast(flash[1], icon="✅" if flash[0] == "success" else "⚠️")

    # ---- sidebar ------------------------------------------------------------
    with st.sidebar:
        st.markdown(f"**Annotator:** {md_escape(annotator)}")
        st.button("Switch annotator", on_click=cb_switch_annotator, key="switch_btn")
        if GUIDELINES_URL:
            st.link_button(GUIDELINES_LABEL, GUIDELINES_URL, icon=":material/menu_book:")
        st.divider()
        st.progress(done / n, text=f"{done} / {n} items annotated")
        if done == n:
            st.success("All items annotated. Thank you!")
        ss.goto = idx + 1  # keep the number box in sync with the current item
        st.number_input(
            "Go to item #", min_value=1, max_value=n, step=1, key="goto",
            on_change=cb_goto, args=(n,),
        )
        nxt = core.first_unannotated(items, annotations, start=(idx + 1) % n)
        st.button(
            "Next unannotated item",
            on_click=cb_go, args=(nxt if nxt is not None else idx, n),
            disabled=nxt is None, key="next_unann_btn",
        )
        st.divider()
        st.download_button(
            "Download my annotations (CSV)",
            data=core.to_csv_bytes(core.csv_rows(items, annotations, annotator)),
            file_name=f"{path.parent.name}_{annotator}.csv",
            mime="text/csv",
            disabled=done == 0,
            key="download_btn",
        )
        try:
            shown_path = path.relative_to(Path.cwd())
        except ValueError:
            shown_path = path
        st.caption(f"Data: {md_escape(data_path.name)}  \nSaved to: {md_escape(shown_path)}")
        if st.session_state.get("text_size") not in TEXT_SIZES:
            from_url = st.query_params.get("text", DEFAULT_TEXT_SIZE)
            ss.text_size = from_url if from_url in TEXT_SIZES else DEFAULT_TEXT_SIZE
        st.segmented_control(
            "Text size",
            options=list(TEXT_SIZES),
            format_func=lambda k: TEXT_SIZES[k][0],
            required=True,
            key="text_size",
            on_change=cb_text_size,
            help="Size of the prompt and response text (S, M, L, XL). "
                 "To enlarge everything, use your browser zoom (Ctrl/Cmd and +).",
        )
        if not isinstance(st.session_state.get("render_md"), bool):
            ss.render_md = st.query_params.get("md", "1") != "0"
        st.toggle(
            "Render markdown",
            key="render_md",
            on_change=cb_render_md,
            help="On: headings, bold, lists, tables and code are formatted. "
                 "Off: the raw text exactly as the model wrote it "
                 "(e.g. **bold** with the asterisks).",
        )
        st.caption("Light / dark background: ⋮ menu (top right).")

    # ---- header + navigation ------------------------------------------------
    # Title on the left, buttons on the right; on narrow screens the buttons
    # wrap below the title instead of being squeezed.
    header = st.container(horizontal=True, vertical_alignment="center", gap="medium")
    head = header.container(width="stretch")
    nav = header.container(horizontal=True, width="content", gap="small")
    with head:
        st.markdown(f"#### Item {idx + 1} / {n}  ·  ID {md_escape(item_id)}")
        if saved:
            stamp = core._to_text(saved.get("updated_at", ""))
            try:
                stamp = datetime.fromisoformat(stamp).strftime("%Y-%m-%d %H:%M UTC")
            except ValueError:
                pass
            if core.is_complete(saved):
                st.badge(f"Saved {stamp}", icon=":material/check:", color="green")
            else:
                st.badge(f"Saved {stamp} without a preference: please choose one",
                         icon=":material/warning:", color="orange")
        else:
            st.badge("Not saved yet", color="gray")
    nav.button("← Previous", on_click=cb_go, args=(idx - 1, n),
               disabled=idx == 0, key="prev_btn")
    nav.button("Next →", on_click=cb_go, args=(idx + 1, n),
               disabled=idx == n - 1, key="next_btn")

    st.markdown("**Prompt**")
    text_box(item["prompt"], max_height="30vh")

    # ---- the two responses ---------------------------------------------------
    col_a, col_b = st.columns(2, gap="large")
    for side, col in zip(core.SIDES, (col_a, col_b)):
        with col.container(border=True, height="stretch"):
            st.markdown(f"#### Response {side}")
            text_box(item[f"response_{side.lower()}"], max_height="60vh")

    # ---- step 1: overall judgement (required) --------------------------------
    # Outside the form so that choosing it immediately reveals step 2. Once
    # chosen it can be changed but not cleared (required=True), so the issue
    # buttons never disappear again and no selections are lost.
    saved_pref = core.preference_of(saved)
    pref_labels = dict(core.PREFERENCES)
    pref_key = wkey(annotator, item_id, "preference")
    with st.container(key="preference_box"):  # CSS hook: button styling
        st.pills(
            "**1. Overall, how do A and B compare?** (required)",
            options=core.PREFERENCE_KEYS,
            format_func=lambda k: pref_labels[k],
            selection_mode="single",
            default=saved_pref,
            required=True,
            key=pref_key,
            wrap=True,
        )
    if ss.get(pref_key) not in core.PREFERENCE_KEYS:
        st.info("Choose the overall judgement first. The issue categories appear after that.")
        st.caption("Previous / Next do not save. Use the Save buttons to store your judgement.")
        return

    # ---- step 2: issues, comment, save ---------------------------------------
    with st.form(key=wkey(annotator, item_id, "form"), border=False):
        st.markdown("**2. Issues** (required for both A and B)")
        st.caption(
            f'For each response, click every issue you see, or "{core.NO_ISSUES_LABEL}" '
            "if it has none. Click again to unselect."
            + (f" Unsure what a category covers? See the [{GUIDELINES_LABEL.lower()}]({GUIDELINES_URL})."
               if GUIDELINES_URL else "")
        )
        col_a, col_b = st.columns(2, gap="large")
        for side, col in zip(core.SIDES, (col_a, col_b)):
            with col.container(border=True, height="stretch"):
                st.pills(
                    f"**Issues in {side}**",
                    options=core.ISSUE_OPTIONS,
                    format_func=lambda k: core.ISSUE_LABELS[k],
                    selection_mode="multi",
                    default=core.default_issue_choice(saved, side),
                    key=wkey(annotator, item_id, side, "issues"),
                    wrap=True,  # move to extra rows when the screen is narrow
                )

        st.text_area(
            "Comment (optional)",
            value=core._to_text(saved.get("comment", "")) if saved else "",
            key=wkey(annotator, item_id, "comment"),
            height=80,
        )
        save_args = dict(
            annotator=annotator, item_id=item_id, path=str(path),
            data_file=str(data_path), is_last=idx == n - 1,
        )
        b1, b2, _ = st.columns([1, 1, 4])
        with b1:
            st.form_submit_button(
                "Save & next →", type="primary", on_click=cb_save,
                kwargs={**save_args, "next_index": idx + 1 if idx < n - 1 else None},
                key="save_next_btn", width="stretch",
            )
        with b2:
            st.form_submit_button(
                "Save", on_click=cb_save, kwargs={**save_args, "next_index": None},
                key="save_btn", width="stretch",
            )
    if flash and flash[0] == "error":
        st.error(md_escape(flash[1]))  # shown right under the Save buttons
    st.caption("Previous / Next do not save. Use the Save buttons to store your judgement.")


if __name__ == "__main__":
    main()
