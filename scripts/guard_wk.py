#!/usr/bin/env python3.14
"""Shell-command guard: block the uses of `wk` and of its token file that the rules forbid.

    <hook JSON on stdin> | scripts/guard_wk.py

1. `wk pull`, `wk diff`, `wk clone`, in any flag order and with any profile: each run creates a
   new export manifest in the Workato workspace and never deletes it. Use `scripts/sync_recipes.py`
   or `wk recipes pull <id>` instead; both are a plain GET. And `wk push`, which imports a whole
   package into the workspace: a recipe is changed one at a time, by the procedure in AGENTS.md.
2. Every shell `wk auth token` and `wk mcp auth-header`, including pipelines, substitutions and
   redirections: both print the API token. For an API call use `scripts/wk_api.py`, which reads
   the token inside its own process.
3. Every command that names `profiles.env`, the file in which `wk` keeps tokens as plain text on
   a machine without a keychain, also by a glob in the current folder (`prof*`, `*.env`). Only
   commands that cannot show its content pass: `ls`, `stat`, `test`, `chmod`, `touch`, and
   `git check-ignore`, `git status`, `git ls-files`; and none of them when `xargs` could hand the
   name on to another program.
4. `wk ... -o <file>` with a file outside tmp/: the read commands are allowed without asking, so
   their output flag must not be able to overwrite a file of the repository or of the person.
   Every file named counts, in every spelling (`-o F`, `-oF`, `--output=F`, `-jo F`), and a path
   the shell would expand is refused.
5. `wk --verbose`: a debug log may show the request headers, and with them the token.
6. `xargs wk` with fewer than two subcommand words: the rest would come from standard input.

`wk` is recognized as a word anywhere in a simple command, so wrappers (`xargs wk`, `env -u X wk`,
`time -p wk`), `else`, `{` and environment prefixes are covered. The price: unquoted prose such as
`echo never run wk pull` is blocked too; quote it. The output flag and `--verbose` are checked
only where `wk` is the program of the command, so `grep wk -o file` and
`find tmp/wk -name a -o -name b` pass.

A flag of a subcommand may stand before it (`wk --folder 5 pull`): wk then takes the next word
as the value of that flag. The guard knows the flags of wk itself, not those of every subcommand
and version, so it reads such a word both ways, as a value and as a subcommand, and blocks when
either reading is a forbidden command.

Claude Code and Codex run this script as a PreToolUse hook on Bash. Another harness can call it
the same way if its hook passes the same JSON on stdin:
{"tool_name": "Bash", "tool_input": {"command": "..."}}. A harness that runs no hooks (a cloud
agent, a code reviewer) is covered only by the rule in AGENTS.md.

This is a guard against mistakes, not a shell security boundary: `eval`, text piped into a shell
(`echo ... | sh`), a command held in a variable, aliases, external scripts and a program handed
to another interpreter (`python3 -c`, `perl -e`, `osascript -e`) are not interpreted, and a
command that reads every file of a folder (`grep -r`) is not recognized as reading the token
file. tmp/ is read relative to the folder the command runs in. A malformed payload is blocked,
and so is a command that mentions wk or the token file with quoting the guard cannot parse.

The script imports nothing from scripts/lib on purpose: a hook has to keep working when the rest
of the tooling is broken.

Exit status: 0 the command may run; 2 it is blocked, and the reason on stderr goes to the agent.
"""

import argparse
import fnmatch
import json
import re
import shlex
import sys
from collections.abc import Iterator
from pathlib import Path

