#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CNS to ZSS Converter

Converts Mugen CNS character state files to Ikemen GO ZSS (Zantei State Script) format.
Preserves all comments, handles variable assignments, merges identical controllers,
and applies syntax formatting rules.
"""

import re
import sys
import os
from collections import OrderedDict, defaultdict

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
# If a controller has more parameters than this, output is split into multiple lines
MAX_PARAMS_ON_LINE = 3

# If one‑line controller body exceeds this length, split into multiple lines
MAX_ONE_LINE_LEN = 100

# ----------------------------------------------------------------------
# Utility functions
# ----------------------------------------------------------------------
def map_enum_value(param_name: str, value: str) -> str:
    """Convert deprecated CNS enum values to ZSS style."""
    if not value:
        return value
    param_lower = param_name.lower()
    val = value.strip()
    if not val:
        return val

    if 'animtype' in param_lower:
        first = val[0].lower()
        mapping = {'l': 'Light', 'm': 'Medium', 'h': 'Hard', 'b': 'Back', 'u': 'Up', 'd': 'Diagup'}
        if first in mapping:
            return mapping[first]
        full_words = {'light', 'medium', 'hard', 'back', 'up', 'diagup'}
        if val.lower() in full_words:
            return val.capitalize()
        return value

    if param_lower in ('ground.type', 'air.type'):
        first = val[0].lower()
        mapping = {'h': 'High', 'l': 'Low', 't': 'Trip', 'n': 'None'}
        if first in mapping:
            return mapping[first]
        full_words = {'high', 'low', 'trip', 'none'}
        if val.lower() in full_words:
            return val.capitalize()
        return value

    return value

def split_code_and_comment(line: str):
    """Split line into code and comment (comment starts with ';')."""
    if ';' not in line:
        return line.rstrip(), None
    parts = line.split(';', 1)
    return parts[0].rstrip(), parts[1].rstrip() if len(parts) > 1 else None

def strip_comment_for_parsing(line: str) -> str:
    """Remove comment portion, keep code."""
    code, _ = split_code_and_comment(line)
    return code.strip()

def get_comment_for_line(line: str) -> str:
    """Extract comment, convert ';' to '#' for ZSS."""
    _, comment = split_code_and_comment(line)
    if comment is not None:
        return '#' + comment
    return None

def clean_condition(cond: str) -> str:
    """Remove unnecessary outer parentheses from a condition."""
    cond = cond.strip()
    if cond.startswith('(') and cond.endswith(')'):
        depth = 0
        for i, ch in enumerate(cond):
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0 and i == len(cond) - 1:
                    cond = cond[1:-1].strip()
                    break
    cond = re.sub(r'(\w+)\s+\(', r'\1(', cond)
    return cond

def is_always_true(cond: str) -> bool:
    """Check if condition is the literal trigger1 = 1."""
    cond = cond.strip()
    if cond.lower().startswith('trigger1 = '):
        cond = cond[11:].strip()
    if cond.startswith('(') and cond.endswith(')'):
        cond = cond[1:-1].strip()
    return cond == '1'

def parse_varset_assignment(line_clean: str):
    """Recognise variable assignment lines for var/fvar/sysvar/sysfvar."""
    m = re.match(r'(var|fvar|sysvar|sysfvar)\s*\(\s*(.*?)\s*\)\s*=\s*(.*)', line_clean, re.IGNORECASE)
    if m:
        var_type = m.group(1).lower()
        index_expr = m.group(2).strip()
        value_expr = m.group(3).strip()
        return var_type, index_expr, value_expr
    return None

# ----------------------------------------------------------------------
# State and controller parsing
# ----------------------------------------------------------------------
def parse_state_block(lines):
    """
    Parse a complete state block (from [Statedef ...] to next [Statedef]).
    Returns a dictionary with keys:
        'no', 'attributes', 'attr_comments', 'controllers', 'pure_comments'.
    """
    state = {
        'no': None,
        'attributes': OrderedDict(),
        'attr_comments': OrderedDict(),
        'controllers': [],
        'pure_comments': []
    }
    current_controller = None
    i = 0
    total = len(lines)

    while i < total:
        raw_line = lines[i]

        # Pure comment line (no code before ';')
        code_part, comment_part = split_code_and_comment(raw_line)
        if code_part is None or code_part.strip() == '':
            if comment_part and comment_part.strip():
                state['pure_comments'].append('#' + comment_part.strip())
            i += 1
            continue

        stripped = strip_comment_for_parsing(raw_line)
        if not stripped:
            i += 1
            continue

        # [Statedef ...] header
        m = re.match(r'\[\s*Statedef\s+(-?\d+)\s*\]', stripped, re.IGNORECASE)
        if m:
            state['no'] = int(m.group(1))
            i += 1
            continue

        # [State ...] header (start of a controller)
        m = re.match(r'\[\s*State\s+(.*?)\]', stripped, re.IGNORECASE)
        if m:
            if current_controller and current_controller.get('type'):
                state['controllers'].append(current_controller)

            header_content = m.group(1).strip()
            if ',' in header_content:
                label, comment = header_content.split(',', 1)
                comment = comment.strip()
            else:
                label = header_content
                comment = label if label else None

            raw_block = [raw_line]
            ctrl_lines = []
            i += 1
            while i < total:
                nxt = lines[i]
                nxt_code, _ = split_code_and_comment(nxt)
                if nxt_code and nxt_code.strip().startswith('['):
                    break
                ctrl_lines.append(nxt)
                raw_block.append(nxt)
                i += 1

            current_controller = {
                'type': None,
                'triggeralls': [],
                'triggers': defaultdict(list),
                'params': OrderedDict(),
                'param_comments': OrderedDict(),
                'duplicates': [],
                'persistent': None,
                'ignorehitpause': None,
                'comment': comment,
                'raw_block': raw_block
            }
            seen_params = set()

            for cline in ctrl_lines:
                code_clean = strip_comment_for_parsing(cline)
                if not code_clean:
                    continue

                # Trigger lines
                trig_match = re.match(r'(trigger\d*|triggerall)\s*=\s*(.*)', code_clean, re.IGNORECASE)
                if trig_match:
                    key = trig_match.group(1).lower()
                    cond = trig_match.group(2).strip()
                    if key == 'triggerall':
                        current_controller['triggeralls'].append(cond)
                    else:
                        num = int(key[7:]) if len(key) > 7 else 1
                        current_controller['triggers'][num].append(cond)
                    continue

                # Variable assignment (varadd / varset / parentvaradd / parentvarset)
                varset = parse_varset_assignment(code_clean)
                if varset:
                    var_type, index_expr, value_expr = varset
                    param_name = {
                        'var': 'v',
                        'fvar': 'fv',
                        'sysvar': 'sysv',
                        'sysfvar': 'sysfv'
                    }.get(var_type, 'v')
                    if param_name in seen_params:
                        current_controller['duplicates'].append((param_name, index_expr))
                        current_controller['duplicates'].append(('value', value_expr))
                    else:
                        seen_params.add(param_name)
                        seen_params.add('value')
                        current_controller['params'][param_name] = index_expr
                        current_controller['params']['value'] = value_expr
                    comment = get_comment_for_line(cline)
                    if comment:
                        current_controller['param_comments'][param_name] = comment
                    continue

                # Regular parameter (key = value)
                param_match = re.match(r'([\w\.]+)\s*=\s*(.*)', code_clean)
                if param_match:
                    pname = param_match.group(1).lower()
                    pval = param_match.group(2).strip()
                    comment = get_comment_for_line(cline)

                    if pname in ('persistent', 'ignorehitpause', 'type'):
                        if pname == 'persistent':
                            current_controller['persistent'] = pval
                        elif pname == 'ignorehitpause':
                            current_controller['ignorehitpause'] = pval
                        elif pname == 'type':
                            type_lower = pval.lower()
                            if type_lower in ('varadd', 'parentvaradd'):
                                current_controller['type'] = 'varAdd'
                            elif type_lower in ('varset', 'parentvarset'):
                                current_controller['type'] = 'varSet'
                            else:
                                current_controller['type'] = pval
                        if comment:
                            current_controller['param_comments'][pname] = comment
                    else:
                        if pname in seen_params:
                            current_controller['duplicates'].append((pname, pval))
                        else:
                            seen_params.add(pname)
                            current_controller['params'][pname] = map_enum_value(pname, pval)
                            if comment:
                                current_controller['param_comments'][pname] = comment
                    continue
            continue

        # Attribute lines (before any [State ...])
        if current_controller is None:
            attr_match = re.match(r'(\w+)\s*=\s*(.*)', stripped)
            if attr_match:
                attr = attr_match.group(1).lower()
                val = attr_match.group(2).strip()
                state['attributes'][attr] = val
                comment = get_comment_for_line(raw_line)
                if comment:
                    state['attr_comments'][attr] = comment
        i += 1

    if current_controller and current_controller.get('type'):
        state['controllers'].append(current_controller)

    return state

# ----------------------------------------------------------------------
# Controller formatting
# ----------------------------------------------------------------------
def format_controller_body(ctrl_type: str, params: OrderedDict, param_comments: OrderedDict, duplicates, ignorehitpause_val=None) -> str:
    """Format a controller's parameter list into a ZSS body string."""
    all_params = list(params.items())

    if ignorehitpause_val is not None and ignorehitpause_val != '0':
        if ctrl_type.lower() in ('explod', 'modifyexplod', 'afterimage'):
            all_params.insert(0, ("ignorehitpause", "1"))

    if not all_params and not duplicates:
        return f"{ctrl_type}{{}}"

    # Try one-line version
    one_line_items = []
    for i, (k, v) in enumerate(all_params):
        if i == len(all_params) - 1:
            one_line_items.append(f"{k}: {v}")
        else:
            one_line_items.append(f"{k}: {v};")
    one_line_body = f"{ctrl_type}{{{' '.join(one_line_items)}}}"

    has_comment = any(k in param_comments for k, _ in all_params) or bool(duplicates)
    if has_comment or len(all_params) > MAX_PARAMS_ON_LINE or len(one_line_body) > MAX_ONE_LINE_LEN:
        lines = [f"{ctrl_type}{{"]
        for k, v in all_params:
            comment = param_comments.get(k)
            if comment:
                lines.append(f"\t{k}: {v}; {comment}")
            else:
                lines.append(f"\t{k}: {v};")
        for dup_key, dup_val in duplicates:
            lines.append(f"\t# WARNING: duplicate parameter: {dup_key}: {dup_val}")
        lines.append("}")
        return "\n".join(lines)
    else:
        return one_line_body

