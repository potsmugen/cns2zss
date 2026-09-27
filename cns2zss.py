#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CNS to ZSS Converter

Converts Mugen CNS character state files to Ikemen GO ZSS format.
"""

import os
import re
import stat
import sys
import tempfile
from collections import defaultdict


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
# If a controller has more parameters than this, output is split into multiple lines
MAX_PARAMS_ON_LINE = 3

# If one‑line controller body exceeds this length, split into multiple lines
MAX_ONE_LINE_LEN = 100

STATEDEF_RE = re.compile(
    r'^\s*\[\s*Statedef\s+(\+1|-?\d+)\s*\]',
    re.IGNORECASE,
)


def parse_state_number(statedef_match):
    number = statedef_match.group(1)
    return number if number == '+1' else int(number)


# ----------------------------------------------------------------------
# Utility functions
# ----------------------------------------------------------------------

def map_enum_value(param_name: str, value: str) -> str:
    """Convert deprecated CNS enum values to ZSS style."""
    if not value:
        return value

    name = param_name.lower()
    stripped = value.strip()

    if not stripped:
        return stripped

    if 'animtype' in name:
        mapping = {
            'l': 'Light',
            'm': 'Medium',
            'h': 'Hard',
            'b': 'Back',
            'u': 'Up',
            'd': 'Diagup',
        }

        if stripped[0].lower() in mapping:
            return mapping[stripped[0].lower()]

        if stripped.lower() in {
            'light', 'medium', 'hard', 'back', 'up', 'diagup'
        }:
            return stripped.capitalize()

    if name in ('ground.type', 'air.type'):
        mapping = {
            'h': 'High',
            'l': 'Low',
            't': 'Trip',
            'n': 'None',
        }

        if stripped[0].lower() in mapping:
            return mapping[stripped[0].lower()]

        if stripped.lower() in {'high', 'low', 'trip', 'none'}:
            return stripped.capitalize()

    return value


def split_code_and_comment(line: str) -> tuple[str, str | None]:
    """Split a line into code and comment."""
    if ';' not in line:
        return line.rstrip(), None

    code, comment = line.split(';', 1)
    return code.rstrip(), comment.rstrip()


def strip_comment_for_parsing(line: str) -> str:
    """Return stripped code without its comment."""
    return split_code_and_comment(line)[0].strip()


def get_comment_for_line(line: str) -> str | None:
    """Return a CNS comment converted to a ZSS comment."""
    comment = split_code_and_comment(line)[1]

    if comment is not None and comment.strip():
        return '#' + comment

    return None


def clean_condition(condition: str) -> str:
    """Remove redundant outer parentheses from a condition."""
    condition = condition.strip()

    if condition.startswith('(') and condition.endswith(')'):
        depth = 0

        for index, char in enumerate(condition):
            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1

                if depth == 0 and index == len(condition) - 1:
                    condition = condition[1:-1].strip()
                    break

    return re.sub(r'(\w+)\s+\(', r'\1(', condition)


def is_always_true(condition: str) -> bool:
    """Return whether the condition is the literal trigger1 = 1."""
    condition = condition.strip()

    if condition.lower().startswith('trigger1 = '):
        condition = condition[11:].strip()

    if condition.startswith('(') and condition.endswith(')'):
        condition = condition[1:-1].strip()

    return condition == '1'


def parse_varset_assignment(line: str) -> tuple[str, str, str] | None:
    """Parse var(), fvar(), sysvar(), or sysfvar() assignment syntax."""
    match = re.match(
        r'(var|fvar|sysvar|sysfvar)'
        r'\s*\(\s*(.*?)\s*\)\s*=\s*(.*)',
        line,
        re.IGNORECASE,
    )

    if not match:
        return None

    return (
        match.group(1).lower(),
        match.group(2).strip(),
        match.group(3).strip(),
    )


def is_controller_header(line: str) -> bool:
    """Return whether a line is a [State ...] controller header."""
    return bool(re.match(
        r'^\s*\[\s*State(?:\s|,|\])',
        line,
        re.IGNORECASE,
    ))


def is_comment_or_blank(line: str) -> bool:
    """Return whether a line is blank or a standalone comment."""
    return (
        not line.strip()
        or line.lstrip().startswith(';')
    )


# ----------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------

def parse_state_block(lines):
    """Parse one complete Statedef block."""
    state = {
        'no': None,
        'attributes': {},
        'attr_comments': {},
        'controllers': [],
        'pure_comments': [],
    }

    current_controller = None
    index = 0

    while index < len(lines):
        raw_line = lines[index]
        code, comment = split_code_and_comment(raw_line)

        if not code.strip():
            if comment and comment.strip():
                state['pure_comments'].append('#' + comment.strip())

            index += 1
            continue

        stripped = code.strip()

        statedef_match = STATEDEF_RE.match(stripped)
        if statedef_match:
            state['no'] = parse_state_number(statedef_match)
            index += 1
            continue

        controller_match = re.match(
            r'\[\s*State\s+(.*?)\]',
            stripped,
            re.IGNORECASE,
        )

        if controller_match:
            if current_controller and current_controller.get('type'):
                state['controllers'].append(current_controller)

            header = controller_match.group(1).strip()

            if ',' in header:
                label, controller_comment = header.split(',', 1)
                controller_comment = controller_comment.strip()
            else:
                label = header
                controller_comment = label or None

            raw_block = [raw_line]
            controller_lines = []
            index += 1

            while index < len(lines):
                next_line = lines[index]
                next_code, _ = split_code_and_comment(next_line)

                if next_code and next_code.strip().startswith('['):
                    break

                controller_lines.append(next_line)
                raw_block.append(next_line)
                index += 1

            current_controller = {
                'type': None,
                'triggeralls': [],
                'triggers': defaultdict(list),
                'params': {},
                'param_comments': {},
                'special_comments': {},
                'duplicates': [],
                'persistent': None,
                'ignorehitpause': None,
                'comment': controller_comment,
                'pure_comments': [],
                'raw_block': raw_block,
            }

            seen_params = set()

            for controller_line in controller_lines:
                clean_line = strip_comment_for_parsing(controller_line)
                line_comment = get_comment_for_line(controller_line)

                if not clean_line:
                    if line_comment:
                        current_controller['pure_comments'].append(line_comment.strip())
                    continue

                trigger_match = re.match(
                    r'(trigger\d*|triggerall)\s*=\s*(.*)',
                    clean_line,
                    re.IGNORECASE,
                )

                if trigger_match:
                    key = trigger_match.group(1).lower()
                    condition = trigger_match.group(2).strip()

                    if key == 'triggerall':
                        current_controller['triggeralls'].append(condition)
                    else:
                        number = int(key[7:]) if len(key) > 7 else 1
                        current_controller['triggers'][number].append(condition)

                    continue

                varset = parse_varset_assignment(clean_line)

                if varset:
                    var_type, index_expr, value_expr = varset
                    param_name = {
                        'var': 'v',
                        'fvar': 'fv',
                        'sysvar': 'sysv',
                        'sysfvar': 'sysfv',
                    }[var_type]

                    if param_name in seen_params:
                        current_controller['duplicates'].extend([
                            (param_name, index_expr),
                            ('value', value_expr),
                        ])
                    else:
                        seen_params.update((param_name, 'value'))
                        current_controller['params'][param_name] = index_expr
                        current_controller['params']['value'] = value_expr

                    if line_comment:
                        current_controller['param_comments'][param_name] = (
                            line_comment
                        )

                    continue

                parameter_match = re.match(
                    r'([\w\.]+)\s*=\s*(.*)',
                    clean_line,
                )

                if not parameter_match:
                    continue

                parameter = parameter_match.group(1).lower()
                value = parameter_match.group(2).strip()

                if parameter in ('persistent', 'ignorehitpause', 'type'):
                    if parameter == 'persistent':
                        current_controller['persistent'] = value
                    elif parameter == 'ignorehitpause':
                        current_controller['ignorehitpause'] = value
                    else:
                        value_lower = value.lower()

                        # Parent variants must keep their name or they write the wrong player's vars.
                        type_names = {
                            'varadd': 'varAdd',
                            'varset': 'varSet',
                            'parentvaradd': 'parentVarAdd',
                            'parentvarset': 'parentVarSet',
                        }
                        current_controller['type'] = type_names.get(
                            value_lower,
                            value,
                        )

                    if line_comment:
                        current_controller['special_comments'][parameter] = (
                            line_comment
                        )

                elif parameter in seen_params:
                    current_controller['duplicates'].append(
                        (parameter, value)
                    )
                else:
                    seen_params.add(parameter)
                    current_controller['params'][parameter] = map_enum_value(
                        parameter,
                        value,
                    )

                    if line_comment:
                        current_controller['param_comments'][parameter] = (
                            line_comment
                        )

            continue

        if current_controller is None:
            attribute_match = re.match(r'(\w+)\s*=\s*(.*)', stripped)

            if attribute_match:
                attribute = attribute_match.group(1).lower()
                state['attributes'][attribute] = attribute_match.group(2).strip()

                line_comment = get_comment_for_line(raw_line)
                if line_comment:
                    state['attr_comments'][attribute] = line_comment

        index += 1

    if current_controller and current_controller.get('type'):
        state['controllers'].append(current_controller)

    # ZSS crashes on persistent in negative states and +1, so drop it there.
    if state['no'] == '+1' or (isinstance(state['no'], int) and state['no'] < 0):
        for controller in state['controllers']:
            controller['persistent'] = None
            controller['special_comments'].pop('persistent', None)

    return state


# ----------------------------------------------------------------------
# Controller formatting
# ----------------------------------------------------------------------

def format_controller_body(
    controller_type,
    params,
    param_comments,
    duplicates,
    ignorehitpause_val=None,
):
    """Format one controller body."""
    all_params = list(params.items())

    if (
        ignorehitpause_val is not None
        and ignorehitpause_val != '0'
        and controller_type.lower() in (
            'explod',
            'modifyexplod',
            'afterimage',
        )
    ):
        all_params.insert(0, ('ignorehitpause', '1'))

    if not all_params and not duplicates:
        return f'{controller_type}{{}}'

    items = []

    for index, (key, value) in enumerate(all_params):
        suffix = '' if index == len(all_params) - 1 else ';'
        items.append(f'{key}: {value}{suffix}')

    one_line = f'{controller_type}{{{" ".join(items)}}}'
    has_comment = any(key in param_comments for key, _ in all_params)

    if (
        has_comment
        or duplicates
        or len(all_params) > MAX_PARAMS_ON_LINE
        or len(one_line) > MAX_ONE_LINE_LEN
    ):
        lines = [f'{controller_type}{{']

        for key, value in all_params:
            comment = param_comments.get(key)

            if comment:
                lines.append(f'\t{key}: {value}; {comment}')
            else:
                lines.append(f'\t{key}: {value};')

        for key, value in duplicates:
            lines.append(
                f'\t# WARNING: duplicate parameter: {key}: {value}'
            )

        lines.append('}')
        return '\n'.join(lines)

    return one_line


def get_trigger_key(controller):
    """Create a key for merging controllers."""
    triggeralls = tuple(sorted(
        clean_condition(condition)
        for condition in controller['triggeralls']
        if not is_always_true(condition)
    ))

    numbered = []

    for number in sorted(controller['triggers']):
        conditions = tuple(sorted(
            clean_condition(condition)
            for condition in controller['triggers'][number]
            if not is_always_true(condition)
        ))

        if conditions:
            numbered.append(conditions)

    return (
        triggeralls,
        tuple(numbered),
        controller.get('persistent'),
        controller.get('ignorehitpause'),
    )


def strip_outer_parens(condition):
    """Remove one redundant pair of outer parentheses."""
    condition = condition.strip()

    if not (
        condition.startswith('(')
        and condition.endswith(')')
    ):
        return condition

    depth = 0

    for index, char in enumerate(condition):
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1

            if depth == 0:
                if index == len(condition) - 1:
                    return condition[1:-1].strip()
                break

    return condition


# ----------------------------------------------------------------------
# ZSS generation
# ----------------------------------------------------------------------

def generate_zss_state(state):
    """Generate ZSS for one parsed state."""
    output = [
        '#============================================================',
        f"# State {state['no']}",
        '#============================================================',
        '',
    ]

    attributes = []

    for key, value in state['attributes'].items():
        comment = state['attr_comments'].get(key)

        if comment:
            attributes.append(f'\t{key}: {value}; {comment}')
        else:
            attributes.append(f'\t{key}: {value};')

    if attributes:
        output.append(
            f"[StateDef {state['no']};\n"
            + '\n'.join(attributes)
            + '\n]'
        )
    else:
        output.append(f"[StateDef {state['no']}]")

    for comment in state.get('pure_comments', []):
        output.append(comment)

    if state['controllers']:
        output.append('')

    groups = []
    current = []
    current_key = None

    for controller in state['controllers']:
        key = get_trigger_key(controller)

        if key == current_key:
            current.append(controller)
        else:
            if current:
                groups.append(current)

            current = [controller]
            current_key = key

    if current:
        groups.append(current)

    for group in groups:
        first = group[0]

        triggeralls = [
            clean_condition(condition)
            for condition in first['triggeralls']
            if not is_always_true(condition)
        ]

        numbered = []

        for number in sorted(first['triggers']):
            conditions = [
                clean_condition(condition)
                for condition in first['triggers'][number]
                if not is_always_true(condition)
            ]

            if conditions:
                numbered.append(conditions)

        body_lines = []
        comments = [
            controller.get('comment')
            for controller in group
            if controller.get('comment') is not None
        ]

        comments_identical = (
            len(comments) == len(group)
            and len(set(comments)) == 1
        )

        for controller in group:
            if not comments_identical and controller.get('comment'):
                body_lines.append(f"# {controller['comment']}")

            body_lines.extend(
                controller.get('pure_comments', [])
            )

            for name in ('type', 'persistent', 'ignorehitpause'):
                comment = controller.get(
                    'special_comments',
                    {},
                ).get(name)

                if comment:
                    body_lines.append(comment.strip())

            body = format_controller_body(
                controller['type'],
                controller['params'],
                controller.get('param_comments', {}),
                controller.get('duplicates', []),
                controller.get('ignorehitpause'),
            )

            body_lines.extend(body.splitlines())

            raw_block = controller.get('raw_block', [])

            controller_has_assignment = any(
                ':=' in split_code_and_comment(raw_line)[0]
                for raw_line in raw_block
            )

            if controller_has_assignment:
                warning_lines = [
                    '# WARNING: assignment operator `:=` found in expression. '
                    'Manual adjustment required.',
                    '# Original CNS block:',
                ]

                warning_lines.extend(
                    '# ' + raw_line.rstrip()
                    for raw_line in raw_block
                )

                # Put the warning immediately before this controller's
                # generated body rather than before the whole merged group.
                body_start = len(body_lines) - len(body.splitlines())
                body_lines[body_start:body_start] = warning_lines

        def wrap(expression):
            if re.search(r'&&|\|\|', expression):
                return f'({expression})'
            return expression

        outer = None
        if triggeralls:
            parts = [wrap(condition) for condition in triggeralls]
            outer = '\n'.join(
                [parts[0]] + [f'&& {part}' for part in parts[1:]]
            )
            outer = strip_outer_parens(outer)

        inner = None
        if numbered:
            terms = []

            for conditions in numbered:
                if len(conditions) == 1:
                    terms.append(wrap(conditions[0]))
                else:
                    parts = [wrap(condition) for condition in conditions]
                    terms.append('(' + '\n'.join(
                        [parts[0]] + [f'&& {part}' for part in parts[1:]]
                    ) + ')')

            inner = terms[0] if len(terms) == 1 else '\n'.join(
                [terms[0]] + [f'|| {term}' for term in terms[1:]]
            )
            inner = strip_outer_parens(inner)

        persistent = first.get('persistent')
        ignorehitpause = first.get('ignorehitpause')
        modifiers = []

        if persistent is not None:
            modifiers.append(f'persistent({persistent})')

        if ignorehitpause not in (None, '0'):
            modifiers.append('ignorehitpause')

        prefix = ' '.join(modifiers)
        prefix = f'{prefix} ' if prefix else ''

        def indent_line(line, level):
            if not line:
                return ''
            return '\t' * level + line

        if comments_identical:
            output.append(f'# {comments[0]}')

        if outer is None and inner is None:
            if prefix:
                output.append(f'{prefix}{{')

                for line in body_lines:
                    output.append(indent_line(line, 1))

                output.append('}')
            else:
                output.extend(body_lines)
        elif outer is None:
            output.append(f'{prefix}if {inner} {{')
            output.extend(indent_line(line, 1) for line in body_lines)
            output.append('}')
        elif inner is None:
            output.append(f'{prefix}if {outer} {{')
            output.extend(indent_line(line, 1) for line in body_lines)
            output.append('}')
        else:
            output.append(f'{prefix}if {outer} {{')
            output.append(f'\tif {inner} {{')
            output.extend(indent_line(line, 2) for line in body_lines)
            output.append('\t}')
            output.append('}')

        output.append('')

    return '\n'.join(output)


# ----------------------------------------------------------------------
# Main conversion
# ----------------------------------------------------------------------

def convert_cns_to_zss(content: str) -> str:
    """Convert complete CNS content to ZSS."""
    if not any(
        STATEDEF_RE.match(strip_comment_for_parsing(line))
        for line in content.splitlines()
    ):
        return '(NO_STATEDDEF)'

    lines = content.splitlines()
    output = []
    pending = []
    seen_states = set()
    index = 0

    while index < len(lines):
        raw_line = lines[index]

        if raw_line.lstrip().startswith(';'):
            text = raw_line.lstrip()[1:].rstrip()

            if text:
                pending.append('#' + text)

            index += 1
            continue

        if not raw_line.strip():
            pending.append('')
            index += 1
            continue

        stripped = strip_comment_for_parsing(raw_line)

        statedef_match = STATEDEF_RE.match(stripped)

        if statedef_match:
            state_number = parse_state_number(statedef_match)

            if state_number in seen_states:
                if pending:
                    output.extend(pending)
                    pending = []

                output.append(
                    f'# WARNING: Duplicate state {state_number} removed'
                )

                index += 1

                while index < len(lines):
                    next_stripped = strip_comment_for_parsing(lines[index])

                    if STATEDEF_RE.match(next_stripped):
                        break

                    index += 1

                continue

            seen_states.add(state_number)

            if pending:
                while pending and pending[-1] == '':
                    pending.pop()

                output.extend(pending)
                output.append('')
                pending = []

            state_lines = [raw_line]
            end = index + 1

            while end < len(lines):
                next_line = lines[end]
                next_code, _ = split_code_and_comment(next_line)
                next_stripped = strip_comment_for_parsing(next_line)

                if not next_code.strip():
                    state_lines.append(next_line)
                    end += 1
                    continue

                if STATEDEF_RE.match(next_stripped):
                    break

                if (
                    next_stripped.startswith('[')
                    and not is_controller_header(next_stripped)
                ):
                    break

                state_lines.append(next_line)
                end += 1

            # Do not attach separator comments before the next section to
            # the preceding state. Leave them for the main loop so they are
            # emitted before the next state or section.
            body_end = len(state_lines)

            while body_end > 1 and is_comment_or_blank(
                state_lines[body_end - 1]
            ):
                body_end -= 1

            state_lines = state_lines[:body_end]
            next_index = index + body_end

            state = parse_state_block(state_lines)
            output.append(generate_zss_state(state))
            index = next_index
            continue

        if stripped.startswith('['):
            if pending:
                output.extend(pending)
                pending = []

            output.append(f'# Removed [{stripped[1:-1]}] section')

            end = index + 1

            while end < len(lines):
                next_stripped = strip_comment_for_parsing(lines[end])

                if next_stripped and next_stripped.startswith('['):
                    break

                end += 1

            index = end
            continue

        if pending:
            output.extend(pending)
            pending = []

        output.append(raw_line)
        index += 1

    if pending:
        output.extend(pending)

    # Collapse multiple consecutive blank lines that are represented as
    # separate output lines. Embedded blank lines in generated state strings
    # are intentionally preserved.
    result = []
    previous_blank = False

    for line in output:
        if line == '':
            if not previous_blank:
                result.append(line)

            previous_blank = True
        else:
            result.append(line)
            previous_blank = False

    final_result = '\n'.join(result)

    # Always terminate generated ZSS files with one standard LF line break.
    return final_result.rstrip('\n') + '\n'


# ----------------------------------------------------------------------
# File I/O and command-line entry point
# ----------------------------------------------------------------------

def write_file_atomically(filepath, content):
    """Write UTF-8 text to a sibling temporary file, then replace the target."""
    output_path = os.path.realpath(os.fspath(filepath))
    output_dir = os.path.dirname(output_path)

    try:
        output_mode = stat.S_IMODE(os.stat(output_path).st_mode)
    except FileNotFoundError:
        # Restore the mask immediately so new files match normal open() permissions.
        current_umask = os.umask(0)
        os.umask(current_umask)
        output_mode = 0o666 & ~current_umask

    descriptor, temporary_path = tempfile.mkstemp(
        prefix='.cns2zss-',
        suffix='.tmp',
        dir=output_dir,
    )

    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())

        os.chmod(temporary_path, output_mode)
        os.replace(temporary_path, output_path)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass

        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass

        raise


def read_file_with_encoding(filepath):
    """Read a file trying common encodings."""
    for encoding in (
        'utf-8-sig',
        'shift_jis',
        'cp932',
        'latin-1',
    ):
        try:
            with open(filepath, 'r', encoding=encoding) as file:
                return file.read(), encoding
        except (UnicodeDecodeError, LookupError):
            continue

    raise UnicodeError(f'Could not decode file: {filepath}')


def confirm_overwrite(filepath):
    """Ask user for confirmation before overwriting an existing file."""
    while True:
        answer = input(
            f"File '{filepath}' already exists. Overwrite? (y/N): "
        ).strip().lower()

        if answer in ('y', 'yes'):
            return True

        if answer in ('n', 'no', ''):
            return False

        print("Please answer 'y' or 'n'.")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python cns2zss.py input.cns [output.zss]')
        sys.exit(1)

    infile = sys.argv[1]
    outfile = sys.argv[2] if len(sys.argv) > 2 else infile + '.zss'

    if os.path.exists(outfile) and not confirm_overwrite(outfile):
        print('Conversion cancelled.')
        sys.exit(0)

    cns_data, _ = read_file_with_encoding(infile)

    try:
        zss_data = convert_cns_to_zss(cns_data)

        if zss_data == '(NO_STATEDDEF)':
            print(
                f'Skipped {infile}: no [Statedef] found, '
                'file left unchanged.'
            )
        else:
            write_file_atomically(outfile, zss_data)
            print(f'Converted {infile} -> {outfile} (encoding: utf-8)')

    except Exception as error:
        print(f'Error: {error}')
        sys.exit(1)