ALLOW = 0
BLOCK = 2
MAX_DEPTH = 20
EXPORT_COMMANDS = (("pull",), ("diff",), ("clone",))
IMPORT_COMMANDS = (("push",),)
TOKEN_COMMANDS = (("auth", "token"), ("mcp", "auth-header"))
# The flags of wk itself, as `wk --help` of wk 1.1.0 lists them: the ones that take a value, and
# the switches. Every other flag belongs to a subcommand; `may_run` says how it is read.
FLAGS_WITH_VALUE = frozenset({"-p", "--profile", "--store-type", "--timeout"})
SWITCHES = frozenset(
    {
        "-h",
        "--help",
        "-j",
        "--json",
        "--no-color",
        "--no-input",
        "-q",
        "--quiet",
        "--raw",
        "--verbose",
    }
)
SHORT_FLAG_LENGTH = len("-x")
STDIN_WORDS = 2  # `xargs wk` has to spell this many words of the command itself
OUTPUT_FLAG = "--output"
OUTPUT_LETTER = "o"  # -o
VALUE_LETTERS = "p"  # the other short flags of wk that take a value: -p
OUTPUT_FOLDER = "tmp/"  # the working cache: the only place a wk read may write to unasked
# The same folder by its full path, as the hook was started and with symbolic links resolved.
CACHES = tuple(
    {
        f"{root}/{OUTPUT_FOLDER}"
        for root in (Path(__file__).absolute().parents[1], Path(__file__).resolve().parents[1])
    }
)
EXPANDED_BY_SHELL = "$`~*?[{\\"  # with one of these the guard cannot know the real path
# Programs that run the command that follows them. The permission rules of a harness look through
# some of them, so a `wk` after one is the program of the command and not an argument.
LAUNCHERS = frozenset({"xargs", "timeout", "nice", "stdbuf", "builtin", "noglob"})
DEBUG_FLAG = "--verbose"
SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "fish", "csh", "tcsh"})
SPLIT_FLAGS = ("-S", "--split-string")  # `env -S '<command line>'` runs that command line
WHY_EXPORT = (
    "`wk {}` is forbidden: it creates an export manifest in Workato. "
    "Use scripts/sync_recipes.py or `wk recipes pull <id>` (plain GETs)."
)
WHY_IMPORT = (
    "`wk push` is forbidden: it imports a whole package into the workspace. Change one recipe "
    "at a time, by the push procedure in AGENTS.md."
)
WHY_PRINT = (
    "Shell `wk {}` is forbidden, including pipes, substitutions and redirects: it prints the "
    "API token. For an API call use scripts/wk_api.py: it reads the token inside its own process."
)
WHY_STDIN = (
    "`xargs wk` with fewer than two subcommand words is forbidden: the rest of the command "
    "would come from standard input, unseen. Write the wk command out."
)
WHY_DEBUG = (
    "`wk --verbose` is forbidden here: a debug log may show the request headers, and with them "
    "the API token. A person runs it in a terminal of their own."
)
WHY_OUTPUT = (
    f"`wk ... -o <file>` may write only under {OUTPUT_FOLDER} (the working cache), for example "
    f"-o {OUTPUT_FOLDER}edits/<file>: a wk read runs without asking, so it must not be able to "
    f"overwrite another file. Write to {OUTPUT_FOLDER} and copy the file from there."
)
TOKEN_FILE = "profiles.env"  # noqa: S105 - a file name, not a password
# Programs that may name the token file: they show that it exists, never what it holds.
BLIND_PROGRAMS = frozenset({"ls", "stat", "test", "[", "chmod", "touch"})
BLIND_GIT_COMMANDS = frozenset({"check-ignore", "status", "ls-files"})
GLOB_CHARACTERS = "*?["
# Words that may stand before the command itself: `time wk ...`, `then wk ...`, `! wk ...`.
PREFIX_WORDS = frozenset(
    {"time", "command", "exec", "env", "sudo", "nohup", "then", "else", "do", "!", "{"}
)
OPERATORS = ";&|()<>\n"
QUOTES = "\"'"
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
SHELL_COMMAND_FLAG = re.compile(r"-[A-Za-z]*c[A-Za-z]*")
HEREDOC = re.compile(r"(?<!<)<<(?!<)-?[ \t]*(\\|['\"])?([A-Za-z_][\w.-]*)['\"]?[^\n]*\n")


