# cns2zss — Agent notes

A Python script that converts M.U.G.E.N CNS character state files to Ikemen GO ZSS format. Stdlib-only with a Tkinter GUI. Core is `cns2zss.py`; GUI is `cns2zss_gui.py` and imports the core. No external dependencies.

Read the `.py` files. This doc is invariants and landmines, not a transcript. After a session that changes behavior, update **this file** — keep it short.

## Core invariants

1. **Preserve everything possible.** Comments (standalone, inline, pure comments inside state blocks) must survive. Output should be clean, readable ZSS with the same logical structure.
2. **Mechanical conversion only.** No semantic analysis, no optimization, no control-flow restructuring (e.g., no `else` conversion). Output is a direct translation, not a rewrite.
3. **Real files beat theory.** KFM and user-provided files are the ground truth.

## Architecture

**Entry point:** `convert_cns_to_zss(content: str) -> str`. Returns the sentinel string `'(NO_STATEDDEF)'` if the input contains no `[Statedef]` block (caller should skip writing and log).

**State parser:** `parse_state_block(lines)` parses a `[Statedef ...]` block into:
- `no`: numeric state number (int), except literal `+1` is retained as a string to distinguish it from `1`
- `attributes`: dict of state-level keys (insertion order preserved)
- `attr_comments`: dict of inline comments for attributes
- `controllers`: list of parsed controller dicts
- `pure_comments`: list of comment lines with no code

**Controller parser:** each `[State ...]` becomes a dict with:
- `type`, `triggeralls`, `triggers` (dict mapping num → list of conds), `params`, `param_comments`, `duplicates`, `persistent`, `ignorehitpause`, `comment`, `raw_block`

**Variable assignment:** `parse_varset_assignment()` matches `var()`, `fvar()`, `sysvar()`, `sysfvar()` and maps to `v`, `fv`, `sysv`, `sysfv` in ZSS. `parentvaradd`/`parentvarset` keep their original type name but use the same parsing.

**ZSS generation:** `generate_zss_state(state)`:
- Attributes → `[StateDef N; ... ]`
- Pure comments → after the state block
- Controller merging: consecutive controllers with identical triggers (triggeralls + numbered triggers + persistent + ignorehitpause) are merged into one block
- Conditions: triggerall → outer `if`; numbered triggers → inner `if` with `&&`/`||` chains
- `persistent` → `persistent(N)` prefix, except in negative states and `+1` (stripped; see below)
- Formatting: one‑line vs multi‑line based on `MAX_PARAMS_ON_LINE` and `MAX_ONE_LINE_LEN`

**Main conversion loop:** `convert_cns_to_zss()` buffers standalone comments and blank lines, flushing them as prelude when a `[Statedef]` is found. It skips duplicate state definitions by numeric state number, except literal `+1` remains distinct from `1`. Non‑state sections (`[Data]`, `[Cmd]`, etc.) are replaced with `# Removed [...]`. If the entire file contains no `[Statedef]`, it is returned unchanged (sentinel `(NO_STATEDDEF)`); section stripping only applies once at least one `[Statedef]` exists.

## Generation philosophy

The script is rule‑based, not heuristic. No semantic analysis.

**What it does not do:**
- Optimise for ZSS features (loops, etc.)
- Check if trigger names or controller parameters are valid
- Convert `:=` assignment syntax — it warns and preserves the block structure
- Convert complementary trigger pairs into `else` blocks
- Resolve or evaluate expressions — they pass through unchanged

## Configuration

Constants in `cns2zss.py`:

| Constant | Default | Purpose |
| :--- | :--- | :--- |
| `MAX_PARAMS_ON_LINE` | 3 | Force multi‑line if more params, or if any inline comment |
| `MAX_ONE_LINE_LEN` | 100 | Force multi‑line if one‑line body exceeds this length |

## Key parser behavior

### Comment handling

- **Standalone comments:** Lines starting with `;` (after spaces) → `#` and preserved.
- **Pure comments inside states:** Collected into `state['pure_comments']` and output after the `[StateDef ...]` block.
- **Inline comments:** Kept as `# comment` on the same line in ZSS.
- **Empty `;` lines:** Skipped (no comment text → not emitted).

