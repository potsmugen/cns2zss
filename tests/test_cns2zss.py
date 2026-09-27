import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cns2zss import (
    convert_cns_to_zss,
    read_file_with_encoding,
    write_file_atomically,
)


FIXTURES = Path(__file__).parent / 'fixtures'


class CNS2ZSSTest(unittest.TestCase):
    def test_comprehensive_fixture(self):
        source = (FIXTURES / 'comprehensive.cns').read_text(
            encoding='utf-8'
        )
        expected = (FIXTURES / 'comprehensive.zss').read_text(
            encoding='utf-8'
        )

        actual = convert_cns_to_zss(source)

        self.assertEqual(actual, expected)

    def test_no_statedef_returns_sentinel(self):
        source = '[Data]\nlife = 1000\n'

        self.assertEqual(
            convert_cns_to_zss(source),
            '(NO_STATEDDEF)',
        )

    def test_literal_plus_one_is_distinct_from_unsigned_one(self):
        source = (
            '[Statedef +1]\ntype = S\n'
            '[Statedef 1]\ntype = S\n'
            '[Statedef +1]\ntype = A\n'
        )

        output = convert_cns_to_zss(source)

        self.assertEqual(output.count('[StateDef +1;'), 1)
        self.assertEqual(output.count('[StateDef 1;'), 1)
        self.assertIn('# WARNING: Duplicate state +1 removed', output)

    def test_persistent_stripped_in_negative_and_plus_one_states(self):
        controller = (
            '[State x]\ntype = Null\ntrigger1 = 1\n'
            'persistent = 0 ; keep\n'
        )

        for number in ('-2', '-1', '+1'):
            with self.subTest(number=number):
                output = convert_cns_to_zss(
                    f'[Statedef {number}]\n' + controller
                )
                self.assertNotIn('persistent', output)
                self.assertNotIn('# keep', output)

        output = convert_cns_to_zss('[Statedef 0]\n' + controller)
        self.assertIn('persistent(0)', output)

    def test_always_true_trigger_kept_unless_all_triggers_are_one(self):
        header = '[Statedef 200]\n[State 200, End]\ntype = Null\n'

        output = convert_cns_to_zss(
            header + 'trigger1 = AnimTime = 0\ntrigger2 = 1\n'
        )
        self.assertIn('if AnimTime = 0\n|| 1 {', output)

        output = convert_cns_to_zss(
            header + 'triggerall = 1\ntrigger1 = 1\ntrigger2 = (1)\n'
        )
        self.assertNotIn('if', output)
        self.assertIn('\nNull{}\n', output)

    def test_always_true_dropped_from_and_groups(self):
        header = '[Statedef 200]\n[State 200, End]\ntype = Null\n'
        cases = {
            'trigger1 = 1\ntrigger1 = A\n': 'if A {',
            'triggerall = 1\ntrigger1 = X\n': 'if X {',
            'triggerall = X\ntrigger1 = 1\n': 'if X {',
            'trigger1 = A\ntrigger2 = 1\ntrigger2 = B\n': 'if A\n|| B {',
        }

        for triggers, expected in cases.items():
            with self.subTest(triggers=triggers):
                output = convert_cns_to_zss(header + triggers)
                self.assertIn(expected, output)
                self.assertNotIn('1\n&&', output)

    def test_controllers_with_identical_triggers_are_not_merged(self):
        source = (
            '[Statedef 200]\n'
            '[State 200, set]\ntype = VarSet\ntrigger1 = var(1) = 0\nvar(1) = 1\n'
            '[State 200, add]\ntype = VarAdd\ntrigger1 = var(1) = 0\nvar(2) = 1\n'
        )

        output = convert_cns_to_zss(source)

        self.assertEqual(output.count('if var(1) = 0 {'), 2)

    def test_triggers_after_gap_become_warnings(self):
        source = (
            '[Statedef 200]\n[State 200, x]\ntype = Null\n'
            'trigger1 = A\ntrigger3 = B\n'
        )

        output = convert_cns_to_zss(source)

        self.assertIn('if A {', output)
        self.assertNotIn('|| B', output)
        self.assertIn(
            '# WARNING: trigger3 ignored by the engine (no trigger2): B',
            output,
        )

    def test_xor_is_wrapped_when_joined_with_and(self):
        source = (
            '[Statedef 200]\n[State 200, x]\ntype = Null\n'
            'trigger1 = A ^^ B\ntrigger1 = C\n'
        )

        self.assertIn('(A ^^ B)\n&& C', convert_cns_to_zss(source))

    def test_map_assignment_becomes_map_and_value(self):
        source = (
            '[Statedef 200]\n[State 200, x]\ntype = MapSet\n'
            'trigger1 = A\nmap(foo) = 5\n'
        )

        self.assertIn('MapSet{map: "foo"; value: 5}', convert_cns_to_zss(source))

    def test_first_type_wins_like_the_engine(self):
        source = (
            '[Statedef 200]\n[State 200, x]\ntype = Null\n'
            'type = ChangeState\ntrigger1 = A\nvalue = 0\n'
        )

        output = convert_cns_to_zss(source)

        self.assertIn('Null{', output)
        self.assertIn('# WARNING: duplicate parameter: type: ChangeState', output)

    def test_spaces_in_string_literals_are_kept(self):
        source = (
            '[Statedef 200]\n[State 200, x]\ntype = Null\n'
            'trigger1 = command = "a (b)" && var (1)\n'
        )

        self.assertIn(
            'if command = "a (b)" && var(1) {',
            convert_cns_to_zss(source),
        )

    def test_missing_trigger1_is_warned(self):
        source = (
            '[Statedef 200]\n[State 200, x]\ntype = Null\n'
            'triggerall = A\n'
        )

        self.assertIn(
            '# WARNING: no trigger1; the engine rejects this controller',
            convert_cns_to_zss(source),
        )

    def test_statedef_with_label_or_constant_is_kept(self):
        source = (
            '[Statedef 200, Punch]\ntype = S\n'
            '[Statedef const(StateJump)]\ntype = A\n'
        )

        output = convert_cns_to_zss(source)

        self.assertIn('# State 200, Punch', output)
        self.assertIn('[StateDef 200;', output)
        self.assertIn('[StateDef const(StateJump);', output)
        self.assertNotIn('Removed', output)

    def test_header_and_trigger_comments_are_kept(self):
        source = (
            '[Statedef 200] ; Punch state\n'
            '[State 200, x] ; header note\n'
            'type = Null\n'
            'trigger1 = A ; only when A\n'
        )

        output = convert_cns_to_zss(source)

        self.assertIn('#Punch state', output)
        self.assertIn('# header note', output)
        self.assertIn('# trigger1: only when A', output)

    def test_invalid_trigger_names_become_warnings(self):
        source = (
            '[Statedef 200]\n[State 200, x]\ntype = Null\n'
            'trigger1 = A\ntrigger = B\ntrigger0 = C\n'
        )

        output = convert_cns_to_zss(source)

        self.assertIn('if A {', output)
        self.assertIn(
            '# WARNING: trigger ignored by the engine (invalid trigger name): B',
            output,
        )
        self.assertIn(
            '# WARNING: trigger0 ignored by the engine (invalid trigger name): C',
            output,
        )

    def test_first_statedef_attribute_wins_like_the_engine(self):
        output = convert_cns_to_zss('[Statedef 200]\ntype = S\ntype = A\n')

        self.assertIn('\ttype: S;', output)
        self.assertNotIn('type: A;', output)
        self.assertIn('# WARNING: duplicate attribute: type: A', output)

    def test_controller_without_type_is_kept_as_comments(self):
        source = (
            '[Statedef 200]\n[State 200, x] ; important\n'
            'trigger1 = A\nvalue = 1\n'
        )

        output = convert_cns_to_zss(source)

        self.assertIn('# WARNING: no type; the engine rejects this controller', output)
        self.assertIn('# [State 200, x] ; important', output)
        self.assertIn('# value = 1', output)
        self.assertNotIn('if A', output)

    def test_nested_condition_continuation_is_indented(self):
        source = (
            '[Statedef 200]\n[State 200, x]\ntype = Null\n'
            'triggerall = Ctrl\ntrigger1 = A\ntrigger2 = B\n'
        )

        self.assertIn(
            'if Ctrl {\n\tif A\n\t|| B {\n\t\tNull{}',
            convert_cns_to_zss(source),
        )

    def test_persistent_goes_on_inner_if_with_triggerall(self):
        source = (
            '[Statedef 200]\n[State 200, x]\ntype = Null\n'
            'triggerall = Ctrl\ntrigger1 = A\npersistent = 0\nignorehitpause = 1\n'
        )

        self.assertIn(
            'ignorehitpause if Ctrl {\n\tpersistent(0) if A {',
            convert_cns_to_zss(source),
        )

    def test_comments_after_removed_section_are_kept(self):
        source = (
            '[Data]\nlife = 1000\n\n'
            ';===== States =====\n; Standing\n'
            '[Statedef 0]\ntype = S\n'
        )

        output = convert_cns_to_zss(source)

        self.assertIn('#===== States =====\n# Standing', output)

    def test_empty_trigger_is_kept_as_comments(self):
        source = (
            '[Statedef 200]\n[State 200, x]\ntype = Null\ntrigger1 =\n'
        )

        output = convert_cns_to_zss(source)

        self.assertIn(
            '# WARNING: trigger1 is empty; the engine rejects this controller',
            output,
        )
        self.assertIn('# trigger1 =', output)
        self.assertNotIn('if ', output)

    def test_duplicate_state_removal_stops_at_the_state(self):
        source = (
            '[Statedef 1]\n[Statedef 1]\ntype = S\n\n'
            '; next section\n[Data]\nlife = 1\n[Statedef 2]\n'
        )

        output = convert_cns_to_zss(source)

        self.assertIn('# WARNING: Duplicate state 1 removed', output)
        self.assertIn('# next section', output)
        self.assertIn('# Removed [Data] section', output)

    def test_invalid_state_header_ends_the_state(self):
        source = (
            '[Statedef 200]\n'
            '[State 200, a]\ntype = Null\ntrigger1 = A\n'
            '[State]\ntype = PosAdd\ntrigger1 = B\n'
            '[State 200, c]\ntype = Null\ntrigger1 = C\n'
        )

        output = convert_cns_to_zss(source)

        self.assertIn('if A {', output)
        self.assertIn(
            '# WARNING: invalid [State] header; '
            'the engine ignores the rest of this state',
            output,
        )
        self.assertIn('# [State 200, c]', output)
        self.assertNotIn('if B', output)
        self.assertNotIn('if C', output)

    def test_no_warnings_drops_ignored_code_but_keeps_assignments(self):
        source = (
            '[Data]\nlife = 1\n'
            '[Statedef 200]\ntype = S\ntype = A\n'
            '[State 200, a]\ntype = Null\ntrigger1 = A\ntrigger3 = B\n'
            'x = 1\nx = 2\n'
            '[State 200, b]\ntrigger1 = C\n'
            '[State 200, c]\ntype = Null\ntrigger1 = D\nx = var(0) := 1\n'
            '[State]\ntype = Null\ntrigger1 = E\n'
            '[Statedef 200]\n'
        )

        output = convert_cns_to_zss(source, keep_warnings=False)

        self.assertNotIn('Removed', output)
        self.assertNotIn('# WARNING: duplicate', output)
        self.assertNotIn('ignored by the engine', output)
        self.assertNotIn('invalid [State] header', output)
        self.assertNotIn('Duplicate state', output)
        self.assertIn('assignment operator `:=`', output)

    def test_no_warnings_keeps_load_errors(self):
        source = (
            '[Statedef 200]\n[State 200, a]\ntrigger1 = A\n'
            '[State 200, b]\ntype = Null\ntriggerall = B\n'
        )

        output = convert_cns_to_zss(source, keep_warnings=False)

        self.assertIn('# WARNING: no type; the engine rejects this controller', output)
        self.assertIn('# WARNING: no trigger1; the engine rejects this controller', output)

    def test_comments_between_parameters_stay_in_place(self):
        source = (
            '[Statedef 200]\n[State 200, x]\ntype = PosAdd\n'
            'trigger1 = A\nx = 1\n;y = 2\nz = 3\n'
        )

        self.assertIn(
            '\t\tx: 1;\n\t\t#y = 2\n\t\tz: 3;',
            convert_cns_to_zss(source),
        )

    def test_warnings_are_collected_even_when_removed(self):
        source = (
            '[Data]\nlife = 1\n'
            '[Statedef 200]\n[State 200, a]\ntype = Null\n'
            'trigger1 = A\ntrigger3 = B\n'
        )
        warnings = []

        output = convert_cns_to_zss(source, keep_warnings=False, warnings=warnings)

        self.assertNotIn('WARNING', output)
        self.assertEqual(warnings, [
            'Removed [Data] section',
            'State 200 [a]: trigger3 ignored by the engine (no trigger2): B',
        ])

    def test_blank_line_decides_where_trailing_comments_go(self):
        source = (
            '[Statedef 200]\n'
            '[State 200, a]\ntype = PosAdd\ntrigger1 = A\nx = 1\n;y = 2\n\n'
            '; Now jump\n'
            '[State 200, b]\ntype = Null\ntrigger1 = B\n; end of b\n\n'
            '; Next state\n[Statedef 210]\n'
        )

        output = convert_cns_to_zss(source)

        self.assertIn('\t\tx: 1;\n\t\t#y = 2\n\t}', output)
        self.assertIn('if B {\n\t# Now jump\n\tNull{}\n\t# end of b\n}', output)
        self.assertIn('# Next state\n\n#=====', output)

    def test_other_plus_prefixed_statedef_numbers_are_not_accepted(self):
        for number in ('+0', '+2', '+01'):
            with self.subTest(number=number):
                source = f'[Statedef {number}]\ntype = S\n'
                self.assertEqual(
                    convert_cns_to_zss(source),
                    '(NO_STATEDDEF)',
                )

    def test_atomic_write_leaves_existing_file_on_replace_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'output.zss'
            path.write_text('original', encoding='utf-8')

            with (
                patch(
                    'cns2zss.os.replace',
                    side_effect=OSError('replace failed'),
                ),
                self.assertRaisesRegex(OSError, 'replace failed'),
            ):
                write_file_atomically(path, 'replacement')

            self.assertEqual(path.read_text(encoding='utf-8'), 'original')
            self.assertEqual(list(Path(directory).glob('.cns2zss-*.tmp')), [])

    def test_read_file_with_encoding_handles_utf8_bom(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bom.cns'
            path.write_bytes('\ufeff[Statedef 0]'.encode('utf-8'))

            content, encoding = read_file_with_encoding(path)

        self.assertEqual(content, '[Statedef 0]')
        self.assertEqual(encoding, 'utf-8-sig')

    def test_read_file_with_encoding_handles_shift_jis(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'shift_jis.cns'
            path.write_bytes('日本語'.encode('shift_jis'))

            content, encoding = read_file_with_encoding(path)

        self.assertEqual(content, '日本語')
        self.assertEqual(encoding, 'shift_jis')


if __name__ == '__main__':
    unittest.main()
