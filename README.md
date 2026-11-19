# Naturalness annotation interface

Side-by-side judgement of two model responses to the same prompt, in two
required steps:

1. **Overall judgement**: A is better / Equally good / Equally bad / B is better.
   The issue buttons appear only after this is chosen. It can be changed
   afterwards but not cleared.
2. **Issues, for both A and B**: click every issue that applies (multiple
   allowed), or **No issues**:

   Grammar · Spelling · Punctuation · Word choice · Other language ·
   Awkward phrasing · Flow disruptions · Translationese

   Save is refused while a side has no answer, or when "No issues" is combined
   with an issue.

A comment is optional. An item counts as annotated once it is saved.

The [annotation guidelines](https://docs.google.com/document/d/1Aw6SI6h3ji3qMfIlFZQ89nJTuBN0x09aMKzgJsRqMls/edit?tab=t.0#heading=h.ruz56gdbvim4)
are linked on the login screen, in the sidebar and next to the issue
categories. To use another document, set `ANNOTATION_GUIDELINES` to its URL
before starting the app (an empty value hides the link), or change
`GUIDELINES_URL` at the top of `app.py`.

Light and dark backgrounds are both configured in `.streamlit/config.toml`. The
app follows the computer's setting, and each annotator can switch in the **⋮**
menu (top right): System, Light or Dark.

The **Text size** control in the sidebar (S / M / L / XL) changes the size of the
prompt and response text. The choice is kept in the page address (`&text=xl`),
so it survives a reload. Browser zoom (Ctrl/Cmd and +) enlarges everything.

**Render markdown** (sidebar switch, on by default) formats markdown in prompts
and responses: headings, bold/italic, lists, tables, code and quotes. Switch it
off (`&md=0`) to see the raw text exactly as the model wrote it. Rendering is
safe: raw HTML in a response stays visible as text and is never run, links are
shown but not clickable (hover to see the address), and images appear as an
`[image: …]` placeholder and are not loaded. Single line breaks are kept.
`$` signs and `:shortcodes:` are left as typed.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Run

```bash
.venv/bin/streamlit run app.py -- --data data/your_file.jsonl --out annotations
```

Note the `--` before the app options. Without `--data`, the app opens
`data/sample.jsonl`. Then open http://localhost:8501, enter an annotator ID, and
start annotating.

People on the same network can use the "Network URL" that Streamlit prints.
Each annotator enters their own ID. A bookmarked link such as
`http://host:8501/?annotator=anna` logs them in directly, and the app always
resumes at their first unannotated item.

## Input data

`.jsonl`, `.json` (a list of objects), `.csv` or `.tsv`, UTF-8. Each item needs:

| field        | also accepted as                          |
|--------------|-------------------------------------------|
| `prompt`     | `instruction`, `question`, `input`        |
| `response_a` | `Response A`, `output_a`, `answer_a`      |
| `response_b` | `Response B`, `output_b`, `answer_b`      |
| `id` (recommended) | `item_id`, `uid`, `example_id`      |

Other columns (for example model names) are ignored and never shown, so the
judgement stays blind. If there is no `id`, the row number is used, so then do
not reorder the file after annotation has started. Text is shown exactly as
written, or with markdown formatted (see above). HTML is never rendered.

```json
{"id": "ex-001", "prompt": "...", "response_a": "...", "response_b": "..."}
```

## Output

One file per annotator: `annotations/<data file name>/<annotator>.json`. It is
written atomically on every save, so a crash cannot corrupt it. `preference` is
`"A"`, `"B"`, `"both_good"` or `"both_bad"`:

```json
{"annotations": {"ex-001": {"A": ["grammar"], "B": ["spelling", "translationese"],
                            "preference": "A", "comment": "",
                            "updated_at": "2026-11-18T12:44:13+00:00"}}}
```

- Annotators can download their own CSV from the sidebar.
- To merge all annotators into one CSV (one row per annotator × item, with a
  `preference` column and a 0/1 column per side and category, e.g. `A_grammar`,
  `B_translationese`):

```bash
.venv/bin/python export_all.py --data data/your_file.jsonl --out annotations --csv results.csv
```

## Customising

The issue categories (`CATEGORIES`) and preference options (`PREFERENCES`)
are defined at the top of `core.py`. Theme colours are in
`.streamlit/config.toml`.

## Tests

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest
```

## Note on the Streamlit version

`requirements.txt` pins the Streamlit version the app was tested with. The
button colours and tick-boxes are CSS that depends on Streamlit's page
structure. After upgrading Streamlit, check that the buttons still look right
(if not, they still work, they just fall back to Streamlit's default look).