### State block collection

A state block runs from one `[Statedef]` to the next `[Statedef]`. Pure comment lines — including those containing `<...>` — are treated as ordinary comments and collected into `state['pure_comments']`; they never terminate the block.

### Condition formatting

- `triggerall` → outer `if` (indented with `&&` for multiple).
- Numbered triggers → inner `if` (`||` between trigger numbers, `&&` inside a single trigger).
- The inner `wrap()` helper adds parentheses around terms containing `&&` or `||` (once — no double wrapping).
- `strip_outer_parens()` removes redundant outer parentheses.

### Controller merging

Merged if **identical**:
- `triggerall` conditions (sorted, cleaned)
- Numbered trigger conditions (sorted by number, each condition sorted)
- `persistent` value
- `ignorehitpause` value

When merged, if all controllers share the same `comment` (label), it is output once before the merged block.

### Duplicate handling

- **Duplicate controller parameters:** Keep first occurrence, add warning comment: `# WARNING: duplicate parameter: key: value`.
- **Duplicate state definitions:** Skip later occurrences with warning: `# WARNING: Duplicate state X removed`. `+1` and `1` are distinct (`+1` is kept as a string, other numbers as ints).

### `:=` assignment detection

Scans every line of every controller (triggers and parameters). If `:=` found, adds warning comment and outputs original block as comment for manual adjustment.

### persistent stripping

Ikemen crashes on `persistent` in negative states and `[Statedef +1]`. At the end of `parse_state_block`, if `no` is `'+1'` or a negative int, every controller's `persistent` (and its inline comment) is dropped. Doing it at parse time means merging also ignores it.

### ignorehitpause insertion

In `format_controller_body`, if `ignorehitpause_val is not None and ignorehitpause_val != '0'`, and `controller_type.lower()` is `'explod'`, `'modifyexplod'`, or `'afterimage'`, it inserts `ignorehitpause: 1` as the first parameter. This matches ZSS behavior for those controllers.

## Output formatting

- **Indentation:** Tabs (`\t`).
- **One‑line vs multi‑line:** Split if any inline comment, `len(all_params) > MAX_PARAMS_ON_LINE`, or `len(one_line_body) > MAX_ONE_LINE_LEN`.
- **Blank lines:** Single blank lines preserved; multiple collapsed to one.
- **State header:** `[StateDef N;` on its own line, attributes indented, `]` on its own line. If no attributes, `[StateDef N]` (no semicolon).
- **Pure comments:** Immediately after `[StateDef ...]` block, no blank line; blank line added if controllers follow.
- **Controllers:** Each block separated by a blank line; body indented one level within `if` or `persistent` wrappers.
- **Encoding:** Output is always written as UTF‑8 (Ikemen is encoding‑agnostic on read; decoding→re‑encoding is lossless).

## GUI behavior

- One file list. "Convert Selected" converts only selected; "Convert All" converts all. Double-click opens an input in its OS-default application.
- Conversion runs off the UI thread; the log reports converted, skipped, failed, and (when cancelled) unstarted files. No completion popup.
- Cancel Batch stops before the next file; the current file finishes. Closing during conversion asks to cancel and waits for that file before exiting.
- Overwrite confirmation: Yes / No / Cancel. Prompts are a main-thread pre-pass before the worker starts.
- Open File Location opens the OS file browser; the file picker accepts `*.cns *.cmd *.st`.
- Window title is "CNS to ZSS Converter". The same icon artwork is in `assets/icon.png` (macOS/Linux) and `assets/icon.ico` (Windows and executable packaging). Source runs on Windows, macOS, Linux, while the pre-built executable is Windows only.

## Release process

- Source and assets are kept in the repository; generated `.exe` files are never committed.
- `.github/workflows/releases.yaml` serializes builds on pushes to `main`, moves the `latest` tag to that commit, and recreates the GitHub Release so its published date and generated source archives stay current.
- The release ZIP contains the executable, both Python scripts, and both formats of the same app icon; the workflow verifies those ZIP entries before publishing.
- Versioned releases are not built by this workflow.

## Landmines (do not reintroduce)

