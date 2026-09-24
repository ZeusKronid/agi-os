"""Checks of the configuration files written by the model (home_files/system_files).

Two layers:
* static() parses the text with the standard library before anything is installed; a
  failure rejects the proposal and goes back to the model through Controller.respond;
* tool_checks() names the checkers of the programs themselves (foot, sway, Hyprland…)
  that the worker runs inside the installed system, where those programs exist.

Only well-defined syntaxes are checked: a false alarm would block a valid system.
"""

import ast
import configparser
import json
import re
import tomllib
import xml.etree.ElementTree as ElementTree
from pathlib import PurePosixPath


class ConfigCheckError(ValueError):
    pass


SYSTEMD_UNITS = (".service", ".socket", ".timer", ".path", ".target", ".mount", ".automount",
                 ".slice", ".scope", ".swap", ".device")


# Programs whose .json settings allow comments and trailing commas (VS Code writes them itself).
JSONC_OWNERS = ("Code", "Code - OSS", "VSCodium", "Cursor", "zed", "waybar", "fastfetch")


def display(scope, path):
    return ("~/" if scope == "home" else "/") + path


def kind(scope, path):
    """The syntax of a file by its location, or None when it is not checked statically."""
    posix = PurePosixPath(path)
    name, suffix, parts = posix.name, posix.suffix.lower(), posix.parts
    if suffix == ".jsonc" or (len(parts) >= 2 and parts[-2] == "waybar" and name == "config") or (
            suffix == ".json" and any(part in JSONC_OWNERS for part in parts)):
        return "jsonc"
    if suffix == ".json":
        return "json"
    if suffix == ".toml":
        return "toml"
    if suffix == ".xml":
        return "xml"
    if suffix == ".desktop":
        return "desktop"
    if suffix == ".py":
        return "python"
    if suffix in SYSTEMD_UNITS and "systemd" in parts:
        return "systemd"
    if suffix == ".conf" and "systemd" in parts:
        return "systemd"  # logind.conf, *.conf.d/ drop-ins: the same INI dialect.
    if suffix == ".conf" and "xorg.conf.d" in parts:
        return "xorg"
    if name == "hyprland.conf" or (len(parts) >= 2 and parts[-2] in ("sway", "i3") and name == "config"):
        return "braces"
    if suffix == ".conf" and "lightdm" in parts or suffix == ".ini" and "foot" in parts:
        return "ini"  # GKeyFile and foot: only «key=value».
    if suffix == ".ini":
        return "ini-any"
    return None


FORMATS = {"json": "JSON", "jsonc": "JSON with comments", "toml": "TOML", "xml": "XML",
           "desktop": "desktop file", "python": "Python", "systemd": "systemd format",
           "xorg": "xorg.conf format", "braces": "matching braces", "ini": "INI", "ini-any": "INI"}


def strip_jsonc(text):
    """JSON with // and /* */ comments and trailing commas (waybar) → strict JSON.
    Line breaks inside comments are kept so reported line numbers stay right."""
    out, i, n = [], 0, len(text)
    while i < n:
        char = text[i]
        if char == '"':
            end = i + 1
            while end < n and text[end] != '"':
                end += 2 if text[end] == "\\" else 1
            out.append(text[i:end + 1])
            i = end + 1
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                raise ConfigCheckError("unclosed comment /*")
            out.append("\n" * text.count("\n", i, end))
            i = end + 2
        else:
            out.append(char)
            i += 1
    return drop_trailing_commas("".join(out))


def drop_trailing_commas(text):
    """Remove a comma that only precedes } or ]; strings are copied untouched."""
    out, i, n = [], 0, len(text)
    while i < n:
        char = text[i]
        if char == '"':
            end = i + 1
            while end < n and text[end] != '"':
                end += 2 if text[end] == "\\" else 1
            out.append(text[i:end + 1])
            i = end + 1
            continue
        if char == ",":
            following = text[i + 1:].lstrip()
            if following[:1] in ("}", "]"):
                i += 1
                continue
        out.append(char)
        i += 1
    return "".join(out)


def check_ini(text, sections_required, delimiters="="):
    """Lines are blank, comments, [section] or key=value; systemd also allows
    backslash continuations and forbids keys before the first section. A generic
    .ini may also use «key: value» (Python configparser and others accept it)."""
    section = None
    continued = False
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if continued:
            continued = line.endswith("\\")
            continue
        if not line or line[0] in "#;":
            continue
        if line.startswith("["):
            if not re.fullmatch(r"\[[^\[\]]+\]", line):
                raise ConfigCheckError(f"line {number}: invalid section header {line[:80]}")
            section = line
            continue
        position = min((line.find(d) for d in delimiters if d in line), default=-1)
        if position <= 0 or not line[:position].strip():
            raise ConfigCheckError(f"line {number}: expected “key=value”, got {line[:80]}")
        if sections_required and section is None:
            raise ConfigCheckError(f"line {number}: setting outside a [..] section")
        continued = sections_required and line.endswith("\\")


def check_desktop(text):
    check_ini(text, True)
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    try:
        parser.read_string(text)
    except configparser.Error as exc:
        raise ConfigCheckError(str(exc).splitlines()[0])
    if not parser.has_section("Desktop Entry"):
        raise ConfigCheckError("no [Desktop Entry] section")
    entry = parser["Desktop Entry"]
    # Name is what every reader needs; a missing Type is tolerated (session files often omit it).
    if not entry.get("Name", "").strip():
        raise ConfigCheckError("[Desktop Entry] has no required Name key")
    if entry.get("Type", "Application").strip() == "Application" and not entry.get("Exec", "").strip():
        raise ConfigCheckError("the application (Type=Application) has no Exec key")