def get_trigger_key(ctrl):
    """Generate a hashable key for a controller's triggers, persistent, ignorehitpause."""
    talls = tuple(sorted(clean_condition(t) for t in ctrl['triggeralls'] if not is_always_true(t)))
    numbered = []
    for num in sorted(ctrl['triggers'].keys()):
        conds = tuple(sorted(clean_condition(c) for c in ctrl['triggers'][num] if not is_always_true(c)))
        if conds:
            numbered.append(conds)
    numbered = tuple(numbered)
    persistent = ctrl.get('persistent')
    ignorehitpause = ctrl.get('ignorehitpause')
    return (talls, numbered, persistent, ignorehitpause)

def strip_outer_parens(cond: str) -> str:
    """Remove one pair of outer parentheses if they wrap the whole expression."""
    if not cond:
        return cond
    cond = cond.strip()
    if cond.startswith('(') and cond.endswith(')'):
        depth = 0
        for i, ch in enumerate(cond):
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0:
                    if i == len(cond) - 1:
                        return cond[1:-1].strip()
                    else:
                        break
    return cond

# ----------------------------------------------------------------------
# ZSS state generation
# ----------------------------------------------------------------------
def generate_zss_state(state):
    """Convert a parsed state dictionary into ZSS syntax."""
    out_lines = []
    out_lines.append("#============================================================")
    out_lines.append(f"# State {state['no']}")
    out_lines.append("#============================================================")
    out_lines.append("")

    # Attributes
    attr_parts = []
    for k, v in state['attributes'].items():
        comment = state['attr_comments'].get(k)
        if comment:
            attr_parts.append(f"\t{k}: {v}; {comment}")
        else:
            attr_parts.append(f"\t{k}: {v};")
    if attr_parts:
        attr_line = f"[StateDef {state['no']};\n" + "\n".join(attr_parts) + "\n]"
    else:
        attr_line = f"[StateDef {state['no']}]"
    out_lines.append(attr_line)

    # Pure comments (lines that were only '; comment')
    if state.get('pure_comments'):
        for comment in state['pure_comments']:
            out_lines.append(comment)
        if state['controllers']:
            out_lines.append('')
    elif state['controllers']:
        out_lines.append('')

    # Merge controllers with identical trigger keys
    merged_groups = []
    current_group = []
    current_key = None
    for ctrl in state['controllers']:
        key = get_trigger_key(ctrl)
        if key == current_key:
            current_group.append(ctrl)
        else:
            if current_group:
                merged_groups.append(current_group)
            current_group = [ctrl]
            current_key = key
    if current_group:
        merged_groups.append(current_group)

    for group in merged_groups:
        first = group[0]
        talls = [clean_condition(t) for t in first['triggeralls'] if not is_always_true(t)]
        numbered = []
        for num in sorted(first['triggers'].keys()):
            conds = [clean_condition(c) for c in first['triggers'][num] if not is_always_true(c)]
            if conds:
                numbered.append(conds)
        persistent_val = first.get('persistent')
        ignorehitpause_val = first.get('ignorehitpause')

        has_assign = False
        # Check triggers
        for cond in talls:
            if ':=' in cond:
                has_assign = True
        for conds in numbered:
            for cond in conds:
                if ':=' in cond:
                    has_assign = True
        # Check parameter lines in all controllers of the group
        for ctrl in group:
            for line in ctrl.get('raw_block', []):
                code_part, _ = split_code_and_comment(line)
                if code_part and ':=' in code_part:
                    has_assign = True

        comments = [ctrl.get('comment') for ctrl in group if ctrl.get('comment') is not None]
        all_comments_identical = len(set(comments)) == 1 and len(comments) == len(group)
        merged_comment = comments[0] if all_comments_identical else None

        inner_block_lines = []
        raw_blocks = []
        for ctrl in group:
            if not all_comments_identical:
                comment = ctrl.get('comment')
                if comment:
                    inner_block_lines.append(f"# {comment}")
            body = format_controller_body(
                ctrl['type'],
                ctrl['params'],
                ctrl.get('param_comments', OrderedDict()),
                ctrl.get('duplicates', []),
                ctrl.get('ignorehitpause')
            )
            inner_block_lines.extend(body.splitlines())
            if has_assign:
                raw_blocks.append(ctrl.get('raw_block', []))

        def wrap_if_needed(expr):
            if re.search(r'&&|\|\|', expr):
                return f"({expr})"
            return expr

        if talls:
            and_parts = [wrap_if_needed(c) for c in talls]
            outer_cond = "\n".join([and_parts[0]] + [f"&& {p}" for p in and_parts[1:]])
        else:
            outer_cond = None

        if numbered:
            or_terms = []
            for conds in numbered:
                if len(conds) == 1:
                    term = wrap_if_needed(conds[0])
                else:
                    sub_parts = [wrap_if_needed(c) for c in conds]
                    term = "\n".join([sub_parts[0]] + [f"&& {p}" for p in sub_parts[1:]])
                or_terms.append(term)
            if len(or_terms) == 1:
                inner_cond = or_terms[0]
            else:
                inner_cond = "\n".join([or_terms[0]] + [f"|| {t}" for t in or_terms[1:]])
                if outer_cond is not None:
                    inner_cond = f"({inner_cond})"
        else:
            inner_cond = None

        if outer_cond is not None:
            outer_cond = strip_outer_parens(outer_cond)
        if inner_cond is not None:
            inner_cond = strip_outer_parens(inner_cond)

        if outer_cond is not None and inner_cond and '\n' in inner_cond:
            lines = inner_cond.split('\n')
            inner_cond = lines[0] + '\n' + '\n'.join('\t' + line for line in lines[1:])

        if has_assign:
            out_lines.append("# WARNING: assignment operator `:=` found in expression. Manual adjustment required.")
            for raw_block in raw_blocks:
                out_lines.append("# Original CNS block:")
                for line in raw_block:
                    out_lines.append("# " + line.rstrip())

        mods = []
        if persistent_val is not None:
            mods.append(f"persistent({persistent_val})")
        if ignorehitpause_val is not None and ignorehitpause_val != '0':
            mods.append("ignorehitpause")
        mod_str = " ".join(mods) + " " if mods else ""

        if merged_comment:
            out_lines.append(f"# {merged_comment}")

        if outer_cond is None and inner_cond is None:
            if mods:
                out_lines.append(f"{mod_str}{{")
                for line in inner_block_lines:
                    out_lines.append(f"\t{line}")
                out_lines.append("}")
            else:
                out_lines.extend(inner_block_lines)
        elif outer_cond is None:
            out_lines.append(f"{mod_str}if {inner_cond} {{")
            for line in inner_block_lines:
                out_lines.append(f"\t{line}")
            out_lines.append("}")
        elif inner_cond is None:
            out_lines.append(f"{mod_str}if {outer_cond} {{")
            for line in inner_block_lines:
                out_lines.append(f"\t{line}")
            out_lines.append("}")
        else:
            out_lines.append(f"{mod_str}if {outer_cond} {{")
            out_lines.append(f"\tif {inner_cond} {{")
            for line in inner_block_lines:
                out_lines.append(f"\t\t{line}")
            out_lines.append("\t}")
            out_lines.append("}")
        out_lines.append("")
    return "\n".join(out_lines)