def words(text: str) -> list[str]:
    """Split text into shell words; fall back to whitespace when the quoting does not parse."""
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def toggled(quote: str | None, char: str) -> str | None:
    """Return the quoting state after a quote character: opened, closed or unchanged."""
    if quote is None:
        return char
    return None if quote == char else quote


def heredocs(command: str) -> tuple[str, list[str], list[str]]:
    """Take the heredoc bodies out of a command.

    Returns the command without the bodies, the bodies that are fed to a shell (they are
    programs) and the bodies of unquoted heredocs (the shell expands substitutions in them).
    """
    kept: list[str] = []
    scripts: list[str] = []
    expanded: list[str] = []
    pos = 0
    while True:
        start = HEREDOC.search(command, pos)
        if not start:
            kept.append(command[pos:])
            return "".join(kept), scripts, expanded
        kept.append(command[pos : start.end()])
        delimiter = re.compile(r"^[ \t]*" + re.escape(start.group(2)) + r"[ \t]*$", re.MULTILINE)
        closing = delimiter.search(command, start.end())
        if not closing:
            pos = start.end()
            continue
        body = command[start.end() : closing.start()]
        # The whole line of the heredoc: `bash <<EOF` and `cat <<EOF | bash` both run the body.
        line = command[command.rfind("\n", pos, start.start()) + 1 : start.end()]
        if any(word.rsplit("/", 1)[-1] in SHELLS for word in words(line.replace("|", " "))):
            scripts.append(body)
        if not start.group(1):
            expanded.append(body)
        pos = closing.end()


def substitution_end(command: str, start: int) -> tuple[int, bool]:
    """Find where a `$(` whose content begins at `start` closes.

    Returns the index after the closing parenthesis and whether it was found at all.
    """
    depth = 1
    end = start
    quote: str | None = None
    while end < len(command) and depth:
        char = command[end]
        if char == "\\":
            end += 2
            continue
        if char in QUOTES:
            quote = toggled(quote, char)
        elif quote is None:
            depth += (char == "(") - (char == ")")
        end += 1
    return end, depth == 0


def substitutions(command: str, *, heredoc: bool = False) -> Iterator[str]:
    """Yield the text of every `$(...)` and backtick substitution outside single quotes.

    Nothing is evaluated. Inside a heredoc body quotes do not protect a substitution.
    """
    quote: str | None = None
    i = 0
    while i < len(command):
        char = command[i]
        if char == "\\" and quote != "'":
            i += 2
        elif char in QUOTES and not heredoc:
            quote = toggled(quote, char)
            i += 1
        elif quote != "'" and char == "`":
            end = command.find("`", i + 1)
            if end < 0:
                return
            yield command[i + 1 : end]
            i = end + 1
        elif quote != "'" and command.startswith("$(", i):
            end, closed = substitution_end(command, i + 2)
            yield command[i + 2 : end - 1] if closed else command[i + 2 :]
            i = end
        else:
            i += 1


def strip_comments(command: str) -> str:
    """Drop `# ...` where the shell starts a comment (outside quotes); keep the newline."""
    out: list[str] = []
    quote: str | None = None
    i = 0
    while i < len(command):
        char = command[i]
        if char == "\\" and quote != "'":
            out.append(command[i : i + 2])
            i += 2
            continue
        if char in QUOTES:
            quote = toggled(quote, char)
        elif char == "#" and quote is None and (i == 0 or command[i - 1] in " \t\n;&|()"):
            end = command.find("\n", i)
            i = len(command) if end < 0 else end
            continue
        out.append(char)
        i += 1
    return "".join(out)


