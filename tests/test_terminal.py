from __future__ import annotations

import io
import unittest

from mrclean.terminal import TerminalColors, TerminalFormatter, generate_bash_completion, generate_zsh_completion


class TerminalFormatterTests(unittest.TestCase):
    def test_formatter_auto_detects_no_colors_for_non_tty(self) -> None:
        output = io.StringIO()
        formatter = TerminalFormatter(output=output)
        # StringIO is not a TTY, so colors should be disabled
        self.assertFalse(formatter.use_colors)

    def test_formatter_respects_explicit_color_setting(self) -> None:
        output = io.StringIO()
        formatter = TerminalFormatter(use_colors=True, output=output)
        self.assertTrue(formatter.use_colors)

    def test_formatter_disables_colors_when_requested(self) -> None:
        output = io.StringIO()
        formatter = TerminalFormatter(use_colors=False, output=output)
        self.assertFalse(formatter.use_colors)

    def test_colorize_adds_ansi_codes_when_colors_enabled(self) -> None:
        formatter = TerminalFormatter(use_colors=True)
        result = formatter.colorize("test", TerminalColors.RED)
        self.assertIn("\033[", result)
        self.assertIn("test", result)

    def test_colorize_skips_ansi_codes_when_colors_disabled(self) -> None:
        formatter = TerminalFormatter(use_colors=False)
        result = formatter.colorize("test", TerminalColors.RED)
        self.assertEqual("test", result)

    def test_success_formats_with_checkmark(self) -> None:
        formatter = TerminalFormatter(use_colors=False)
        result = formatter.success("operation completed")
        self.assertIn("✓", result)
        self.assertIn("operation completed", result)

    def test_error_formats_with_cross(self) -> None:
        formatter = TerminalFormatter(use_colors=False)
        result = formatter.error("operation failed")
        self.assertIn("✗", result)
        self.assertIn("operation failed", result)

    def test_warning_formats_with_symbol(self) -> None:
        formatter = TerminalFormatter(use_colors=False)
        result = formatter.warning("potential issue")
        self.assertIn("⚠", result)
        self.assertIn("potential issue", result)

    def test_info_formats_with_symbol(self) -> None:
        formatter = TerminalFormatter(use_colors=False)
        result = formatter.info("informational message")
        self.assertIn("ℹ", result)
        self.assertIn("informational message", result)

    def test_kali_banner_contains_mrclean(self) -> None:
        formatter = TerminalFormatter(use_colors=False)
        banner = formatter.kali_banner()
        self.assertIn("MrClean", banner)

    def test_print_success_writes_to_output(self) -> None:
        output = io.StringIO()
        formatter = TerminalFormatter(use_colors=False, output=output)
        formatter.print_success("test message")
        result = output.getvalue()
        self.assertIn("test message", result)
        self.assertIn("✓", result)

    def test_print_error_writes_to_output(self) -> None:
        output = io.StringIO()
        formatter = TerminalFormatter(use_colors=False, output=output)
        formatter.print_error("test error")
        result = output.getvalue()
        self.assertIn("test error", result)
        self.assertIn("✗", result)

    def test_print_section_formats_items(self) -> None:
        output = io.StringIO()
        formatter = TerminalFormatter(use_colors=False, output=output)
        formatter.print_section("Test Section", ["item1", "item2", "item3"])
        result = output.getvalue()
        self.assertIn("Test Section", result)
        self.assertIn("item1", result)
        self.assertIn("item2", result)
        self.assertIn("item3", result)


class ShellCompletionTests(unittest.TestCase):
    def test_bash_completion_contains_mrclean(self) -> None:
        script = generate_bash_completion()
        self.assertIn("mrclean", script)
        self.assertIn("_mrclean_completion", script)

    def test_bash_completion_contains_commands(self) -> None:
        script = generate_bash_completion()
        self.assertIn("init", script)
        self.assertIn("validate", script)
        self.assertIn("plan", script)
        self.assertIn("scan", script)
        self.assertIn("watch", script)
        self.assertIn("apply", script)

    def test_bash_completion_contains_options(self) -> None:
        script = generate_bash_completion()
        self.assertIn("--repo", script)
        self.assertIn("--json", script)
        self.assertIn("--force", script)

    def test_zsh_completion_contains_mrclean(self) -> None:
        script = generate_zsh_completion()
        self.assertIn("mrclean", script)
        self.assertIn("_mrclean", script)

    def test_zsh_completion_contains_commands(self) -> None:
        script = generate_zsh_completion()
        self.assertIn("init", script)
        self.assertIn("validate", script)
        self.assertIn("plan", script)
        self.assertIn("scan", script)
        self.assertIn("watch", script)
        self.assertIn("apply", script)

    def test_zsh_completion_contains_descriptions(self) -> None:
        script = generate_zsh_completion()
        self.assertIn("Write a sample MrClean config", script)
        self.assertIn("Validate a config file", script)


if __name__ == "__main__":
    unittest.main()
