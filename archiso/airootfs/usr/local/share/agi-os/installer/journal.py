"""Structured, secret-free logging of AGIOS components into journald.

Every record carries SYSLOG_IDENTIFIER=agios-<component>, a machine-readable
AGIOS_EVENT name and, while an operation (preview build, finalization) runs, its
AGIOS_OPERATION id, so one `journalctl -b -t agios-web -t agios-storage ...`
shows a whole installation across the website and its root helpers. Records go
over journald's native datagram protocol: no extra packages, and stdout stays
free for the JSON protocols the helpers speak.

Nothing here is allowed to break the caller. Outside Live (unit tests,
development on a workstation) records are dropped unless AGIOS_LOG_JOURNAL=1
or AGIOS_LOG_STDERR=1 asks for them.
"""

import contextvars
import json
import os
import re
import socket
import struct
import sys
import traceback
import uuid

SOCKET = "/run/systemd/journal/socket"
IDENTIFIERS = ("agios-web", "agios-storage", "agios-finalize", "agios-worker", "agios-guest")
LEVELS = {"error": 3, "warning": 4, "info": 6, "debug": 7}
MAX_MESSAGE = 16_000
MAX_DATA = 32_000
MASK = "***"
TRACE = re.compile(r"[a-z]{1,16}-[0-9a-f]{12}")

operation = contextvars.ContextVar("agios_operation", default=None)

SECRET_KEYS = re.compile(
    r"^(pass(word|phrase)?|secret|token|key|api[_-]?key|apikey|authorization|cookie|credentials?|"
    r".*_(password|passphrase|token|secret)|(api|private|secret|access|ssh|encryption|luks)[_-]?key|"
    r"(access|refresh|id|session)[_-]?token|client[_-]?secret)$",
    re.IGNORECASE)
PATTERNS = (
    # key: value / key=value / "key": "value" for secret-looking names.
    (re.compile(r"""(?ix)
        (["']?\b(?:password|passphrase|passwd|secret|api[_-]?key|apikey|x-api-key|access[_-]?token|
                 refresh[_-]?token|id[_-]?token|token|client[_-]?secret)\b["']?\s*[:=]\s*)
        (["']?)[^"'\s,;}&]+"""), r"\1\2" + MASK),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 " + MASK),
    (re.compile(r"\b(sk|rk|pk)-[A-Za-z0-9_-]{16,}"), MASK),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"), MASK),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), MASK),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), MASK),
    # crypt(3) hashes as written by chpasswd -e or found in shadow files.
    (re.compile(r"\$(?:y|gy|7|6|5|2[aby]|argon2id?|sha512|md5)\$[^\s:\"']{8,}"), MASK),
    (re.compile(r"(?i)(://[^/\s:@]+:)[^@\s/]+@"), r"\1" + MASK + "@"),
)


def redact(value):
    """A copy of value with secrets masked: secret-named keys, known token formats, crypt hashes."""
    if isinstance(value, dict):
        return {k: (MASK if isinstance(k, str) and SECRET_KEYS.match(k) and v not in (None, "", False)
                    else redact(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    if isinstance(value, str):
        for pattern, replacement in PATTERNS:
            value = pattern.sub(replacement, value)
    return value


def new_operation(kind):
    return f"{kind}-{uuid.uuid4().hex[:12]}"


def adopt(request):
    """Take the caller's correlation id out of a helper request (it is not part of the request)."""
    trace = request.pop("trace", None) if isinstance(request, dict) else None
    if isinstance(trace, str) and TRACE.fullmatch(trace):
        operation.set(trace)
    return request


def _field(name, value):
    data = value.encode("utf-8", "replace")
    key = name.encode()
    if b"\n" in data:
        return key + b"\n" + struct.pack("<Q", len(data)) + data + b"\n"
    return key + b"=" + data + b"\n"


def _journal(fields):
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
        sock.sendto(b"".join(_field(k, v) for k, v in fields.items()), SOCKET)


def _stderr(fields):
    print(json.dumps(fields, ensure_ascii=False), file=sys.stderr, flush=True)


def enabled():
    """journald of the Live system (and of the preview VM guest, which boots the same medium).
    Unit tests and development runs on a workstation do not write into its journal."""
    return os.path.ismount("/run/archiso/bootmnt") or os.environ.get("AGIOS_LOG_JOURNAL") == "1"


def sink(fields):
    """Deliver one record; tests replace this function."""
    if os.environ.get("AGIOS_LOG_STDERR") == "1":
        _stderr(fields)
    elif enabled() and os.path.exists(SOCKET):
        _journal(fields)


def _clip(text, limit):
    return text if len(text) <= limit else text[:limit] + f"… [обрезано {len(text) - limit} символов]"


class Logger:
    def __init__(self, component):
        self.identifier = "agios-" + component
        self.component = component

    def log(self, level, event, message, exc=None, **data):
        try:
            text = str(message)
            if exc is not None:
                # In MESSAGE itself, so plain journalctl and the preview VM's serial log show it too.
                text += "\n" + "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            fields = {"MESSAGE": _clip(redact(text), MAX_MESSAGE), "PRIORITY": str(LEVELS[level]),
                      "SYSLOG_IDENTIFIER": self.identifier, "AGIOS_COMPONENT": self.component,
                      "AGIOS_EVENT": event}
            current = data.pop("operation", None) or operation.get()
            if current:
                fields["AGIOS_OPERATION"] = str(current)
            if data:
                fields["AGIOS_DATA"] = _clip(json.dumps(redact(data), ensure_ascii=False, default=str), MAX_DATA)
            if exc is not None:
                fields["AGIOS_ERROR"] = type(exc).__name__
            sink(fields)
        except Exception:
            # Logging must never change the outcome of an installation step.
            pass

    def debug(self, event, message, **data):
        self.log("debug", event, message, **data)

    def info(self, event, message, **data):
        self.log("info", event, message, **data)

    def warning(self, event, message, **data):
        self.log("warning", event, message, **data)

    def error(self, event, message, **data):
        self.log("error", event, message, **data)