def simple_commands(command: str) -> list[list[str]]:
    """Split a command line into its simple commands, each a list of words.

    Raises:
        ValueError: The shell quoting cannot be parsed.
    """
    lexer = shlex.shlex(command, posix=True, punctuation_chars=OPERATORS)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True  # keep $VAR, a:b and ${X:-y} inside one word
    lexer.commenters = ""  # shlex would swallow the newline after a comment
    found: list[list[str]] = []
    current: list[str] = []
    for token in [*lexer, ";"]:
        if token and all(char in OPERATORS for char in token):
            if current:
                found.append(current)
            current = []
        else:
            current.append(token)
    return found


def without_prefix(command: list[str]) -> list[str]:
    """Drop leading wrapper words and `NAME=value` assignments: `X=1 time wk ...` -> `wk ...`."""
    start = 0
    while start < len(command) and (
        command[start] in PREFIX_WORDS or ASSIGNMENT.match(command[start])
    ):
        start += 1
    return command[start:]


def shell_program(command: list[str], index: int) -> str | None:
    """Return the program of `sh -c '<program>'` when the word at `index` is a shell."""
    if command[index].rsplit("/", 1)[-1] not in SHELLS:
        return None
    for flag in range(index + 1, len(command) - 1):
        if SHELL_COMMAND_FLAG.fullmatch(command[flag]):
            rest = command[flag + 1 :]
            # `bash -c -- '<program>'`: the program follows the end-of-options mark.
            return rest[1] if rest[0] == "--" and len(rest) > 1 else rest[0]
    return None


def takes_next_word(flag: str) -> bool:
    """Tell whether a flag the guard does not know may take the next word as its value."""
    alone = flag.startswith("--") or len(flag) == SHORT_FLAG_LENGTH  # not joined ones: -jq
    return alone and "=" not in flag and flag not in SWITCHES


def may_run(tokens: list[str], path: tuple[str, ...]) -> bool:
    """Tell whether a wk call runs the subcommand `path` in some reading of its flags.

    wk finds its subcommand the way its command-line library does. The word after `-p`,
    `--profile`, `--store-type` or `--timeout` is a value. A switch of wk and a flag with `=` take
    nothing. Any other flag belongs to a subcommand and may stand before it: wk then skips the
    next word as its value, unless a newer wk knows that flag as a switch. Both readings are
    followed, so `wk --folder 5 pull` and `wk --new-switch pull` are both `wk pull`.
    """
    # A state is how many words of the path are matched and what the next word is: "" a word of
    # its own, "value" the value of the flag before it, "maybe" one or the other.
    states = {(0, "")}
    for token in tokens:
        after: set[tuple[int, str]] = set()
        for matched, pending in states:
            if pending:
                after.add((matched, ""))  # the word read as the value of the flag before it
            if pending == "value":
                continue
            if token in FLAGS_WITH_VALUE:
                after.add((matched, "value"))
            elif token.startswith("-"):
                after.add((matched, "maybe" if takes_next_word(token) else ""))
            elif token == path[matched]:
                if matched + 1 == len(path):
                    return True
                after.add((matched + 1, ""))
            # Any other word is the subcommand, and it is not the one looked for.
        states = after
    return False


def fixed_words(tokens: list[str]) -> int:
    """Count the words of a wk call that are no flag and cannot be the value of one."""
    count = 0
    pending = False
    for token in tokens:
        if token.startswith("-"):
            pending = token in FLAGS_WITH_VALUE or takes_next_word(token)
        else:
            count += not pending
            pending = False
    return count


def short_output(letters: str, rest_of_call: Iterator[str]) -> list[str]:
    """Return the file that `-o` names in one word of short flags: `-o F`, `-oF`, `-o=F`, `-jo F`.

    A short flag that takes a value takes the rest of its word, or the next word when nothing
    is left. `-p` does the same, so the `o` of `-pprod` is part of a profile name.
    """
    for position, letter in enumerate(letters):
        rest = letters[position + 1 :]
        if letter in VALUE_LETTERS:
            if not rest:
                next(rest_of_call, None)
            return []
        if letter == OUTPUT_LETTER:
            if not rest:
                return [next(rest_of_call, "")]
            return [rest[1:] if rest.startswith("=") and len(rest) > 1 else rest]
    return []