# ----------------------------------------------------------------------
# Main conversion function
# ----------------------------------------------------------------------
def convert_cns_to_zss(content: str) -> str:
    """Convert entire CNS file content to ZSS format."""
    lines = content.splitlines()
    out_lines = []
    i = 0
    total = len(lines)
    pending = []
    seen_states = set()        # Track state numbers seen in this file

    while i < total:
        raw_line = lines[i]

        # Buffer standalone comment lines (starts with ';')
        if raw_line.lstrip().startswith(';'):
            comment_text = raw_line.lstrip()[1:].rstrip()
            if comment_text:
                pending.append('#' + comment_text)
            i += 1
            continue

        # Buffer blank lines
        if raw_line.strip() == '':
            pending.append('')
            i += 1
            continue

        stripped = strip_comment_for_parsing(raw_line)
        if not stripped:
            if pending:
                out_lines.extend(pending)
                pending = []
            out_lines.append(raw_line)
            i += 1
            continue

        # [Statedef] found – check for duplicate state number
        m = re.match(r'\[\s*Statedef\s+(-?\d+)\s*\]', stripped, re.IGNORECASE)
        if m:
            state_no = int(m.group(1))
            if state_no in seen_states:
                # Duplicate state – remove the entire block
                if pending:
                    out_lines.extend(pending)
                    pending = []
                out_lines.append(f"# WARNING: Duplicate state {state_no} removed")
                # Skip to the next [Statedef] or end of file
                i += 1
                while i < total:
                    nxt = lines[i]
                    nxt_stripped = strip_comment_for_parsing(nxt)
                    if nxt_stripped and re.match(r'\[\s*Statedef', nxt_stripped, re.IGNORECASE):
                        break
                    i += 1
                continue
            else:
                seen_states.add(state_no)

            if pending:
                while pending and pending[-1] == '':
                    pending.pop()
                out_lines.extend(pending)
                out_lines.append('')
                pending = []

            state_lines = [raw_line]
            j = i + 1
            while j < total:
                nxt = lines[j]
                nxt_code, _ = split_code_and_comment(nxt)
                if nxt_code is None or nxt_code.strip() == '':
                    nxt_comment = nxt.lstrip()[1:].rstrip() if nxt.lstrip().startswith(';') else ''
                    if re.search(r'<[^>]+>', nxt_comment):
                        break
                    state_lines.append(nxt)
                    j += 1
                    continue
                nxt_stripped = strip_comment_for_parsing(nxt)
                if nxt_stripped.startswith('[') and re.match(r'\[\s*Statedef', nxt_stripped, re.IGNORECASE):
                    break
                state_lines.append(nxt)
                j += 1

            state = parse_state_block(state_lines)
            if state['no'] is not None:
                out_lines.append(generate_zss_state(state))
            i = j
            continue

        # Non‑state section (e.g., [Files], [Cmd]) – remove
        if stripped.startswith('['):
            if pending:
                out_lines.extend(pending)
                pending = []
            out_lines.append(f"# Removed [{stripped[1:-1]}] section")
            j = i + 1
            while j < total:
                nxt_stripped = strip_comment_for_parsing(lines[j])
                if nxt_stripped and nxt_stripped.startswith('['):
                    break
                j += 1
            i = j
            continue

        # Any other line – flush pending and output as is
        if pending:
            out_lines.extend(pending)
            pending = []
        out_lines.append(raw_line)
        i += 1

    if pending:
        out_lines.extend(pending)

    # Collapse multiple consecutive blank lines into a single blank line
    result = []
    prev_blank = False
    for line in out_lines:
        if line == '':
            if not prev_blank:
                result.append(line)
                prev_blank = True
        else:
            result.append(line)
            prev_blank = False
    return "\n".join(result)

