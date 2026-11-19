import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import core

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "app.py")


# ------------------------------------------------------------------ core ---
def write(p: Path, text: str) -> Path:
    p.write_text(text, encoding="utf-8")
    return p


def test_load_jsonl_and_aliases(tmp_path):
    f = write(tmp_path / "d.jsonl",
              '{"ID": 7, "Prompt": "p", "Response A": "a", "response-b": "b", "extra": 1}\n\n')
    assert core.load_items(f) == [{"prompt": "p", "response_a": "a", "response_b": "b", "id": "7"}]


def test_load_csv_with_bom_newlines_and_no_ids(tmp_path):
    f = tmp_path / "d.csv"
    f.write_bytes('﻿prompt,response_a,response_b\n"line1\n\nline3","ø, æ","b"\n,,\n'.encode())
    items = core.load_items(f)
    assert items == [{"prompt": "line1\n\nline3", "response_a": "ø, æ", "response_b": "b", "id": "1"}]


def test_load_tsv_and_json(tmp_path):
    t = write(tmp_path / "d.tsv", "id\tprompt\tresponse_a\tresponse_b\nx\tp\ta\tb\n")
    assert core.load_items(t)[0]["id"] == "x"
    j = write(tmp_path / "d.json", json.dumps([{"prompt": "p", "response_a": None, "response_b": 3}]))
    assert core.load_items(j)[0] == {"prompt": "p", "response_a": "", "response_b": "3", "id": "1"}


@pytest.mark.parametrize("name,content,msg", [
    ("d.jsonl", '{"prompt": "p", "response_a": "a"}\n', "missing column(s) response_b"),
    ("d.jsonl", '{"id":1,"prompt":"p","response_a":"a","response_b":"b"}\n'
                '{"id":1,"prompt":"p","response_a":"a","response_b":"b"}\n', "duplicate id"),
    ("d.jsonl", '{"id":1,"prompt":"p","response_a":"a","response_b":"b"}\n'
                '{"prompt":"p","response_a":"a","response_b":"b"}\n', "some items have an id"),
    ("d.jsonl", '{"prompt": \n', "invalid JSON"),
    ("d.jsonl", "\n\n", "no items"),
    ("d.json", '{"a": 1}', "must contain a list"),
    ("d.txt", "x", "unsupported file type"),
    ("d.jsonl", '{"id":" ","prompt":"p","response_a":"a","response_b":"b"}\n', "empty id"),
])
def test_bad_data(tmp_path, name, content, msg):
    with pytest.raises(core.DataError, match=None) as e:
        core.load_items(write(tmp_path / name, content))
    assert msg in str(e.value)


def test_store_roundtrip_and_corruption(tmp_path):
    p = tmp_path / "ds" / "ann.json"
    assert core.read_store(p) == {}
    core.save_annotation(p, "ann", "d", "1", core.make_entry(["spelling", "grammar"], [], "A", " hi "))
    core.save_annotation(p, "ann", "d", "2", core.make_entry([], ["translationese"], "both_bad", ""))
    s = core.read_store(p)
    assert s["1"]["A"] == ["grammar", "spelling"] and s["1"]["comment"] == "hi"
    assert s["2"]["B"] == ["translationese"]
    assert not list(p.parent.glob("*.tmp"))
    p.write_text("{broken", encoding="utf-8")
    with pytest.raises(core.StoreError):
        core.read_store(p)


def test_sanitize_name():
    assert core.sanitize_name("  Mike Z. ") == "mike_z"
    assert core.sanitize_name("../../etc") == "etc"
    assert core.sanitize_name("...") == ""


# ------------------------------------------------------------------- app ---
@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "triples.jsonl"
    rows = [{"id": f"q{i}", "prompt": f"prompt {i}", "response_a": f"A{i}", "response_b": f"B{i}"}
            for i in range(1, 4)]
    data.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    out = tmp_path / "ann"
    monkeypatch.setenv("ANNOTATION_DATA", str(data))
    monkeypatch.setenv("ANNOTATION_OUT", str(out))
    return data, out


def new_app():
    at = AppTest.from_file(APP, default_timeout=30)
    return at.run()


def login(at, name="Tester"):
    at.text_input(key="login_name").input(name)
    at.button(key="login_btn").click().run()
    assert not at.exception, at.exception
    return at


class Issue:
    """One issue option inside a side's pills widget, with a checkbox-like API."""

    def __init__(self, widget, cat):
        self.widget, self.cat = widget, cat

    def check(self):
        self.widget.select(self.cat)
        return self

    def uncheck(self):
        self.widget.unselect(self.cat)
        return self

    @property
    def value(self):
        return self.cat in (self.widget.value or [])