def output_targets(tokens: list[str]) -> list[str]:
    """Return every file a wk call names with -o or --output; wk writes to the last one."""
    targets: list[str] = []
    rest_of_call = iter(tokens)
    for token in rest_of_call:
        if token in FLAGS_WITH_VALUE:
            next(rest_of_call, None)  # its value, whatever that word looks like
        elif token == OUTPUT_FLAG:
            targets.append(next(rest_of_call, ""))
        elif token.startswith(f"{OUTPUT_FLAG}="):
            targets.append(token.partition("=")[2])
        elif token.startswith("-") and not token.startswith("--"):
            targets.extend(short_output(token[1:], rest_of_call))
    return targets


def inside_cache(target: str) -> bool:
    """Tell whether an output path is a plain file path below the working cache tmp/."""
    parts = target.split("/")
    plain = not any(char in target for char in EXPANDED_BY_SHELL) and ".." not in parts
    below = target.removeprefix("./").startswith(OUTPUT_FOLDER) or target.startswith(CACHES)
    return plain and below and bool(parts[-1])


def is_program(command: list[str], index: int) -> bool:
    """Tell whether the word at `index` is what the simple command runs, not an argument of it.

    True for the first word, after a launcher (`timeout 30 wk`) and after what is left of a
    prefix word with flags (`time -p wk`, `env -u X wk`).
    """
    first = command[0]
    return index == 0 or first.startswith("-") or first.rsplit("/", 1)[-1] in LAUNCHERS


def forbidden_wk(command: list[str], index: int) -> str | None:
    """Return why the wk call that starts at the word `index` is forbidden, or None."""
    word = command[index]
    # `wk` as a word anywhere in the simple command: xargs wk, env -u X wk, time -p wk.
    # A path to it counts as the command when it comes first or follows a plain word
    # (`xargs /opt/homebrew/bin/wk`), not when it is the value of an option (`git -C ~/src/wk`).
    by_path = word.endswith("/wk") and (index == 0 or not command[index - 1].startswith("-"))
    if word != "wk" and not by_path:
        return None
    arguments = command[index + 1 :]
    groups = (
        (EXPORT_COMMANDS, WHY_EXPORT),
        (IMPORT_COMMANDS, WHY_IMPORT),
        (TOKEN_COMMANDS, WHY_PRINT),
    )
    for group, why in groups:
        for path in group:
            if may_run(arguments, path):
                return why.format(" ".join(path))
    fed = any(before.rsplit("/", 1)[-1] == "xargs" for before in command[:index])
    runs = is_program(command, index)
    checks = (
        (fed and fixed_words(arguments) < STDIN_WORDS, WHY_STDIN),
        (runs and any(arg.split("=")[0] == DEBUG_FLAG for arg in arguments), WHY_DEBUG),
        (runs and not all(map(inside_cache, output_targets(arguments))), WHY_OUTPUT),
    )
    return next((reason for failed, reason in checks if failed), None)


def names_token_file(word: str) -> bool:
    """Tell whether a shell word is the token file, as a path or as a glob that matches it."""
    folder, _, name = word.rpartition("/")
    if name == TOKEN_FILE:
        return True
    # A glob counts when it spells part of the name (`*.env`, `prof*`), not when it is `*` alone,
    # and only in the current folder: `tmp/p*` is not the token file.
    is_glob = any(char in name for char in GLOB_CHARACTERS) and any(c.isalnum() for c in name)
    return is_glob and folder in ("", ".") and fnmatch.fnmatchcase(TOKEN_FILE, name)


def split_string(command: list[str]) -> Iterator[str]:
    """Yield the command line of every `env -S '<command line>'` in a simple command."""
    for position, word in enumerate(command):
        if word in SPLIT_FLAGS and position + 1 < len(command):
            yield command[position + 1]
        elif word.startswith("--split-string="):
            yield word.partition("=")[2]
        elif word.startswith("-S") and len(word) > len("-S"):
            yield word[2:]


