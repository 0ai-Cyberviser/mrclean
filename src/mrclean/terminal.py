from __future__ import annotations

import os
import sys
from typing import TextIO


class TerminalColors:
    """ANSI color codes for terminal output, optimized for Kali Linux."""

    # Standard colors
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    # Foreground colors
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Bright/intense foreground colors
    BRIGHT_BLACK = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"

    # Background colors
    BG_BLACK = "\033[40m"
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"
    BG_MAGENTA = "\033[45m"
    BG_CYAN = "\033[46m"
    BG_WHITE = "\033[47m"

    # Kali Linux themed colors
    KALI_BLUE = "\033[38;5;33m"  # Kali signature blue
    KALI_DRAGON = "\033[38;5;208m"  # Dragon orange
    SUCCESS = BRIGHT_GREEN
    ERROR = BRIGHT_RED
    WARNING = BRIGHT_YELLOW
    INFO = BRIGHT_CYAN
    HEADER = BOLD + KALI_BLUE


class TerminalFormatter:
    """Terminal output formatter with Kali Linux styling."""

    def __init__(self, use_colors: bool | None = None, output: TextIO = sys.stdout) -> None:
        """
        Initialize terminal formatter.

        Args:
            use_colors: Enable color output. If None, auto-detect based on terminal.
            output: Output stream for formatted text.
        """
        self.output = output
        if use_colors is None:
            # Auto-detect color support
            self.use_colors = self._detect_color_support()
        else:
            self.use_colors = use_colors

    def _detect_color_support(self) -> bool:
        """Detect if terminal supports colors."""
        # Check if output is a TTY
        if not hasattr(self.output, "isatty") or not self.output.isatty():
            return False

        # Check for common no-color indicators
        if os.getenv("NO_COLOR"):
            return False

        # Check for color support indicators
        term = os.getenv("TERM", "").lower()
        if "color" in term or "xterm" in term or "kali" in term:
            return True

        # Check COLORTERM
        if os.getenv("COLORTERM"):
            return True

        return True  # Default to colors for modern terminals

    def colorize(self, text: str, *styles: str) -> str:
        """Apply color codes to text if colors are enabled."""
        if not self.use_colors:
            return text
        color_codes = "".join(styles)
        return f"{color_codes}{text}{TerminalColors.RESET}"

    def success(self, text: str) -> str:
        """Format success message."""
        return self.colorize(f"✓ {text}", TerminalColors.SUCCESS, TerminalColors.BOLD)

    def error(self, text: str) -> str:
        """Format error message."""
        return self.colorize(f"✗ {text}", TerminalColors.ERROR, TerminalColors.BOLD)

    def warning(self, text: str) -> str:
        """Format warning message."""
        return self.colorize(f"⚠ {text}", TerminalColors.WARNING, TerminalColors.BOLD)

    def info(self, text: str) -> str:
        """Format info message."""
        return self.colorize(f"ℹ {text}", TerminalColors.INFO)

    def header(self, text: str) -> str:
        """Format header with Kali styling."""
        return self.colorize(text, TerminalColors.HEADER)

    def kali_banner(self) -> str:
        """Display Kali-themed MrClean banner."""
        banner = """
╔═══════════════════════════════════════════════════════════════╗
║                         MrClean                               ║
║          Policy-First Repository Automation Agent             ║
╚═══════════════════════════════════════════════════════════════╝
        """
        return self.colorize(banner.strip(), TerminalColors.KALI_BLUE, TerminalColors.BOLD)

    def print(self, text: str) -> None:
        """Print formatted text to output."""
        print(text, file=self.output)

    def print_success(self, text: str) -> None:
        """Print success message."""
        self.print(self.success(text))

    def print_error(self, text: str) -> None:
        """Print error message."""
        self.print(self.error(text))

    def print_warning(self, text: str) -> None:
        """Print warning message."""
        self.print(self.warning(text))

    def print_info(self, text: str) -> None:
        """Print info message."""
        self.print(self.info(text))

    def print_header(self, text: str) -> None:
        """Print header."""
        self.print(self.header(text))

    def print_section(self, title: str, items: list[str]) -> None:
        """Print a formatted section with items."""
        self.print_header(f"\n{title}")
        for item in items:
            self.print(f"  • {item}")