def issue_pills(at):
    return [p for p in at.pills if p.key.endswith("|issues")]


def cb(at, side, cat, item="q1", who="tester"):
    return Issue(at.pills(key=f"w|{who}|{item}|{side}|issues"), cat)


def pref(at, item="q1", who="tester"):
    return at.pills(key=f"w|{who}|{item}|preference")


def button_keys(at):
    return {b.key for b in at.button}


def heading(at):
    return next(m.value for m in at.markdown if m.value.startswith("#### Item"))


def stored(out):
    return core.read_store(out / "triples" / "tester.json")


def test_full_flow(env):
    data, out = env
    at = new_app()
    assert not at.exception
    at = login(at)
    assert "Item 1 / 3" in heading(at)
    # step 1 only: no issues, no save buttons until a preference is chosen
    assert pref(at).value is None and issue_pills(at) == []
    assert not {"save_btn", "save_next_btn"} & button_keys(at)
    assert at.info and "Choose the overall judgement first" in at.info[0].value

    pref(at).set_value("B").run()
    assert not at.info
    assert len(issue_pills(at)) == 2
    labels = [core.NO_ISSUES_LABEL] + [label for _, label in core.CATEGORIES]
    assert all(p.options == labels and p.value == [] for p in issue_pills(at))
    cb(at, "A", "grammar").check()
    cb(at, "B", "translationese").check()
    cb(at, "B", "spelling").check()
    at.text_area(key="w|tester|q1|comment").input("note")
    at.button(key="save_next_btn").click().run()
    assert not at.exception and not at.error
    assert "Item 2 / 3" in heading(at)
    s = stored(out)
    assert s["q1"]["A"] == ["grammar"]
    assert s["q1"]["B"] == ["spelling", "translationese"]
    assert s["q1"]["comment"] == "note"
    assert s["q1"]["preference"] == "B"

    # item 2: new item starts at step 1 again
    assert pref(at, "q2").value is None and issue_pills(at) == []
    pref(at, "q2").set_value("both_good").run()
    assert all(p.value == [] for p in issue_pills(at))
    # "No issues" on both sides -> counts as annotated
    cb(at, "A", "none", item="q2").check()
    cb(at, "B", "none", item="q2").check()
    at.button(key="save_next_btn").click().run()
    assert stored(out)["q2"]["A"] == [] and "Item 3 / 3" in heading(at)

    # unsaved choices on item 3 are discarded when navigating away with Previous
    pref(at, "q3").set_value("A").run()
    cb(at, "A", "spelling", item="q3").check()
    at.button(key="prev_btn").click().run()
    assert "Item 2 / 3" in heading(at)
    assert "q3" not in stored(out)

    # go back to item 1: saved ticks are restored
    at.button(key="prev_btn").click().run()
    assert "Item 1 / 3" in heading(at)
    assert cb(at, "A", "grammar").value and cb(at, "B", "translationese").value
    assert not cb(at, "A", "spelling").value
    assert at.text_area(key="w|tester|q1|comment").value == "note"
    assert pref(at).value == "B"

    # edit item 1 and plain Save stays on it
    cb(at, "A", "grammar").uncheck()
    cb(at, "A", "none").check()
    at.button(key="save_btn").click().run()
    assert "Item 1 / 3" in heading(at)
    assert stored(out)["q1"]["A"] == []
    assert not cb(at, "A", "grammar").value and cb(at, "A", "none").value

    # go-to box and "next unannotated"
    at.number_input(key="goto").set_value(3).run()
    assert "Item 3 / 3" in heading(at)
    assert pref(at, "q3").value is None and issue_pills(at) == []  # unsaved choices gone
    at.button(key="prev_btn").click().run()
    at.button(key="next_unann_btn").click().run()
    assert "Item 3 / 3" in heading(at)

    # last item: Save & next stays, everything done
    pref(at, "q3").set_value("A").run()
    cb(at, "A", "none", item="q3").check()
    cb(at, "B", "grammar", item="q3").check()
    at.button(key="save_next_btn").click().run()
    assert "Item 3 / 3" in heading(at)
    assert set(stored(out)) == {"q1", "q2", "q3"}
    assert at.button(key="next_unann_btn").disabled
    assert not at.exception