def reads_token_file(command: list[str]) -> str | None:
    """Return why a simple command that names the token file is blocked, or None."""
    if not any(names_token_file(word) for word in command):
        return None
    program = command[0].rsplit("/", 1)[-1]
    blind_git = program == "git" and len(command) > 1 and command[1] in BLIND_GIT_COMMANDS
    if program in BLIND_PROGRAMS or blind_git:
        return None
    return (
        f"`{TOKEN_FILE}` holds API tokens as plain text: a shell command may not read, copy, "
        "move or print it. A person edits it in an editor (docs/setup/workato.md)."
    )


def handed_on(commands: list[list[str]]) -> str | None:
    """Return why a command line that names the token file next to `xargs` is blocked, or None."""
    named = any(names_token_file(word) for raw in commands for word in raw)
    hands_on = any(word.rsplit("/", 1)[-1] == "xargs" for raw in commands for word in raw)
    if not (named and hands_on):
        return None
    return (
        f"`{TOKEN_FILE}` holds API tokens as plain text: its name may not be handed to `xargs`, "
        "which would pass it on to a program that reads it."
    )


def simple_reason(raw: list[str], depth: int) -> str | None:
    """Return why one simple command is blocked, or None."""
    for line in split_string(raw):
        reason = verdict(line, depth + 1)
        if reason:
            return reason
    simple = without_prefix(raw)
    reason = reads_token_file(simple) if simple else None
    for index in range(len(simple)):
        if reason:
            break
        nested = shell_program(simple, index)
        reason = verdict(nested, depth + 1) if nested is not None else None
        reason = reason or forbidden_wk(simple, index)
    return reason


def verdict(command: str, depth: int = 0) -> str | None:
    """Return why a shell command is blocked, or None when it may run."""
    if depth > MAX_DEPTH:
        return "Shell nesting is too deep for the wk guard; simplify the command."
    command, programs, expanded = heredocs(command)
    command = strip_comments(
        command.replace("\\\n", " ")
    )  # a backslash-newline continues the line
    programs.extend(substitutions(command))
    for body in expanded:
        programs.extend(substitutions(body, heredoc=True))
    for program in programs:
        reason = verdict(program, depth + 1)
        if reason:
            return reason
    try:
        commands = simple_commands(command)
    except ValueError:
        return "Cannot parse shell quoting; simplify the command for the wk guard."
    reasons = (simple_reason(raw, depth) for raw in commands)
    return handed_on(commands) or next((reason for reason in reasons if reason), None)


def main(argv: list[str] | None = None) -> int:
    """Read the hook payload from stdin; return 0 to let the command run or 2 to block it."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    parser.parse_args(argv)
    try:
        payload = json.load(sys.stdin)
        if payload.get("tool_name", "Bash") != "Bash":
            return ALLOW
        command = payload["tool_input"]["command"]
    except ValueError, AttributeError, KeyError, TypeError:
        print("Invalid wk guard hook payload", file=sys.stderr)
        return BLOCK
    if not isinstance(command, str):
        print("Invalid shell command in wk guard hook payload", file=sys.stderr)
        return BLOCK
    if "wk" not in command and "profiles" not in command and ".env" not in command:
        # A glob can spell the token file without naming it: `cat prof*`. Only such a command
        # is parsed in full; every other command without the three words runs unparsed.
        candidates = (word.strip(QUOTES) for word in re.split(r"[\s;&|()<>]+", command))
        if not any(names_token_file(word) for word in candidates):
            return ALLOW
    try:
        reason = verdict(command)
    except Exception as error:  # noqa: BLE001 - a guard bug must not wave a wk command through
        reason = f"The wk guard failed on this command ({type(error).__name__}); simplify it."
    if reason:
        print(reason, file=sys.stderr)
        return BLOCK
    return ALLOW


if __name__ == "__main__":
    sys.exit(main())