def generate_bash_completion() -> str:
    """Generate bash completion script for MrClean."""
    return """# Bash completion for mrclean
# Source this file or add to ~/.bashrc or /etc/bash_completion.d/

_mrclean_completion() {
    local cur prev opts commands
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    # Main commands
    commands="init validate plan scan watch dispatch assess run propose intent materialize draft preview apply"

    # Command-specific options
    case "${COMP_WORDS[1]}" in
        init)
            opts="--force"
            ;;
        validate)
            opts=""
            ;;
        plan)
            opts="--repo --goal --branch --check --changed-file --notes --json"
            ;;
        scan|watch|dispatch|assess)
            opts="--repo --json --include-healthy"
            if [ "${COMP_WORDS[1]}" == "watch" ]; then
                opts="$opts --interval --iterations"
            fi
            ;;
        run|propose|intent|materialize|draft|preview)
            opts="--repo --pr --limit --json --allow-verify --include-healthy"
            if [ "${COMP_WORDS[1]}" == "preview" ]; then
                opts="$opts --output"
            fi
            ;;
        apply)
            opts="--preview-file --json --execute"
            ;;
    esac

    # Complete commands or options
    if [ $COMP_CWORD -eq 1 ]; then
        COMPREPLY=( $(compgen -W "${commands}" -- ${cur}) )
    else
        case "${prev}" in
            --repo|--goal|--branch|--check|--changed-file|--notes|--pr|--limit|--interval|--iterations|--output|--preview-file)
                # File/path completion for config files and outputs
                COMPREPLY=( $(compgen -f -- ${cur}) )
                ;;
            *)
                COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
                ;;
        esac
    fi
}

complete -F _mrclean_completion mrclean
"""


def generate_zsh_completion() -> str:
    """Generate zsh completion script for MrClean."""
    return """#compdef mrclean
# Zsh completion for mrclean
# Place in /usr/share/zsh/site-functions/_mrclean or ~/.zsh/completion/

_mrclean() {
    local -a commands
    commands=(
        'init:Write a sample MrClean config'
        'validate:Validate a config file'
        'plan:Build a cleanup plan'
        'scan:Scan configured repositories for active PR issues'
        'watch:Poll configured repositories and emit queue changes'
        'dispatch:Turn the current queue into guarded execution candidates'
        'assess:Estimate false-positive risk and runtime issues'
        'run:Execute safe local prep commands'
        'propose:Generate a bounded edit proposal'
        'intent:Generate a validated machine-readable edit intent'
        'materialize:Resolve a generated intent against the local checkout'
        'draft:Convert a materialized intent into file-write operations'
        'preview:Render unified diff previews from guarded draft bundles'
        'apply:Apply a ready preview bundle to the local checkout'
    )

    _arguments -C \
        '1: :->command' \
        '*:: :->options'

    case $state in
        command)
            _describe 'mrclean command' commands
            ;;
        options)
            case $words[1] in
                init)
                    _arguments '--force[Overwrite existing files]'
                    ;;
                plan)
                    _arguments \
                        '--repo[Repository name from config]:repo:' \
                        '--goal[Cleanup goal]:goal:' \
                        '--branch[Working branch]:branch:' \
                        '--check[Failing check name]:check:' \
                        '--changed-file[Changed file]:file:_files' \
                        '--notes[Extra operator notes]:notes:' \
                        '--json[Emit JSON output]'
                    ;;
                scan|watch|dispatch|assess)
                    _arguments \
                        '--repo[Limit to configured repo]:repo:' \
                        '--json[Emit JSON output]' \
                        '--include-healthy[Include healthy PRs]'
                    ;;
                run|propose|intent|materialize|draft|preview)
                    _arguments \
                        '--repo[Limit to configured repo]:repo:' \
                        '--pr[Target PR number]:pr:' \
                        '--limit[Number of candidates]:limit:' \
                        '--json[Emit JSON output]' \
                        '--allow-verify[Allow verify-rated candidates]' \
                        '--include-healthy[Include healthy PRs]'
                    ;;
                apply)
                    _arguments \
                        '--preview-file[Path to preview artifact]:file:_files' \
                        '--json[Emit JSON output]' \
                        '--execute[Actually write changes]'
                    ;;
            esac
            ;;
    esac
}

_mrclean
"""