def test_resume_and_isolation_between_annotators(env):
    data, out = env
    at = login(new_app())
    pref(at).set_value("A").run()
    cb(at, "A", "punctuation").check()
    cb(at, "B", "none").check()
    at.button(key="save_next_btn").click().run()

    # a fresh session for the same annotator resumes at the first unannotated item
    at2 = login(new_app())
    assert "Item 2 / 3" in heading(at2)

    # another annotator starts from scratch and does not see tester's ticks
    at3 = login(new_app(), "Other")
    assert "Item 1 / 3" in heading(at3)
    assert pref(at3, who="other").value is None and issue_pills(at3) == []

    # switching annotator returns to the login screen
    at3.button(key="switch_btn").click().run()
    assert at3.text_input(key="login_name") is not None
    assert not at3.exception


def test_login_requires_name(env):
    at = new_app()
    at.text_input(key="login_name").input("  ...  ")
    at.button(key="login_btn").click().run()
    assert at.error and "Please enter" in at.error[0].value


def test_query_param_login(env):
    at = AppTest.from_file(APP, default_timeout=30)
    at.query_params["annotator"] = "Tester"
    at.run()
    assert not at.exception and "Item 1 / 3" in heading(at)


def test_bad_data_file_shows_error(env, monkeypatch, tmp_path):
    bad = write(tmp_path / "bad.jsonl", '{"prompt": "x"}\n')
    monkeypatch.setenv("ANNOTATION_DATA", str(bad))
    at = new_app()
    assert not at.exception and at.error and "missing column" in at.error[0].value


def test_corrupt_annotation_file_is_not_overwritten(env):
    data, out = env
    p = out / "triples" / "tester.json"
    p.parent.mkdir(parents=True)
    p.write_text("{broken", encoding="utf-8")
    at = login(new_app())
    assert at.error and "Cannot open" in at.error[0].value
    assert p.read_text(encoding="utf-8") == "{broken"


def test_data_file_shrinks_while_in_use(env):
    data, out = env
    at = login(new_app())
    at.number_input(key="goto").set_value(3).run()
    data.write_text(json.dumps({"id": "q1", "prompt": "p", "response_a": "a", "response_b": "b"}),
                    encoding="utf-8")
    at.run()
    assert not at.exception and "Item 1 / 1" in heading(at)


def test_export(env, tmp_path):
    data, out = env
    at = login(new_app())
    pref(at).set_value("both_bad").run()
    cb(at, "A", "none").check()
    cb(at, "B", "word_choice").check()
    at.button(key="save_next_btn").click().run()
    rows = core.csv_rows(core.load_items(data), stored(out), "tester")
    assert len(rows) == 1
    header = core.CSV_HEADER
    assert rows[0][header.index("B_word_choice")] == 1
    assert rows[0][header.index("A_word_choice")] == 0
    assert rows[0][header.index("preference")] == "both_bad"


def test_make_entry_rejects_bad_preference():
    with pytest.raises(ValueError):
        core.make_entry([], [], "C", "")


def test_preference_comes_first_and_is_required(env):
    data, out = env
    at = login(new_app())
    assert pref(at).proto.required                 # cannot be cleared once chosen
    assert issue_pills(at) == [] and not {"save_btn", "save_next_btn"} & button_keys(at)
    assert not (out / "triples" / "tester.json").exists()
    pref(at).set_value("A").run()
    assert len(issue_pills(at)) == 2 and {"save_btn", "save_next_btn"} <= button_keys(at)
    cb(at, "A", "grammar").check()
    # changing the preference afterwards keeps the issue buttons
    pref(at).set_value("both_bad").run()
    assert len(issue_pills(at)) == 2
    cb(at, "A", "grammar").check()
    cb(at, "B", "none").check()
    at.button(key="save_next_btn").click().run()
    assert not at.error and "Item 2 / 3" in heading(at)
    assert stored(out)["q1"]["A"] == ["grammar"] and stored(out)["q1"]["preference"] == "both_bad"


def test_save_callback_still_refuses_missing_preference(env, monkeypatch):
    # Defence in depth: even if Save were reached without a preference, nothing is stored.
    import importlib, sys
    sys.path.insert(0, str(ROOT))
    app = importlib.import_module("app")
    fake = {}
    monkeypatch.setattr(app.st, "session_state", type("S", (dict,), {
        "__getattr__": dict.__getitem__, "__setattr__": dict.__setitem__})(fake))
    path = env[1] / "triples" / "tester.json"
    app.cb_save("tester", "q1", str(path), "d", None, False)
    assert not path.exists()
    assert app.st.session_state["flash"][0] == "error"