- **Don't add `else` conversion.** Requires Boolean algebra, out of scope.
- **Don't treat `+1` as duplicate of `1`.** `+1` stays a string, so they are distinct.
- **Don't emit `persistent` in negative states or `+1`.** Ikemen crashes.
- **Don't check `:=` only in triggers.** Scan every line of every controller.
- **Don't hardcode `100` for line limit.** Use `MAX_ONE_LINE_LEN` constant.
- **Don't add runtime dependencies.** GUI is stdlib-only; PyInstaller is a build‑time exception.
- **Don't use `tkinter` in core.** Core is pure text processing; GUI imports it.
- **Don't forget `ignorehitpause` insertion for explod/modifyexplod/afterimage.** It is automatic in `format_controller_body`.
- **Don't add a `<...>` separator heuristic.** Any comment with angle brackets is an ordinary comment; the old version truncated states.
- **Don't echo input encoding on write.** Always write UTF‑8.
- **parentvaradd/parentvarset are mapped to `varAdd`/`varSet`** in the `type` field (same as `varadd`/`varset`). Don't give them separate ZSS type names unless the spec requires it.

## Regressions

- `parentvaradd`/`parentvarset` type values are mapped to `varAdd`/`varSet` (matching `varadd`/`varset` behavior).
- `:=` now detected in parameters as well as triggers (fixed).
- No more double parentheses around OR‑chain terms (fixed).
- Standalone comments between states are preserved (fixed).
- Negative and unsigned integer state numbers are supported; literal `+1` is the only accepted plus-prefixed value and remains distinct from `1`.
- Pure comments inside states are preserved and output after the state block (fixed).
- Duplicate state definitions are skipped with a warning (fixed).
- `ignorehitpause` is correctly inserted for explod/modifyexplod/afterimage when set.
- `<...>` comments no longer terminate state blocks (they are ordinary comments).
- Empty `;` comment lines no longer emit a stray `#`.
- Files with zero `[Statedef]` return untouched via the `(NO_STATEDDEF)` sentinel.
- Output is always UTF‑8, not the source file's detected encoding.
- CLI and GUI output writes use a sibling temporary file and atomic replace, preserving an existing output if writing fails.
- GUI conversion runs in a worker thread; overwrite prompts are a main‑thread pre‑pass.
- `open_location` is cross‑platform (`os.startfile` / `open` / `xdg-open`).
- `persistent` is stripped from negative states and `+1` (Ikemen crash).
- `OrderedDict` removed; plain `dict` used everywhere (insertion order preserved on Python 3.7+).

## Parked / don't do unless asked

- `else` block conversion — semantic analysis required.
- ZSS‑to‑CNS conversion — not the purpose.
- GUI tabs for different file types — keep one window.
- Shipped pip dependencies — stdlib only.
- Full expression evaluation — pass through unchanged.
- `parentvar`/`parentfvar` as variable types — use `var`/`fvar` for assignment; parent controller type handles namespace.

## Trigger conversion blueprint

Mechanical, blind translation — no semantic cleanup:

```
if (triggerall)
&& (triggerall)
&& (triggerall) {
	if ((trigger1)
	&& (trigger1)
	|| (trigger2
	&& trigger2)) {
		controllers
	}
}
```

Rules:
- All `triggerall =` lines → outer `if`, joined with `&&`.
- Within a single trigger number (e.g. two `trigger1 =` lines) → joined with `&&`.
- Across different trigger numbers → joined with `||`.
- Trigger lines may appear OUT OF ORDER in the CNS source (e.g. a `trigger4` line can appear between two `trigger1` lines). MUGEN groups by trigger number, not by source order, so the converter MUST group by integer key and ignore source position.
- Duplicate same-number triggers (e.g. `trigger4 = A` then `trigger4 = B`) are preserved as `A && B` even if logically impossible — no deduplication, no semantic cleanup.
- `trigger1 = 1` is always-true and filtered out (omitted from output).
- Exact line-wrapping and parenthesis style for single-condition groups is governed by the formatting rules (MAX_PARAMS_ON_LINE / MAX_ONE_LINE_LEN), NOT this blueprint. This blueprint defines logical grouping only.