# ----------------------------------------------------------------------
# File I/O and main entry point
# ----------------------------------------------------------------------
def read_file_with_encoding(filepath):
    """Read file trying common encodings (UTF‑8, Shift-JIS, CP932)."""
    encodings = ['utf-8', 'shift_jis', 'cp932']
    for enc in encodings:
        try:
            with open(filepath, 'r', encoding=enc) as f:
                return f.read(), enc
        except (UnicodeDecodeError, LookupError):
            continue
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        return f.read(), 'utf-8'

def confirm_overwrite(filepath):
    """Ask user for confirmation before overwriting an existing file."""
    while True:
        answer = input(f"File '{filepath}' already exists. Overwrite? (y/N): ").strip().lower()
        if answer in ('y', 'yes'):
            return True
        if answer in ('n', 'no', ''):
            return False
        print("Please answer 'y' or 'n'.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python cns2zss.py input.cns [output.zss]")
        sys.exit(1)

    infile = sys.argv[1]
    outfile = sys.argv[2] if len(sys.argv) > 2 else infile + ".zss"

    if os.path.exists(outfile) and not confirm_overwrite(outfile):
        print("Conversion cancelled.")
        sys.exit(0)

    cns_data, used_encoding = read_file_with_encoding(infile)
    try:
        zss_data = convert_cns_to_zss(cns_data)
        with open(outfile, 'w', encoding=used_encoding, errors='replace') as f:
            f.write(zss_data)
        print(f"Converted {infile} -> {outfile} (encoding: {used_encoding})")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