def test_entry_without_preference_counts_as_unfinished(env):
    data, out = env
    p = out / "triples" / "tester.json"
    p.parent.mkdir(parents=True)
    legacy = {"A": ["grammar"], "B": [], "comment": "", "updated_at": "2026-01-01T00:00:00+00:00"}
    full = {**legacy, "preference": "B"}
    p.write_text(json.dumps({"annotations": {"q1": full, "q2": legacy}}), encoding="utf-8")
    at = login(new_app())
    assert "Item 2 / 3" in heading(at)            # resumes at the incomplete item
    assert pref(at, "q2").value is None and issue_pills(at) == []
    pref(at, "q2").set_value("A").run()
    assert cb(at, "A", "grammar", item="q2").value   # saved issues come back
    assert at.sidebar.get("progress")[0].proto.text.startswith("1 / 3")


@pytest.mark.parametrize("choice", ["A", "both_good", "both_bad", "B"])
def test_every_preference_option_saves_and_reloads(env, choice):
    data, out = env
    at = login(new_app())
    assert pref(at).options == ["A is better", "Equally good", "Equally bad", "B is better"]
    pref(at).set_value(choice).run()
    cb(at, "A", "none").check()
    cb(at, "B", "none").check()
    at.button(key="save_btn").click().run()
    assert not at.exception and not at.error
    assert stored(out)["q1"]["preference"] == choice
    at.button(key="next_btn").click().run()
    at.button(key="prev_btn").click().run()
    assert pref(at).value == choice


def test_old_tie_value_counts_as_unfinished():
    assert not core.is_complete({"A": [], "B": [], "preference": "tie"})
    with pytest.raises(ValueError):
        core.make_entry([], [], "tie", "")


def font_sizes(at):
    import re as _re
    return [_re.search(r"font-size:([0-9.]+rem)", h.proto.body).group(1)
            for h in at.get("html") if "dir=\"auto\"" in h.proto.body]


def test_text_size(env):
    data, out = env
    at = login(new_app())
    assert at.segmented_control(key="text_size").value == "m"
    assert at.segmented_control(key="text_size").options == ["S", "M", "L", "XL"]
    assert font_sizes(at) == ["1rem"] * 3                 # prompt + 2 responses
    at.segmented_control(key="text_size").set_value("xl").run()
    assert not at.exception
    assert font_sizes(at) == ["1.5rem"] * 3
    assert at.query_params["text"] == "xl"
    # size is kept when moving to another item
    at.button(key="next_btn").click().run()
    assert font_sizes(at) == ["1.5rem"] * 3


def test_text_size_from_url_and_bad_value(env):
    at = AppTest.from_file(APP, default_timeout=30)
    at.query_params["annotator"] = "Tester"
    at.query_params["text"] = "l"
    at.run()
    assert not at.exception and font_sizes(at) == ["1.25rem"] * 3
    at2 = AppTest.from_file(APP, default_timeout=30)
    at2.query_params["annotator"] = "Tester"
    at2.query_params["text"] = "gigantic"
    at2.run()
    assert not at2.exception and font_sizes(at2) == ["1rem"] * 3


# --------------------------------------------------------------- markdown ---
def test_render_markdown_formats_common_syntax():
    out = core.render_markdown("# T\n\n**b** *i* `c`\nline2\n\n- x\n- y\n\n| a |\n|---|\n| 1 |\n\n~~s~~")
    for frag in ("<h1>T</h1>", "<strong>b</strong>", "<em>i</em>", "<code>c</code>",
                 "<br />", "<li>x</li>", "<table>", "<td>1</td>", "<s>s</s>"):
        assert frag in out, frag


def test_render_markdown_is_safe():
    out = core.render_markdown(
        "<script>alert(1)</script> <b>x</b> <img src=x onerror=alert(1)>\n\n"
        "[a](javascript:alert(1)) [b](https://e.com \"t\") <https://auto.link> ![pic](http://x/y.png)"
    )
    assert "<script" not in out and "<b>" not in out and "<img" not in out
    assert "&lt;script&gt;" in out and "&lt;b&gt;x&lt;/b&gt;" in out
    assert "<a " not in out and "href" not in out              # no clickable links at all
    assert 'class="md-link" title="https://e.com"' in out
    assert "[image: pic]" in out
    assert "[a](javascript:alert(1))" in out                   # unsafe link left as text


def test_render_markdown_leaves_dollars_and_emoji_codes_alone():
    assert core.render_markdown("$5 and $10 :smile:") == "<p>$5 and $10 :smile:</p>\n"