def check_xorg(text):
    depth = 0
    for number, raw in enumerate(text.splitlines(), 1):
        word = raw.split("#", 1)[0].strip().split(maxsplit=1)
        keyword = word[0].lower() if word else ""
        if keyword in ("section", "subsection"):
            depth += 1
        elif keyword in ("endsection", "endsubsection"):
            depth -= 1
            if depth < 0:
                raise ConfigCheckError(f"line {number}: {word[0]} without an opening section")
    if depth:
        raise ConfigCheckError("a section is not closed (no EndSection)")


def check_braces(text, inline_comments=False):
    """hyprland.conf, sway and i3 configs: every block { … } is closed. Comments are
    ignored (Hyprland also has them after text); braces inside quotes do not count."""
    depth = 0
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if inline_comments:
            line = line.split("#", 1)[0]
        if line.startswith("#"):
            continue
        line = re.sub(r'"(?:[^"\\]|\\.)*"', '""', line)
        line = re.sub(r"'[^']*'", "''", line)
        for char in line:
            depth += {"{": 1, "}": -1}.get(char, 0)
            if depth < 0:
                raise ConfigCheckError(f"line {number}: extra closing brace }}")
    if depth:
        raise ConfigCheckError("a block { … } is not closed: a closing brace } is missing")


def static(scope, path, content):
    """Raise ConfigCheckError with a readable reason when the file cannot be valid."""
    syntax = kind(scope, path)
    try:
        if syntax == "json":
            json.loads(content)
        elif syntax == "jsonc":
            json.loads(strip_jsonc(content))
        elif syntax == "toml":
            tomllib.loads(content)
        elif syntax == "xml":
            ElementTree.fromstring(content)
        elif syntax == "desktop":
            check_desktop(content)
        elif syntax == "python":
            ast.parse(content, filename=path)
        elif syntax == "systemd":
            check_ini(content, True)
        elif syntax == "xorg":
            check_xorg(content)
        elif syntax == "braces":
            check_braces(content, PurePosixPath(path).name == "hyprland.conf")
        elif syntax == "ini":
            check_ini(content, False)
        elif syntax == "ini-any":
            check_ini(content, False, "=:")
    except ConfigCheckError as exc:
        raise ConfigCheckError(f"File {display(scope, path)} ({FORMATS[syntax]}): {exc}")
    except json.JSONDecodeError as exc:
        raise ConfigCheckError(f"File {display(scope, path)} ({FORMATS[syntax]}): line {exc.lineno}: {exc.msg}")
    except tomllib.TOMLDecodeError as exc:
        raise ConfigCheckError(f"File {display(scope, path)} (TOML): {exc}")
    except ElementTree.ParseError as exc:
        raise ConfigCheckError(f"File {display(scope, path)} (XML): {exc}")
    except SyntaxError as exc:
        raise ConfigCheckError(f"File {display(scope, path)} (Python): line {exc.lineno}: {exc.msg}")
    return syntax


HINTS = {"systemd-analyze": "Files from system_files are written with mode 0644: a script in ExecStart will not be "
                              "executable — run it through an interpreter (ExecStart=/usr/bin/bash /path) "
                              "or use a program from a package."}


def tool_checks(scope, path):
    """Checkers of the program that reads the file, as (label, candidate binaries, args,
    run_as_user). `{file}` is the absolute path inside the installed system. The worker
    uses the first binary present in the target and skips the check when none is."""
    posix = PurePosixPath(path)
    name, suffix, parts = posix.name, posix.suffix.lower(), posix.parts
    user = scope == "home"
    checks = []
    if suffix == ".ini" and "foot" in parts:
        checks.append(("foot", ("usr/bin/foot",), ["--check-config", "--config", "{file}"], user))
    if len(parts) >= 2 and parts[-2] == "sway" and name == "config":
        checks.append(("sway", ("usr/bin/sway",), ["--validate", "--config", "{file}"], user))
    if len(parts) >= 2 and parts[-2] == "i3" and name == "config":
        checks.append(("i3", ("usr/bin/i3",), ["-C", "-c", "{file}"], user))
    if name == "hyprland.conf":
        checks.append(("Hyprland", ("usr/bin/Hyprland",), ["--verify-config", "--config", "{file}"], True))
    if suffix == ".lua":
        checks.append(("luac", ("usr/bin/luac", "usr/bin/luac5.4", "usr/bin/luac5.3", "usr/bin/luac5.1"),
                       ["-p", "{file}"], False))
    if suffix == ".sh":
        checks.append(("bash -n", ("usr/bin/bash",), ["-n", "{file}"], False))
    if scope == "system" and suffix in SYSTEMD_UNITS and "systemd" in parts:
        checks.append(("systemd-analyze", ("usr/bin/systemd-analyze",), ["verify", "--man=no", "{file}"], False))
    return checks


def summary(scope, path):
    """What will be checked for the review block."""
    labels = [FORMATS[s] for s in (kind(scope, path),) if s]
    labels += [label for label, *_ in tool_checks(scope, path)]
    return labels