def boxes(at):
    return [h.proto.body for h in at.get("html") if "dir=\"auto\"" in h.proto.body]


def test_markdown_toggle(env):
    data, out = env
    data.write_text(json.dumps({"id": "m1", "prompt": "Say **hi**", "response_a": "# Head\n- item",
                                "response_b": "<b>raw</b>"}), encoding="utf-8")
    at = login(new_app())
    assert at.toggle(key="render_md").value is True
    a = boxes(at)
    assert "<strong>hi</strong>" in a[0] and "<h1>Head</h1>" in a[1] and "&lt;b&gt;raw" in a[2]
    at.toggle(key="render_md").set_value(False).run()
    assert not at.exception and at.query_params["md"] == "0"
    a = boxes(at)
    assert "Say **hi**" in a[0] and "# Head\n- item" in a[1] and "<h1>" not in a[1]
    assert "&lt;b&gt;raw&lt;/b&gt;" in a[2]
    # setting survives switching annotator
    at.button(key="switch_btn").click().run()
    at = login(at, "Other")
    assert at.toggle(key="render_md").value is False


def test_markdown_off_from_url(env):
    at = AppTest.from_file(APP, default_timeout=30)
    at.query_params["annotator"] = "Tester"
    at.query_params["md"] = "0"
    at.run()
    assert not at.exception and at.toggle(key="render_md").value is False


# ------------------------------------------------------ mandatory issues ---
def test_issue_choice_rules():
    assert core.issue_choice_error("A", []) is not None
    assert core.issue_choice_error("A", None) is not None
    assert "can't be combined" in core.issue_choice_error("B", ["none", "grammar"])
    assert core.issue_choice_error("A", ["none"]) is None
    assert core.issue_choice_error("A", ["grammar", "spelling"]) is None
    assert core.default_issue_choice(None, "A") == []
    assert core.default_issue_choice({"A": [], "B": ["grammar"]}, "A") == ["none"]
    assert core.default_issue_choice({"A": [], "B": ["grammar"]}, "B") == ["grammar"]
    # "none" is never stored as an issue
    assert core.make_entry(["none"], ["grammar"], "A", "")["A"] == []


def test_both_sides_need_an_answer(env):
    data, out = env
    at = login(new_app())
    pref(at).set_value("A").run()
    f = out / "triples" / "tester.json"
    # nothing selected
    at.button(key="save_btn").click().run()
    assert at.error and "Response A" in at.error[0].value and "Response B" in at.error[0].value
    assert not f.exists()
    # only A answered
    cb(at, "A", "grammar").check()
    at.button(key="save_next_btn").click().run()
    assert "Item 1 / 3" in heading(at) and at.error
    assert "Response B" in at.error[0].value and "Response A" not in at.error[0].value
    assert not f.exists()
    assert cb(at, "A", "grammar").value            # selection kept after refusal
    # "No issues" combined with an issue is refused
    cb(at, "B", "none").check()
    cb(at, "B", "spelling").check()
    at.button(key="save_next_btn").click().run()
    assert at.error and "can't be combined" in at.error[0].value and not f.exists()
    # fixed -> saved
    cb(at, "B", "spelling").uncheck()
    at.button(key="save_next_btn").click().run()
    assert not at.error and "Item 2 / 3" in heading(at)
    assert stored(out)["q1"]["A"] == ["grammar"] and stored(out)["q1"]["B"] == []
    # going back shows "No issues" selected for B
    at.button(key="prev_btn").click().run()
    assert cb(at, "B", "none").value and cb(at, "A", "grammar").value


GUIDE = "https://docs.google.com/document/d/1Aw6SI6h3ji3qMfIlFZQ89nJTuBN0x09aMKzgJsRqMls/"


def test_guidelines_link(env):
    at = new_app()
    assert any(GUIDE in m.value for m in at.markdown)  # login screen
    login(at)
    buttons = at.get("link_button")
    assert len(buttons) == 1 and buttons[0].proto.url.startswith(GUIDE)
    pref(at).set_value("A").run()
    assert any(GUIDE in c.value for c in at.caption)  # next to the issue categories


def test_guidelines_link_can_be_hidden(env, monkeypatch):
    monkeypatch.setenv("ANNOTATION_GUIDELINES", "")
    at = new_app()
    assert not any(GUIDE in m.value for m in at.markdown)
    login(at)
    assert not at.get("link_button")
    pref(at).set_value("A").run()
    assert not any(GUIDE in c.value for c in at.caption)
