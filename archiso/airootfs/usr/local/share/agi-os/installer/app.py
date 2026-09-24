"""Native GTK installer in the Helios «Sunrise» design. Run with --demo to preview without network or disk writes."""

import argparse
import ctypes
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import cairo
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo

from controller import Controller, DemoCatalog, DemoProvider
from domain import ValidationError
from english import english
from providers import APIProvider, PROVIDERS, ProviderError
from bridge import BridgeProvider, PORT as BRIDGE_PORT
from system import demo_inventory, inventory, selected_disk


HERE = Path(__file__).resolve().parent
# Newsreader, Geist and Geist Mono ship in the ISO under /usr/share/fonts/agios. The same relative path
# works from a checkout, so a local run gets the brand fonts without installing them.
FONTS = HERE.parents[3] / "share/fonts/agios"


def load_fonts():
    try:
        fontconfig = ctypes.CDLL("libfontconfig.so.1")
        fontconfig.FcConfigAppFontAddDir(None, str(FONTS).encode())
    except OSError:
        pass


load_fonts()

ACCENT = (1, 0.416, 0.239)
CANVAS = (0.043, 0.035, 0.031)
PHASES = ("Hello", "Conversation", "Confirm", "Sunrise")
# Where the phase dots sit on the arc, 0 = left horizon, 1 = right horizon.
PHASE_DOTS = (0.14, 0.38, 0.62, 0.86)
WAYS = (
    ("account", "ChatGPT", "sign in to your account"),
    ("key", "API key", "OpenAI · Claude · Gemini"),
    ("local", "Ollama", "local, no cloud"),
)
KEY_PROVIDERS = (("openai", "OpenAI"), ("anthropic", "Anthropic"), ("gemini", "Gemini"), ("compatible", "Other API"))
PROVIDER_NAMES = {"chatgpt": "ChatGPT", "openai": "OpenAI", "anthropic": "Anthropic", "gemini": "Gemini",
                  "ollama": "Ollama", "compatible": "Other API", "bridge": "Test bridge"}
PROVIDER_NOTES = {
    "chatgpt": "Sign-in opens in the browser of this live system.",
    "ollama": "For Ollama on the QEMU host, use http://10.0.2.2:11434.",
    "bridge": "Test mode: uses the Codex sign-in on the host.",
}
API_NOTE = ("The key stays in memory only while the installer is open and never enters the chat. "
            "API usage may be billed separately from a subscription.")
FIRST_QUESTION = ("What system do you want? Describe it in your own words: desktop, apps, what the computer "
                  "is for. Name any desktop or window manager, go without a GUI, or ask me to suggest options.")
# Install substeps and the share of the sunrise they start at.
SUBSTEPS = (("Check", 0.0), ("Partitions", 0.08), ("Base", 0.16), ("Packages", 0.42), ("Setup", 0.82))
# Infrastructure packages that say little about the system the person asked for.
QUIET_PACKAGES = re.compile(r"^(greetd|pipewire|wireplumber|noto-|ttf-|xdg-|mesa|networkmanager|lib|base|linux|polkit|sudo)")

CSS = b"""
viewport, scrolledwindow, stack, revealer, overlay, flowbox { background-color: transparent; background-image: none; border: none; }
flowboxchild { padding: 0; background-color: transparent; }
window, .root { background-color: #0b0908; color: #f6f2ec; font-family: Geist, "Noto Sans", sans-serif; font-size: 15px; }
label { color: #f6f2ec; }
label selection { background-color: rgba(255,106,61,.35); }
.brand { font-family: Newsreader, serif; font-size: 19px; }
.caps { font-family: "Geist Mono", monospace; font-size: 10.5px; letter-spacing: 1.7px; color: #8f887e; }
.caps.accent { color: #ff6a3d; }
.muted { color: #8f887e; }
.dim { color: #615a52; }
.soft { color: #d9d2c7; }
.title { font-family: Newsreader, serif; font-size: 54px; letter-spacing: -1.4px; }
.compact .title { font-size: 36px; }
.pip { min-width: 18px; min-height: 3px; border-radius: 2px; background-color: #1f1a16; }
.pip.on { background-color: #ff6a3d; }
.dot { min-width: 6px; min-height: 6px; border-radius: 3px; background-color: #ff6a3d; }
.dot.off { background-color: #615a52; }
.blink { animation: blink 1.1s ease-in-out infinite; }
@keyframes blink { 50% { opacity: .25; } }

button { background-image: none; background-color: transparent; border: none; box-shadow: none; text-shadow: none;
         padding: 0; border-radius: 7px; outline-color: #ff6a3d; outline-style: solid; outline-width: 1px; outline-offset: 2px;
         transition: background-color 200ms, box-shadow 200ms, opacity 200ms; }
button label { color: #f6f2ec; }
button:disabled label { color: #615a52; }
.pill { min-height: 30px; padding: 0 12px; border-radius: 15px; background-color: rgba(17,14,12,.8);
        box-shadow: inset 0 0 0 1px rgba(255,255,255,.09); }
.pill label { font-family: "Geist Mono", monospace; font-size: 11.5px; color: #8f887e; }
.pill:hover:not(:disabled) { box-shadow: inset 0 0 0 1px rgba(255,106,61,.36); }
.pill:disabled { opacity: 1; }
.banner { padding: 7px 14px; border-radius: 10px; background-color: rgba(255,106,61,.12); color: #ff8159;
          font-family: "Geist Mono", monospace; font-size: 11.5px; }

.way { padding: 12px 16px; border-radius: 14px; background-color: rgba(17,14,12,.85);
       box-shadow: inset 0 0 0 1px rgba(255,255,255,.09); }
.way:hover { box-shadow: inset 0 0 0 1px rgba(255,106,61,.36); }
.way:checked { background-color: rgba(22,18,15,.9); box-shadow: inset 0 0 0 1px #ff6a3d; }
.way-title { font-family: Newsreader, serif; font-size: 19px; }
.way-sub { font-family: "Geist Mono", monospace; font-size: 11px; color: #8f887e; }
.compact .way { padding: 10px 12px; }
.compact .way-title { font-size: 16px; }
.compact .way-sub { font-size: 10px; }
.card { padding: 16px; border-radius: 16px; background-color: rgba(17,14,12,.92); box-shadow: inset 0 0 0 1px rgba(255,255,255,.09); }
.chip { min-height: 32px; padding: 0 13px; border-radius: 16px; box-shadow: inset 0 0 0 1px rgba(255,255,255,.14); }
.chip label { font-family: "Geist Mono", monospace; font-size: 12.5px; color: #d9d2c7; }
.chip:hover { box-shadow: inset 0 0 0 1px rgba(255,106,61,.36); }
.chip:checked { background-color: rgba(255,106,61,.12); box-shadow: inset 0 0 0 1px rgba(255,106,61,.36); }
.chip:checked label { color: #ff6a3d; }
.sug { min-height: 34px; padding: 0 14px; border-radius: 17px; box-shadow: inset 0 0 0 1px rgba(255,106,61,.36); }
.sug label { font-family: Newsreader, serif; font-size: 15px; }
.sug:hover { background-color: rgba(255,106,61,.12); }

entry { min-height: 44px; padding: 0 14px; border: none; border-radius: 8px; background-image: none; background-color: #16120f;
        box-shadow: inset 0 0 0 1px rgba(255,255,255,.09); color: #f6f2ec; caret-color: #ff6a3d;
        font-family: "Geist Mono", monospace; font-size: 14px; }
entry:focus { box-shadow: inset 0 0 0 1px #ff6a3d; }
entry.bad { box-shadow: inset 0 0 0 1px rgba(255,106,61,.5); }
entry selection { background-color: rgba(255,106,61,.35); color: #f6f2ec; }
entry image { color: #8f887e; }

.primary { min-height: 44px; padding: 0 18px; background-color: #ff6a3d; }
.primary label { color: #160b06; font-family: "Geist Mono", monospace; font-weight: 500; font-size: 13.5px; }
.primary:hover { background-color: #ff8159; }
.primary:disabled { background-color: rgba(255,106,61,.35); }
.primary:disabled label { color: #160b06; }
.outline { min-height: 44px; padding: 0 18px; box-shadow: inset 0 0 0 1px rgba(255,106,61,.36); }
.outline label { font-family: Newsreader, serif; font-size: 16px; }
.outline:hover { box-shadow: inset 0 0 0 1px #ff6a3d; }
.ghost { min-height: 36px; padding: 0 10px; }
.ghost label { font-family: "Geist Mono", monospace; font-size: 12px; color: #8f887e; }
.ghost:hover label { color: #f6f2ec; }
.link label { font-family: "Geist Mono", monospace; font-size: 11px; color: #ff6a3d; }
.err { color: #ff8159; font-size: 13.5px; }
.okline { color: #d9d2c7; font-size: 14px; }
.check { color: #5fe3a1; font-family: "Geist Mono", monospace; }
.hint { color: #615a52; font-size: 12.5px; }
.status { font-family: "Geist Mono", monospace; font-size: 11.5px; color: #615a52; }

.who { font-family: "Geist Mono", monospace; font-size: 10px; letter-spacing: 1.8px; color: #615a52; }
.ai-text { font-family: Newsreader, serif; font-size: 21px; color: #d9d2c7; }
.compact .ai-text { font-size: 18px; }
.me-text { padding: 10px 16px; border-radius: 18px 18px 6px 18px; background-color: rgba(255,106,61,.12); font-size: 15px; }
.thinking { font-family: "Geist Mono", monospace; font-size: 12px; color: #8f887e; }
.typing { min-width: 6px; min-height: 6px; border-radius: 3px; background-color: #8f887e; animation: typing 1.2s ease-in-out infinite; }
.typing.second { animation-delay: 150ms; }
.typing.third { animation-delay: 300ms; }
@keyframes typing { 0% { opacity: .3; } 30% { opacity: 1; } 60% { opacity: .3; } 100% { opacity: .3; } }
.ask { padding: 7px 7px 7px 22px; border-radius: 29px; background-color: rgba(22,18,15,.94);
       box-shadow: inset 0 0 0 1px rgba(255,255,255,.14); }
.ask.focused { box-shadow: inset 0 0 0 1px #ff6a3d; }
.ask entry { min-height: 44px; padding: 0; background-color: transparent; box-shadow: none; font-family: Newsreader, serif; font-size: 18px; }
.send { min-width: 44px; min-height: 44px; border-radius: 22px; padding: 0; }
.send label { font-size: 17px; }
.ready { min-height: 40px; padding: 0 16px; border-radius: 20px; background-color: #ff6a3d; }
.ready label { color: #160b06; font-family: "Geist Mono", monospace; font-weight: 500; font-size: 13px; }
.ready:hover { background-color: #ff8159; }

.veil { background-color: rgba(8,6,5,.55); }
.sheet { border-radius: 22px 22px 0 0; background-color: #110e0c; box-shadow: inset 0 1px 0 rgba(255,106,61,.36); }
.grab { min-width: 40px; min-height: 4px; border-radius: 2px; background-color: rgba(255,255,255,.14); }
.sheet-title { font-family: Newsreader, serif; font-size: 32px; letter-spacing: -.6px; }
.compact .sheet-title { font-size: 25px; }
.fact { border-top: 1px solid rgba(255,255,255,.09); padding: 10px 0; }
.fact-key { font-family: "Geist Mono", monospace; font-size: 10px; letter-spacing: 1.4px; color: #615a52; }
.fact-value { font-size: 14px; color: #d9d2c7; }
.files { font-family: "Geist Mono", monospace; font-size: 12px; color: #8f887e; }
expander title label { font-family: "Geist Mono", monospace; font-size: 12px; color: #8f887e; }
expander title arrow { color: #ff6a3d; }
.erase { padding: 22px; border-radius: 16px; background-color: #0b0908; box-shadow: inset 0 0 0 1px rgba(255,106,61,.36); }
.big { font-family: Newsreader, serif; font-size: 22px; }
.mono { font-family: "Geist Mono", monospace; font-size: 12px; color: #8f887e; }
.need { font-family: "Geist Mono", monospace; font-size: 11.5px; color: #615a52; }
.need.ok { color: #8f887e; }
.hold { min-height: 54px; border-radius: 27px; background-color: transparent; }
.hold label { font-family: "Geist Mono", monospace; font-weight: 500; font-size: 13px; color: #f6f2ec; }
.hold.full label { color: #160b06; }
.hold:disabled label { color: #615a52; }

.pct { font-family: Newsreader, serif; font-size: 96px; letter-spacing: -2.8px; }
.compact .pct { font-size: 64px; }
.cap { font-family: Newsreader, serif; font-size: 22px; color: #d9d2c7; }
.compact .cap { font-size: 18px; }
.substep { font-family: "Geist Mono", monospace; font-size: 10.5px; letter-spacing: 1.5px; color: #615a52; }
.substep.done { color: #8f887e; }
.substep.current { color: #ff6a3d; }
.done-title { font-family: Newsreader, serif; font-size: 60px; letter-spacing: -1.6px; }
.compact .done-title { font-size: 40px; }
.logbox { padding: 12px 14px; border-radius: 10px; background-color: #110e0c; box-shadow: inset 0 0 0 1px rgba(255,255,255,.09); }
textview, textview text { background-color: #110e0c; color: #8f887e; font-family: "Geist Mono", monospace; font-size: 12px; }
scrollbar, scrollbar trough { background-color: transparent; border: none; }
scrollbar slider { min-width: 5px; min-height: 5px; border: none; border-radius: 3px; background-color: rgba(255,255,255,.14); }
"""


def animations():
    return Gtk.Settings.get_default().props.gtk_enable_animations


def styled(widget, *classes):
    context = widget.get_style_context()
    for css in classes:
        context.add_class(css)
    return widget


def label(text="", *classes, wrap=True, xalign=0.0, markup=False):
    widget = Gtk.Label(xalign=xalign)
    if markup:
        widget.set_markup(text)
    else:
        widget.set_text(text)
    if wrap:
        widget.set_line_wrap(True)
        widget.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    return styled(widget, *classes)


def caps(text, *classes, xalign=0.0):
    return label(text.upper(), "caps", *classes, wrap=False, xalign=xalign)


def button(text, callback, *classes):
    widget = styled(Gtk.Button(label=text), *classes)
    widget.connect("clicked", callback)
    return widget


def box(orientation="v", spacing=0, *children, **props):
    widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if orientation == "v" else Gtk.Orientation.HORIZONTAL,
                     spacing=spacing, **props)
    for child in children:
        widget.pack_start(child, False, False, 0)
    return widget


def clear(container):
    for child in container.get_children():
        child.destroy()


def rise(widget, delay=0.0):
    """Entering content floats up 10px and fades in; nothing moves when GTK animations are off."""
    if not animations():
        return
    widget.set_opacity(0)
    start = []

    def step(w, clock):
        now = clock.get_frame_time() / 1e6
        if not start:
            start.append(now + delay)
        p = min(1.0, max(0.0, (now - start[0]) / 0.5))
        eased = 1 - (1 - p) ** 3
        w.set_opacity(eased)
        w.set_margin_top(round(10 * (1 - eased)))
        return p < 1
    widget.add_tick_callback(step)


def soon(callback, *args):
    """Run on the GTK thread ahead of redraws: the sun repaints every frame, and default-idle callbacks
    would wait behind it on a slow software-rendered VM."""
    GLib.idle_add(callback, *args, priority=GLib.PRIORITY_DEFAULT)


def open_browser_once(url, is_current=lambda: True):
    def open_url():
        if is_current():
            webbrowser.open(url)
        # webbrowser.open returns True; returning it to GLib would reopen forever.
        return GLib.SOURCE_REMOVE
    GLib.idle_add(open_url)


def mulberry(seed):
    state = seed & 0xFFFFFFFF

    def random():
        nonlocal state
        state = (state + 0x6D2B79F5) & 0xFFFFFFFF
        t = state
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296
    return random


class Sky(Gtk.DrawingArea):
    """The site's «Восход» drawn with Cairo: half circle, 97 rays with every fourth one long, and the shimmer
    from the hero's voice formula. The sun is the progress: phase dots sit on the arc and during installation
    the arc is drawn and the sun rises with the installed share. Values glide to their targets every frame."""

    RAYS = 97

    def __init__(self):
        super().__init__()
        random = mulberry(11)
        self.rays = []
        for index in range(self.RAYS + 1):
            major = index % 4 == 0
            length = 0.62 if major else 0.16 + random() * 0.28
            self.rays.append((index / self.RAYS, major, length, 0.4 + random() * 0.9,
                              1 / (0.26 + random() * 0.06), random() * math.tau))
        self.current = {"horizon": 0.44, "radius": 0.19, "arc": 0.0, "grow": 0.0, "energy": 0.3, "lift": 1.0, "dim": 1.0}
        self.target = dict(self.current)
        self.dots = []
        self.labels = []
        self.label_alpha = {}
        self.progress_listener = None
        self.time = 0.0
        self.last = None
        self.last_draw = 0.0
        self.paint_cost = 0.0
        self.backdrop = None
        self.busy = False
        self.connect("draw", self.paint)
        self.add_tick_callback(self.tick)

    def aim(self, **target):
        self.target.update(target)
        if not animations():
            self.current.update(self.target)
        self.queue_draw()

    def tick(self, widget, clock):
        now = clock.get_frame_time() / 1e6
        dt = 0.0 if self.last is None else min(0.1, now - self.last)
        self.last = now
        moving = animations()
        if moving:
            self.time += dt
            k = 1 - math.exp(-dt * 2.8)
            for key, value in self.target.items():
                self.current[key] += (value - self.current[key]) * k
            for text, alpha in list(self.label_alpha.items()):
                goal = 1.0 if any(word == text for _, word in self.labels) else 0.0
                self.label_alpha[text] = alpha + (goal - alpha) * (1 - math.exp(-dt * 3.5))
        else:
            self.current.update(self.target)
            for text in self.label_alpha:
                self.label_alpha[text] = 1.0 if any(word == text for _, word in self.labels) else 0.0
        if self.progress_listener:
            self.progress_listener(self.current["arc"])
        # The shimmer is ambient: 60 fps when painting is cheap, 30 fps while packages install or when a
        # software-rendered VM makes a frame expensive, nothing when animations are off.
        interval = 1 / 30 if self.busy or self.paint_cost > 0.006 else 1 / 62
        if moving and now - self.last_draw >= interval:
            self.last_draw = now
            self.queue_draw()
        return True

    def set_labels(self, words):
        self.labels = [(0.12 + i * 0.19, word) for i, word in enumerate(words[:5])]
        for _, word in self.labels:
            self.label_alpha.setdefault(word, 0.0 if animations() else 1.0)
        self.queue_draw()

    def paint(self, widget, cr):
        started = time.perf_counter()
        self.draw(widget, cr)
        self.paint_cost = self.paint_cost * 0.9 + (time.perf_counter() - started) * 0.1
        return False

    def draw(self, widget, cr):
        width, height = widget.get_allocated_width(), widget.get_allocated_height()
        s = self.current
        if not self.backdrop or self.backdrop.get_width() != width or self.backdrop.get_height() != height:
            self.backdrop = cr.get_target().create_similar(cairo.CONTENT_COLOR, width, height)
            ground = cairo.Context(self.backdrop)
            ground.set_source_rgb(*CANVAS)
            ground.paint()
            warm = cairo.RadialGradient(width / 2, height, 0, width / 2, height, max(width, height) * 0.75)
            warm.add_color_stop_rgba(0, 0.102, 0.059, 0.039, 1)
            warm.add_color_stop_rgba(1, *CANVAS, 0)
            ground.set_source(warm)
            ground.paint()
        cr.set_source_surface(self.backdrop, 0, 0)
        cr.paint()

        hy = s["horizon"] * height
        radius = min(s["radius"] * height, width * 0.36)
        cx, cy = width / 2, hy + (1 - s["lift"]) * radius * 1.25
        dim = s["dim"]
        glow = cairo.RadialGradient(cx, hy, 0, cx, hy, radius * 2.4)
        glow.add_color_stop_rgba(0, *ACCENT, (0.10 + 0.10 * s["energy"]) * dim)
        glow.add_color_stop_rgba(1, *ACCENT, 0)
        cr.save()
        cr.rectangle(0, 0, width, hy)
        cr.clip()
        cr.set_source(glow)
        cr.paint()

        # Rays: drawn as one group, then faded outwards through a radial mask.
        cr.push_group()
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_width(1.5)
        inner = radius + max(4, radius * 0.07)
        shimmer = animations()
        for major_pass in (False, True):
            for f, major, length, voice, speed, phase in self.rays:
                if major != major_pass:
                    continue
                grow = s["grow"] * max(0.0, min(1.0, (s["arc"] - f) * 5 + (1 if s["arc"] > 0.999 else 0)))
                if grow <= 0.001:
                    continue
                wave = 0.65 + 0.35 * math.sin(self.time * speed * math.pi + phase) if shimmer else 0.8
                ray = radius * length * grow * (1 + s["energy"] * voice * 0.7 * wave)
                angle = math.pi + f * math.pi
                ca, sa = math.cos(angle), math.sin(angle)
                cr.move_to(cx + ca * inner, cy + sa * inner)
                cr.line_to(cx + ca * (inner + ray), cy + sa * (inner + ray))
            cr.set_source_rgba(*ACCENT, dim * (1 if major_pass else 0.8))
            cr.stroke()
        rays = cr.pop_group()
        fade = cairo.RadialGradient(cx, cy, radius, cx, cy, radius * 2.05)
        fade.add_color_stop_rgba(0, 0, 0, 0, 1)
        fade.add_color_stop_rgba(0.45, 0, 0, 0, 0.6)
        fade.add_color_stop_rgba(1, 0, 0, 0, 0)
        cr.set_source(rays)
        cr.mask(fade)

        cr.set_line_width(1.5)
        cr.set_source_rgba(*ACCENT, dim)
        cr.arc(cx, cy, radius, math.pi, math.pi + max(0.0001, s["arc"]) * math.pi)
        cr.stroke()
        if s["arc"] > 0.98:
            cr.set_source_rgba(*ACCENT, dim * min(1, (s["arc"] - 0.98) * 50))
            cr.move_to(cx, cy - radius - 6)
            cr.line_to(cx, cy - radius * 1.9)
            cr.stroke()
            cr.arc(cx, cy - radius * 1.9 - 5, 2.4, 0, math.tau)
            cr.fill()
        pulse = (math.sin(self.time * 4) + 1) / 2 if shimmer else 0.5
        for f, state in self.dots:
            angle = math.pi + f * math.pi
            x, y = cx + math.cos(angle) * radius, cy + math.sin(angle) * radius
            size = 2.6 if state == "done" else 2.8 + 0.9 * pulse if state == "current" else 1.8
            if state == "current":
                cr.set_source_rgba(*ACCENT, 0.18 * dim)
                cr.arc(x, y, size + 5, 0, math.tau)
                cr.fill()
            cr.set_source_rgba(*ACCENT, dim * (0.5 if state == "next" else 1))
            cr.arc(x, y, size, 0, math.tau)
            cr.fill()
        if self.labels:
            layout = PangoCairo.create_layout(cr)
            font = Pango.FontDescription.from_string("Geist Mono Medium")
            font.set_absolute_size(max(10, min(12, radius * 0.07)) * Pango.SCALE)
            layout.set_font_description(font)
            spacing = Pango.AttrList()
            spacing.insert(Pango.attr_letter_spacing_new(int(1.2 * Pango.SCALE)))
            layout.set_attributes(spacing)
            for f, word in self.labels:
                alpha = self.label_alpha.get(word, 0)
                if alpha < 0.01:
                    continue
                angle = math.pi + f * math.pi
                distance = radius * 1.62 + (1 - alpha) * 14
                layout.set_text(word.upper(), -1)
                w, h = layout.get_pixel_size()
                cr.move_to(cx + math.cos(angle) * distance - w / 2, cy + math.sin(angle) * distance - h / 2)
                cr.set_source_rgba(0.851, 0.824, 0.78, alpha * dim)
                PangoCairo.show_layout(cr, layout)
        cr.restore()
        line = cairo.LinearGradient(0, 0, width, 0)
        line.add_color_stop_rgba(0, 1, 1, 1, 0)
        line.add_color_stop_rgba(0.5, 1, 1, 1, 0.14)
        line.add_color_stop_rgba(1, 1, 1, 1, 0)
        cr.set_source(line)
        cr.rectangle(0, hy, width, 1)
        cr.fill()
        return False


class HoldButton(Gtk.Button):
    """Erasing the disk is confirmed by holding for 1.5 s: mouse, touch, Space or Enter.
    Letting go early drains the fill and nothing happens."""

    DURATION = 1.5

    def __init__(self, on_done):
        super().__init__()
        self.on_done = on_done
        self.value = 0.0
        self.holding = False
        self.ticking = False
        self.last = None
        self.text = Gtk.Label()
        self.add(self.text)
        styled(self, "hold")
        self.connect("draw", self.paint)
        self.connect("button-press-event", lambda *_: self.start() or True)
        self.connect("button-release-event", lambda *_: self.stop() or True)
        self.connect("leave-notify-event", lambda *_: self.stop() or False)
        self.connect("key-press-event", self.key)
        self.connect("key-release-event", self.key)

    def key(self, widget, event):
        if event.keyval not in (Gdk.KEY_space, Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            return False
        if event.type == Gdk.EventType.KEY_PRESS:
            self.start()
        else:
            self.stop()
        return True

    def start(self):
        if not self.get_sensitive() or self.holding:
            return
        self.holding = True
        self.grab_focus()
        self.run()

    def stop(self):
        self.holding = False
        self.run()

    def reset(self):
        self.holding = False
        self.value = 0.0
        self.get_style_context().remove_class("full")
        self.queue_draw()

    def run(self):
        if not self.ticking:
            self.ticking = True
            self.last = None
            self.add_tick_callback(self.step)

    def step(self, widget, clock):
        now = clock.get_frame_time() / 1e6
        dt = 0.0 if self.last is None else now - self.last
        self.last = now
        self.value = min(1.0, self.value + dt / self.DURATION) if self.holding else max(0.0, self.value - dt * 3)
        context = self.get_style_context()
        (context.add_class if self.value > 0.55 else context.remove_class)("full")
        self.queue_draw()
        if self.value >= 1:
            self.ticking = False
            self.reset()
            soon(self.on_done)
            return False
        if not self.holding and self.value <= 0:
            self.ticking = False
            return False
        return True

    def paint(self, widget, cr):
        width, height = widget.get_allocated_width(), widget.get_allocated_height()
        r = height / 2
        cr.new_path()
        cr.arc(r, r, r, math.pi / 2, math.pi * 1.5)
        cr.arc(width - r, r, r, math.pi * 1.5, math.pi / 2)
        cr.close_path()
        cr.save()
        cr.clip_preserve()
        cr.set_source_rgba(0.122, 0.102, 0.086, 1 if self.get_sensitive() else 0.5)
        cr.fill_preserve()
        cr.set_source_rgba(*ACCENT, 1)
        cr.rectangle(0, 0, width * self.value, height)
        cr.fill()
        cr.restore()
        cr.set_line_width(2)
        cr.set_source_rgba(*ACCENT, 0.36 if self.get_sensitive() else 0.18)
        cr.stroke()
        return False


class EnglishDemoProvider(DemoProvider):
    model = "Interface demo"

    def reply(self, system, messages):
        reply = super().reply(system, messages)
        reply["message"] = ("This is a demo reply without an LLM. I prepared an example system with Sway. "
                            "You can open the summary and run a simulation; no real disk is changed.")
        reply["configuration"].update({
            "desktop": "Sway — demo example", "locale": "en_US.UTF-8", "timezone": "Europe/Berlin",
            "keyboard_layouts": ["us"], "requirements": ["A working Sway session", "Firefox browser", "US keyboard layout"],
        })
        return reply


class InstallerWindow(Gtk.Window):
    def __init__(self, demo=False):
        super().__init__(title="AGI OS — Installer")
        self.demo = demo
        self.provider = None
        self.controller = None
        self.worker = None
        self.installed_received = False
        self.busy = False
        self.kind = "chatgpt"
        self.way = "account"
        self.connected = False
        self.last_text = ""
        self.progress = 0.0
        self.size = (0, 0)
        self.connection_generation = 0
        self.connection_lock = threading.Lock()
        self.connect("delete-event", self.on_close)
        monitor = Gdk.Display.get_default().get_monitor(0).get_workarea()
        self.set_default_size(min(1140, monitor.width - 32), min(800, monitor.height - 64))
        self.set_position(Gtk.WindowPosition.CENTER)
        style = Gtk.CssProvider()
        style.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), style, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.overlay = Gtk.Overlay()
        self.add(self.overlay)
        self.sky = Sky()
        self.overlay.add(self.sky)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=380)
        self.overlay.add_overlay(self.stack)
        self.overlay.add_overlay(self.hud())
        self.banner = styled(Gtk.Label(), "banner")
        self.banner.set_no_show_all(True)
        self.overlay.add_overlay(self.banner)
        self.banner.set_halign(Gtk.Align.END)
        self.banner.set_valign(Gtk.Align.END)
        self.banner.set_margin_end(26)
        self.banner.set_margin_bottom(14)
        self.overlay.set_overlay_pass_through(self.banner, True)
        self.status = label("Checking the environment…", "status", wrap=False)
        self.status.set_ellipsize(Pango.EllipsizeMode.END)
        self.status.set_halign(Gtk.Align.START)
        self.status.set_valign(Gtk.Align.END)
        self.status.set_margin_start(26)
        self.status.set_margin_bottom(18)
        self.status.set_max_width_chars(60)
        self.overlay.add_overlay(self.status)
        self.overlay.set_overlay_pass_through(self.status, True)

        self.connect_page()
        self.chat_page()
        self.install_page()
        self.done_page()
        self.sheet()
        self.log_panel()
        self.overlay.connect("size-allocate", self.on_resize)

        self.show_all()
        self.sheet_revealer.set_reveal_child(False)
        self.veil.hide()
        self.set_banner("PREVIEW · no LLM and no disk writes" if demo else "")
        self.provider_changed()
        self.show_step("connect")
        self.background(lambda: demo_inventory() if demo else inventory(), self.inventory_ready)

    # ── layout ───────────────────────────────────────────────

    def hud(self):
        bar = Gtk.Box()
        bar.set_valign(Gtk.Align.START)
        bar.set_margin_top(22)
        bar.set_margin_start(26)
        bar.set_margin_end(26)
        bar.pack_start(label("AGI OS", "brand", wrap=False), False, False, 0)
        self.pips = [styled(Gtk.Box(), "pip") for _ in PHASES]
        pips = box("h", 5, *self.pips)
        pips.set_valign(Gtk.Align.CENTER)
        self.phase_label = caps(PHASES[0], "soft")
        bar.set_center_widget(box("h", 10, pips, self.phase_label))
        self.model_dot = styled(Gtk.Box(valign=Gtk.Align.CENTER), "dot", "off")
        self.model_label = label("no model", wrap=False)
        self.model_pill = styled(Gtk.Button(), "pill")
        self.model_pill.add(box("h", 8, self.model_dot, self.model_label))
        self.model_pill.set_tooltip_text("Change model")
        self.model_pill.connect("clicked", self.disconnect)
        bar.pack_end(self.model_pill, False, False, 0)
        return bar

    def on_resize(self, widget, allocation):
        size = (allocation.width, allocation.height)
        if size != self.size:
            self.size = size
            soon(self.relayout)

    def relayout(self):
        width, height = self.size
        compact = width < 860
        context = self.get_style_context()
        (context.add_class if compact else context.remove_class)("compact")
        self.aim_sky()
        short = self.short()
        self.hello_space.set_size_request(-1, int(height * (0.34 if short else 0.44)) + 24)
        self.hello.set_size_request(min(760, width - 40), -1)
        self.talk.set_size_request(min(700, width - 40), -1)
        self.talk_floor.set_size_request(-1, int(height * (0.25 if short else 0.33)))
        self.rise_floor.set_size_request(-1, height - int(height * 0.72) + 14)
        self.below.set_size_request(-1, height - int(height * 0.72) - 14)
        self.done_space.set_size_request(-1, int(height * (0.46 if short else 0.5)) + 22)
        self.done_box.set_size_request(min(680, width - 40), -1)
        self.sheet_box.set_size_request(-1, int(height * (0.9 if compact else 0.82)))
        self.sheet_grid.set_orientation(Gtk.Orientation.VERTICAL if compact else Gtk.Orientation.HORIZONTAL)
        return False

    def short(self):
        """Small VM screens (800×600, 1024×600) get a lower, smaller sun so the content fits."""
        return 0 < self.size[1] < 700

    def show_step(self, step):
        self.step = step
        self.stack.set_visible_child_name(step)
        phase = {"connect": 0, "chat": 1, "install": 3, "done": 3}[step]
        self.set_phase(phase)
        self.model_pill.set_sensitive(step == "chat" and self.provider is not None)
        self.aim_sky()

    def set_phase(self, phase):
        for index, pip in enumerate(self.pips):
            (pip.get_style_context().add_class if index <= phase else pip.get_style_context().remove_class)("on")
        self.phase_label.set_text(PHASES[phase].upper())
        self.sky.dots = [(f, "done" if i < phase else "current" if i == phase else "next") for i, f in enumerate(PHASE_DOTS)]
        self.sky.queue_draw()

    def aim_sky(self):
        if not hasattr(self, "step"):
            return
        thinking = self.busy and self.step == "chat"
        short = self.short()
        self.sky.busy = self.step == "install" and self.controller is not None and self.controller.installing
        if self.sheet_revealer.get_reveal_child():
            self.sky.aim(horizon=1.0, radius=0.13 if short else 0.17, arc=1, grow=1, energy=0.2, lift=1, dim=0.5)
        elif self.step == "connect":
            waiting = not self.connect_button.get_sensitive() and hasattr(self, "snapshot")
            self.sky.aim(horizon=0.34 if short else 0.44, radius=0.15 if short else 0.19, arc=1, grow=1 if self.connected else 0.8,
                         energy=0.9 if waiting else 0.7 if self.connected else 0.3, lift=1, dim=1)
        elif self.step == "chat":
            self.sky.aim(horizon=1.0, radius=0.13 if short else 0.17, arc=1, grow=1 if self.sky.labels else 0.8,
                         energy=1.1 if thinking else 0.35, lift=1, dim=1)
        elif self.step == "install":
            p = self.progress
            failed = self.install_state in ("error", "stopped")
            self.sky.aim(horizon=0.72, radius=0.24, arc=max(0.02, p), grow=0.5 + 0.6 * p,
                         energy=0.1 if failed else 0.9, lift=0.35 + 0.65 * p, dim=0.45 if failed else 1)
        else:
            self.sky.aim(horizon=0.46 if short else 0.5, radius=0.2, arc=1, grow=1.1, energy=0.6, lift=1, dim=1)

    def set_banner(self, text):
        self.banner.set_text(text)
        self.banner.set_visible(bool(text))

    # ── connect: who will listen ─────────────────────────────

    def connect_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.CENTER)
        self.hello_space = Gtk.Box()
        page.pack_start(self.hello_space, False, False, 0)
        self.hello = box("v", 14)
        self.hello.pack_start(label('Connect your <span font_style="italic" foreground="#ff6a3d">model</span>',
                                    "title", markup=True, xalign=0.5, wrap=False), False, False, 0)
        ways = box("h", 8, halign=Gtk.Align.CENTER)
        self.way_buttons = {}
        group = None
        for key, title, sub in WAYS:
            way = Gtk.RadioButton.new_from_widget(group)
            group = group or way
            way.set_mode(False)
            styled(way, "way")
            way.add(box("v", 2, label(title, "way-title", wrap=False), label(sub, "way-sub", wrap=False)))
            way.connect("toggled", self.way_toggled, key)
            ways.pack_start(way, True, True, 0)
            self.way_buttons[key] = way
        self.hello.pack_start(ways, False, False, 0)

        card = styled(box("v", 12), "card")
        card.set_halign(Gtk.Align.CENTER)
        card.set_size_request(520, -1)
        self.key_row = box("h", 6)
        self.key_buttons = {}
        group = None
        for kind, name in KEY_PROVIDERS:
            chip = Gtk.RadioButton.new_with_label_from_widget(group, name)
            group = group or chip
            chip.set_mode(False)
            styled(chip, "chip")
            chip.connect("toggled", self.key_toggled, kind)
            self.key_row.pack_start(chip, False, False, 0)
            self.key_buttons[kind] = chip
        card.pack_start(self.key_row, False, False, 0)
        self.endpoint = Gtk.Entry(placeholder_text="https://…/v1")
        self.endpoint_field = box("v", 7, caps("API base URL"), self.endpoint)
        card.pack_start(self.endpoint_field, False, False, 0)
        self.key = Gtk.Entry(placeholder_text="sk-…", visibility=False)
        self.key.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        self.key_link = styled(Gtk.LinkButton(uri="https://example.invalid", label="Get a key ↗"), "link")
        self.key_link.connect("activate-link", self.open_provider)
        key_head = box("h", 10)
        key_head.pack_start(caps("API key"), True, True, 0)
        key_head.pack_end(self.key_link, False, False, 0)
        self.key_field = box("v", 7, key_head, self.key)
        card.pack_start(self.key_field, False, False, 0)
        self.connect_error = label("", "err")
        card.pack_start(self.connect_error, False, False, 0)
        self.connected_line = label("", "okline", markup=True)
        card.pack_start(self.connected_line, False, False, 0)
        self.model_chips = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, min_children_per_line=2, max_children_per_line=6,
                                       column_spacing=6, row_spacing=6)
        self.model_entry = Gtk.Entry(placeholder_text="or enter a model ID")
        self.model_entry.connect("changed", lambda *_: self.begin_button.set_sensitive(self.provider is not None and bool(self.model_entry.get_text().strip())))
        self.model_entry.connect("activate", self.begin_chat)
        self.no_models = label("The server didn’t return a model list. Enter the model ID by hand — it’s in your provider’s docs.", "hint")
        self.model_field = box("v", 8, caps("Model"), self.model_chips, self.no_models, self.model_entry)
        card.pack_start(self.model_field, False, False, 0)
        row = box("h", 12)
        self.note = label("", "hint")
        self.note.set_valign(Gtk.Align.CENTER)
        self.note.set_max_width_chars(44)
        self.connect_error.set_max_width_chars(60)
        self.no_models.set_max_width_chars(60)
        row.pack_start(self.note, True, True, 0)
        self.connect_button = button("Connect  →", self.connect_provider, "primary")
        self.connect_button.set_sensitive(False)
        self.begin_button = button("Start  →", self.begin_chat, "primary")
        self.begin_button.set_sensitive(False)
        row.pack_end(self.begin_button, False, False, 0)
        row.pack_end(self.connect_button, False, False, 0)
        card.pack_start(row, False, False, 0)
        self.hello.pack_start(card, False, False, 0)
        page.pack_start(self.hello, False, False, 0)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.add(page)
        self.stack.add_named(scroller, "connect")
        for widget in (self.key_row, self.endpoint_field, self.key_field, self.connect_error, self.connected_line,
                       self.model_field, self.no_models, self.begin_button):
            widget.set_no_show_all(True)
        for child in (*self.key_row.get_children(), *self.key_buttons.values()):
            child.show_all()
        for field in (self.endpoint_field, self.key_field, self.model_field):
            for child in field.get_children():
                child.show_all()

    def way_toggled(self, widget, way):
        if not widget.get_active():
            return
        self.way = way
        self.key_row.set_visible(way == "key")
        if way == "key":
            kind = next((k for k, chip in self.key_buttons.items() if chip.get_active()), "openai")
        else:
            kind = "chatgpt" if way == "account" else "ollama"
        self.set_kind(kind)

    def key_toggled(self, widget, kind):
        if widget.get_active() and self.way == "key":
            self.set_kind(kind)

    def select_provider(self, kind):
        """Pick a provider the way a click would: its path, and its chip for API keys."""
        way = "account" if kind == "chatgpt" else "local" if kind == "ollama" else "key"
        if kind in self.key_buttons:
            self.key_buttons[kind].set_active(True)
        if self.way_buttons[way].get_active():
            self.set_kind(kind)
        else:
            self.way_buttons[way].set_active(True)

    def set_kind(self, kind):
        self.kind = kind
        self.provider_changed()

    def provider_changed(self):
        self.reset_provider()
        kind = self.kind
        info = PROVIDERS.get(kind, ("", "", ""))
        self.connected = False
        self.endpoint.set_text(info[1])
        self.endpoint_field.set_visible(kind in ("compatible", "ollama"))
        self.key.set_text("")
        self.key_field.set_visible(kind not in ("chatgpt", "ollama", "bridge"))
        self.key_link.set_visible(bool(info[2]))
        if info[2]:
            self.key_link.set_uri(info[2])
        clear(self.model_chips)
        self.model_entry.set_text("")
        self.model_field.set_visible(False)
        self.connected_line.set_visible(False)
        self.show_connect_error("")
        self.begin_button.set_visible(False)
        self.begin_button.set_sensitive(False)
        self.connect_button.set_visible(True)
        self.connect_button.set_sensitive(hasattr(self, "snapshot"))
        self.connect_button.set_label("Sign in to ChatGPT  →" if kind == "chatgpt" else "Connect  →")
        self.note.set_text(PROVIDER_NOTES.get(kind, API_NOTE))
        self.set_model_pill(None)
        self.aim_sky()

    def show_connect_error(self, text):
        self.connect_error.set_text(text)
        self.connect_error.set_visible(bool(text))
        for entry in (self.key, self.endpoint):
            (entry.get_style_context().add_class if text else entry.get_style_context().remove_class)("bad")

    def set_model_pill(self, model):
        self.model_label.set_text(model or "no model")
        (self.model_dot.get_style_context().remove_class if model else self.model_dot.get_style_context().add_class)("off")
        self.model_pill.set_sensitive(bool(model) and self.step == "chat" if hasattr(self, "step") else False)

    def reset_provider(self):
        with self.connection_lock:
            self.connection_generation += 1
            provider, self.provider = self.provider, None
            generation = self.connection_generation
        if provider:
            provider.close()
        return generation

    def open_provider(self, link):
        url = PROVIDERS.get(self.kind, ("", "", ""))[2]
        if url:
            webbrowser.open(url)
        return True

    def connect_provider(self, *_):
        generation = self.reset_provider()
        kind = self.kind
        endpoint, key = self.endpoint.get_text(), self.key.get_text()
        self.key.set_text("")
        self.connected = False
        self.show_connect_error("")
        self.connect_button.set_sensitive(False)
        self.connect_button.set_label("Waiting for sign-in…" if kind == "chatgpt" else "Checking…")
        self.begin_button.set_sensitive(False)
        self.set_status("Waiting for sign-in in the browser…" if kind == "chatgpt" else "Checking the connection…")
        self.aim_sky()

        def connect():
            if self.demo:
                return EnglishDemoProvider(), ["Interface demo"]
            if kind == "chatgpt":
                from chatgpt import ChatGPTProvider
                provider = ChatGPTProvider()
                with self.connection_lock:
                    current = generation == self.connection_generation
                    if current:
                        self.provider = provider
                if not current:
                    provider.close()
                    raise ProviderError("Подключение отменено")
                try:
                    return provider, provider.login(lambda url: open_browser_once(
                        url, lambda: generation == self.connection_generation))
                except Exception:
                    provider.close()
                    raise
            provider = BridgeProvider() if kind == "bridge" else APIProvider(kind, endpoint, key)
            try:
                return provider, provider.models()
            except Exception:
                provider.close()
                raise

        def done(result):
            provider, models = result
            if generation != self.connection_generation:
                provider.close()
                return
            self.provider = provider
            self.connected = True
            self.connect_button.set_visible(False)
            self.connect_button.set_label("Sign in to ChatGPT  →" if kind == "chatgpt" else "Connect  →")
            self.connected_line.set_markup(f'<span foreground="#5fe3a1">✓</span>  Connected · {GLib.markup_escape_text(PROVIDER_NAMES.get(kind, kind))}')
            self.connected_line.show()
            clear(self.model_chips)
            group = None
            for model in models:
                chip = Gtk.RadioButton.new_with_label_from_widget(group, model)
                group = group or chip
                chip.set_mode(False)
                styled(chip, "chip")
                chip.connect("toggled", lambda w, m=model: w.get_active() and self.model_entry.set_text(m))
                self.model_chips.add(chip)
            self.model_chips.set_visible(bool(models))
            self.no_models.set_visible(not models)
            self.model_field.show()
            self.model_chips.show_all()
            if models:
                self.model_entry.set_text(models[0])
            self.begin_button.show()
            self.begin_button.set_sensitive(bool(self.model_entry.get_text().strip()))
            self.note.set_text("The sun is listening. Shall we start?")
            self.set_status("Connected. " + ("Model selected — ready to start." if models else "Enter a model ID."))
            self.aim_sky()
            if models and kind == "bridge":
                self.set_banner("Test mode: LLM on the host, signed in through Codex.")
                self.begin_chat()

        def failed(text):
            if generation == self.connection_generation:
                self.connect_button.set_label("Sign in to ChatGPT  →" if kind == "chatgpt" else "Connect  →")
                self.show_connect_error(text)
                self.show_error(text)
        self.background(connect, done, failed)

    # ── conversation ─────────────────────────────────────────

    def chat_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.CENTER)
        self.talk = box("v", 10)
        self.talk.set_margin_top(84)
        self.scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.messages = box("v", 22)
        self.messages.set_margin_top(10)
        self.messages.set_margin_bottom(20)
        self.scroller.add(self.messages)
        self.talk.pack_start(self.scroller, True, True, 0)
        self.suggestions = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=6,
                                       column_spacing=6, row_spacing=6, homogeneous=False)
        self.talk.pack_start(self.suggestions, False, False, 0)
        self.review_button = button("All set — see the summary  ↑", self.review, "ready")
        self.review_button.set_halign(Gtk.Align.CENTER)
        self.review_button.set_no_show_all(True)
        self.review_button.set_sensitive(False)
        self.talk.pack_start(self.review_button, False, False, 0)
        self.ask = styled(box("h", 8), "ask")
        self.message = Gtk.Entry(placeholder_text="Describe your system in your own words…")
        self.message.connect("activate", self.send_message)
        self.message.connect("focus-in-event", lambda *_: self.ask.get_style_context().add_class("focused"))
        self.message.connect("focus-out-event", lambda *_: self.ask.get_style_context().remove_class("focused"))
        self.ask.pack_start(self.message, True, True, 0)
        self.send_button = button("↑", self.send_message, "primary", "send")
        self.send_button.set_tooltip_text("Send")
        self.ask.pack_start(self.send_button, False, False, 0)
        self.talk.pack_start(self.ask, False, False, 0)
        page.pack_start(self.talk, True, True, 0)
        self.talk_floor = Gtk.Box()
        page.pack_start(self.talk_floor, False, False, 0)
        self.stack.add_named(page, "chat")

    def begin_chat(self, *_):
        if not self.provider:
            return
        model = self.model_entry.get_text().strip()
        if not model:
            self.show_connect_error("Pick a model or enter its ID")
            return
        self.provider.model = model
        self.controller = Controller(self.snapshot, self.provider,
            lambda kind, value: soon(self.controller_event, kind, value),
            DemoCatalog() if self.demo else None)
        clear(self.messages)
        clear(self.suggestions)
        self.sky.set_labels([])
        self.review_button.hide()
        self.show_step("chat")
        self.set_model_pill(model)
        self.set_status("Connected: " + model)
        self.add_message("ai", FIRST_QUESTION)
        self.message.grab_focus()

    def controller_event(self, kind, value):
        if kind == "status":
            if value.startswith("Ищу пакеты: "):
                self.sky.set_labels([term.strip() for term in value.split(": ", 1)[1].split(",")])
                self.aim_sky()
            self.set_status(english(value))
            if self.busy:
                self.thinking_text.set_text(english(value))

    def add_message(self, who, text):
        if who == "ai":
            item = box("v", 6, caps("Installer", "who"), label(text, "ai-text"))
            item.get_children()[1].set_max_width_chars(60)
            item.get_children()[1].set_selectable(True)
        else:
            bubble = label(text, "me-text")
            bubble.set_max_width_chars(48)
            bubble.set_halign(Gtk.Align.END)
            item = box("v", 6, caps("You", "who", xalign=1.0), bubble)
            item.set_halign(Gtk.Align.END)
        self.messages.pack_start(item, False, False, 0)
        item.show_all()
        rise(item)
        self.scroll_down()
        return item

    def scroll_down(self):
        def scroll():
            adj = self.scroller.get_vadjustment()
            adj.set_value(adj.get_upper() - adj.get_page_size())
            return False
        GLib.timeout_add(80, scroll)

    def thinking(self):
        dots = box("h", 5, *(styled(Gtk.Box(valign=Gtk.Align.CENTER), "typing", extra) for extra in ("first", "second", "third")))
        self.thinking_text = label("The model is thinking…", "thinking", wrap=False)
        self.thinking_line = box("h", 12, dots, self.thinking_text)
        self.messages.pack_start(self.thinking_line, False, False, 0)
        self.thinking_line.show_all()
        rise(self.thinking_line)
        self.scroll_down()

    def send_message(self, *_):
        if self.busy or not self.controller:
            return
        text = self.message.get_text().strip()
        if not text:
            return
        self.busy = True
        self.last_text = text
        self.review_button.set_sensitive(False)
        self.review_button.hide()
        self.send_button.set_sensitive(False)
        self.message.set_text("")
        self.add_message("me", text)
        self.thinking()
        self.set_status("The model is thinking…")
        clear(self.suggestions)
        self.aim_sky()
        controller = self.controller

        def done(reply):
            if self.controller is not controller:
                return
            self.busy = False
            self.thinking_line.destroy()
            self.add_message("ai", reply["message"])
            for suggestion in reply["suggestions"]:
                chip = button(suggestion, lambda _, s=suggestion: self.choose_suggestion(s), "sug")
                self.suggestions.add(chip)
            self.suggestions.show_all()
            self.send_button.set_sensitive(True)
            ready = controller.configuration is not None
            self.review_button.set_sensitive(ready)
            self.review_button.set_visible(ready)
            if ready:
                rise(self.review_button)
                self.sky.set_labels(self.agreed_words(controller.configuration))
            self.set_status("Configuration ready for review" if ready else "Pick a suggestion or type your own answer")
            self.aim_sky()

        def failed(text):
            if self.controller is controller:
                self.thinking_line.destroy()
                error = label(text + "  Send it again or change the model.", "err")
                self.messages.pack_start(error, False, False, 0)
                error.show()
                rise(error)
                self.message.set_text(self.last_text)
                self.show_error(text)
        self.background(lambda: controller.respond(text), done, failed)

    def agreed_words(self, config):
        words = [config.session] if config.session else []
        words += [p for p in config.packages if not QUIET_PACKAGES.match(p) and p not in words]
        return words[:5]

    def choose_suggestion(self, text):
        self.message.set_text(text)
        self.send_message()

    def disconnect(self, *_):
        if self.busy:
            self.set_status("Wait for the current reply before changing the model")
            return
        if self.controller and self.controller.installing:
            return
        self.reset_provider()
        self.controller = None
        clear(self.messages)
        clear(self.suggestions)
        self.sky.set_labels([])
        self.show_step("connect")
        self.provider_changed()

    # ── confirm: a sheet over the conversation ───────────────

    def sheet(self):
        self.veil = styled(Gtk.EventBox(), "veil")
        self.veil.connect("button-press-event", self.close_review)
        self.overlay.add_overlay(self.veil)
        self.sheet_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_UP, transition_duration=480)
        self.sheet_revealer.set_valign(Gtk.Align.END)
        self.sheet_box = styled(box("v", 0), "sheet")
        grab = styled(Gtk.Box(halign=Gtk.Align.CENTER), "grab")
        grab.set_margin_top(10)
        head = box("h")
        head.pack_start(grab, True, False, 0)
        self.sheet_box.pack_start(head, False, False, 0)
        close = button("Back to the conversation  ✕", self.close_review, "ghost")
        close.set_halign(Gtk.Align.END)
        close.set_margin_end(16)
        self.sheet_box.pack_start(close, False, False, 0)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.sheet_grid = Gtk.Box(spacing=28, homogeneous=False)
        self.sheet_grid.set_margin_start(34)
        self.sheet_grid.set_margin_end(34)
        self.sheet_grid.set_margin_bottom(26)
        self.summary = box("v", 0)
        self.sheet_grid.pack_start(self.summary, True, True, 0)

        erase = styled(box("v", 14), "erase")
        erase.set_valign(Gtk.Align.START)
        erase.pack_start(caps("The whole disk will be erased", "accent"), False, False, 0)
        self.disk_title = label("", "big")
        self.disk_meta = label("", "mono")
        self.live_banner = label("Running outside the live system: chat works, disk writes are off.", "banner")
        self.live_banner.set_no_show_all(True)
        for widget in (self.disk_title, self.disk_meta, self.live_banner):
            erase.pack_start(widget, False, False, 0)
        self.password = Gtk.Entry(visibility=False, placeholder_text="8+ characters")
        self.repeat = Gtk.Entry(visibility=False, placeholder_text="once more")
        for entry in (self.password, self.repeat):
            entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
            entry.connect("changed", self.validate)
        self.password_caption = caps("Password for your user")
        erase.pack_start(box("v", 7, self.password_caption, self.password), False, False, 0)
        erase.pack_start(box("v", 7, caps("Repeat password"), self.repeat), False, False, 0)
        erase.pack_start(label("The password goes only to the local installer, never to the model.", "hint"), False, False, 0)
        self.need_length = label("○ Password of 8+ characters", "need", wrap=False)
        self.need_match = label("○ Passwords match", "need", wrap=False)
        erase.pack_start(box("h", 14, self.need_length, self.need_match), False, False, 0)
        self.hold = HoldButton(self.confirm_install)
        erase.pack_start(self.hold, False, False, 0)
        erase.pack_start(label("Mouse, finger, Space or Enter — hold for 1.5 seconds. Let go earlier and nothing happens.", "hint"), False, False, 0)
        erase.set_size_request(380, -1)
        self.sheet_grid.pack_start(erase, False, False, 0)
        scroller.add(self.sheet_grid)
        self.sheet_box.pack_start(scroller, True, True, 0)
        self.sheet_revealer.add(self.sheet_box)
        self.overlay.add_overlay(self.sheet_revealer)
        self.connect("key-press-event", lambda w, e: e.keyval == Gdk.KEY_Escape and self.sheet_revealer.get_reveal_child() and self.close_review())

    def review(self, *_):
        if self.busy or not self.controller or not self.controller.configuration:
            return
        config = self.controller.configuration
        disk = selected_disk(self.snapshot, config.disk)
        self.review_config, self.review_disk = config, disk
        clear(self.summary)
        self.summary.pack_start(caps("Summary"), False, False, 0)
        title = label(config.desktop, "sheet-title")
        title.set_margin_top(10)
        title.set_margin_bottom(18)
        self.summary.pack_start(title, False, False, 0)
        facts = [
            ("Layout", "Whole disk, GPT: boot partition and root; swap is zram in memory"),
            ("Filesystem & boot", f"{config.filesystem} · {config.bootloader}"),
            ("Session", config.session or "console"),
            ("Computer", f"{config.hostname} · user {config.username} (sudo with password)"),
            ("Language & time", f"{config.locale} · keyboard {', '.join(config.keyboard_layouts)} · {config.timezone}"),
            ("Packages", ", ".join(config.packages) or "base system only"),
            ("Services", ", ".join(config.services) or "base services only"),
            ("Requirements", "\n".join("· " + r for r in config.requirements)),
        ]
        for key, value in facts:
            row = styled(box("h", 12), "fact")
            name = caps(key, "fact-key")
            name.set_size_request(130, -1)
            name.set_valign(Gtk.Align.START)
            row.pack_start(name, False, False, 0)
            text = label(value, "fact-value")
            text.set_selectable(True)
            row.pack_start(text, True, True, 0)
            self.summary.pack_start(row, False, False, 0)
        files = [(f"~/{path}", content) for path, content in config.home_files] + \
                [(f"/{path}", content) for path, content in config.system_files]
        if files:
            expander = Gtk.Expander(label=f"Settings files ({len(files)})")
            expander.add(label("\n\n".join(f"{path}\n{content}" for path, content in files), "files"))
            expander.set_margin_top(10)
            self.summary.pack_start(expander, False, False, 0)
        self.summary.show_all()
        size = disk["size"] / 2**30
        self.disk_title.set_text(f"{english(disk.get('model') or 'Disk')} · {size:.1f} GiB")
        self.disk_meta.set_text(f"{config.disk} · serial {disk.get('serial') or 'not reported'}")
        self.hold.text.set_text("Hold to erase " + config.disk)
        self.password_caption.set_text(f"PASSWORD FOR {config.username.upper()}")
        self.live_banner.set_visible(not (self.demo or self.snapshot["live"]))
        self.password.set_text("demo-password" if self.demo else "")
        self.repeat.set_text("demo-password" if self.demo else "")
        self.validate()
        self.veil.show()
        self.sheet_revealer.set_reveal_child(True)
        self.set_phase(2)
        self.aim_sky()
        self.password.grab_focus_without_selecting()

    def close_review(self, *_):
        if not self.sheet_revealer.get_reveal_child():
            return False
        self.password.set_text("")
        self.repeat.set_text("")
        self.hold.reset()
        self.sheet_revealer.set_reveal_child(False)
        self.veil.hide()
        self.set_phase(1)
        self.aim_sky()
        self.message.grab_focus()
        return True

    def validate(self, *_):
        value = self.password.get_text()
        long_enough = 8 <= len(value) <= 256 and not any(c in value for c in "\r\n\x00")
        matches = long_enough and value == self.repeat.get_text()
        for need, ok, text in ((self.need_length, long_enough, "Password of 8+ characters"), (self.need_match, matches, "Passwords match")):
            need.set_text(("✓ " if ok else "○ ") + text)
            (need.get_style_context().add_class if ok else need.get_style_context().remove_class)("ok")
        self.hold.set_sensitive(matches and (self.demo or self.snapshot["live"]))

    def confirm_install(self):
        if not self.hold.get_sensitive() or not self.sheet_revealer.get_reveal_child():
            return False
        secret = self.password.get_text()
        self.password.set_text("")
        self.repeat.set_text("")
        self.sheet_revealer.set_reveal_child(False)
        self.veil.hide()
        self.start_install(self.review_config, self.review_disk, secret)
        return False

    # ── sunrise: installation ────────────────────────────────

    def install_page(self):
        page = box("v", 0)
        page.pack_start(Gtk.Box(), True, True, 0)
        rise_box = box("v", 10, halign=Gtk.Align.CENTER)
        self.install_caps = caps("Sunrise", xalign=0.5)
        self.pct = label("", "pct", wrap=False, xalign=0.5, markup=True)
        self.caption = label("", "cap", xalign=0.5)
        self.caption.set_justify(Gtk.Justification.CENTER)
        self.caption.set_max_width_chars(48)
        for widget in (self.install_caps, self.pct, self.caption):
            rise_box.pack_start(widget, False, False, 0)
        page.pack_start(rise_box, False, False, 0)
        self.rise_floor = Gtk.Box()
        page.pack_start(self.rise_floor, False, False, 0)
        self.below = box("v", 14, valign=Gtk.Align.START)
        self.below.set_margin_top(0)
        self.substeps = [caps(name, "substep") for name, _ in SUBSTEPS]
        steps = box("h", 18, *self.substeps, halign=Gtk.Align.CENTER)
        steps.set_margin_top(26)
        self.below.pack_start(steps, False, False, 0)
        self.cancel_button = button("Stop", self.cancel_install, "outline")
        row = box("h", 10, self.cancel_button, button("Log", self.toggle_log, "ghost"), halign=Gtk.Align.CENTER)
        self.below.pack_start(row, False, False, 0)
        page.pack_start(Gtk.Box(), False, False, 0)
        stack_page = Gtk.Overlay()
        stack_page.add(page)
        below_holder = box("v", 0, valign=Gtk.Align.END)
        below_holder.pack_start(self.below, False, False, 0)
        stack_page.add_overlay(below_holder)
        self.stack.add_named(stack_page, "install")
        self.install_state = "idle"
        self.sky.progress_listener = self.progress_frame

    def done_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.CENTER)
        self.done_space = Gtk.Box()
        page.pack_start(self.done_space, False, False, 0)
        self.done_box = box("v", 12)
        self.done_box.pack_start(caps("Done", xalign=0.5), False, False, 0)
        self.done_box.pack_start(label('Good <span font_style="italic" foreground="#ff6a3d">morning</span>', "done-title",
                                       markup=True, wrap=False, xalign=0.5), False, False, 0)
        self.done_text = label("", "cap", xalign=0.5)
        self.done_text.set_justify(Gtk.Justification.CENTER)
        self.done_box.pack_start(self.done_text, False, False, 0)
        self.shutdown_button = button("Shut down", self.shutdown, "primary")
        self.shutdown_button.set_sensitive(False)
        self.done_box.pack_start(box("h", 10, self.shutdown_button, button("Log", self.toggle_log, "ghost"), halign=Gtk.Align.CENTER),
                                 False, False, 6)
        page.pack_start(self.done_box, False, False, 0)
        self.stack.add_named(page, "done")

    def log_panel(self):
        self.log_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.CROSSFADE, transition_duration=250)
        self.log_revealer.set_valign(Gtk.Align.END)
        self.log_revealer.set_margin_start(26)
        self.log_revealer.set_margin_end(26)
        self.log_revealer.set_margin_bottom(46)
        self.progress_log = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_size_request(-1, 170)
        scroll.add(self.progress_log)
        self.log_scroll = scroll
        self.log_revealer.add(styled(box("v", 0, scroll), "logbox"))
        # A hidden revealer still takes clicks over its area, so it leaves the overlay while the log is closed.
        self.log_revealer.set_no_show_all(True)
        self.log_revealer.get_child().show_all()
        self.log_revealer.connect("notify::child-revealed",
                                  lambda r, _: r.get_reveal_child() or r.get_child_revealed() or r.hide())
        self.overlay.add_overlay(self.log_revealer)

    def toggle_log(self, *_):
        opening = not self.log_revealer.get_reveal_child()
        if opening:
            self.log_revealer.show()
        self.log_revealer.set_reveal_child(opening)

    def progress_frame(self, arc):
        if self.step == "install" and self.install_state == "running":
            self.pct.set_markup(f'<span font_features="tnum">{round(arc * 100)}</span><span size="40%" foreground="#8f887e">%</span>')

    def set_progress(self, value):
        self.progress = max(self.progress, min(1.0, value))
        for (name, start), widget, nxt in zip(SUBSTEPS, self.substeps, [*SUBSTEPS[1:], ("", 1.01)]):
            context = widget.get_style_context()
            context.remove_class("done")
            context.remove_class("current")
            if self.progress >= nxt[1] or self.install_state == "done":
                context.add_class("done")
                widget.set_text("✓ " + name.upper())
            else:
                widget.set_text(name.upper())
                if self.progress >= start:
                    context.add_class("current")
        self.aim_sky()

    def start_install(self, config, disk, password):
        self.controller.installing = True
        self.install_state = "running"
        self.installed_received = False
        self.progress = 0.0
        self.progress_log.get_buffer().set_text("")
        self.sky.set_labels([])
        self.sky.current.update(arc=0.0, grow=0.0, lift=0.35)
        self.cancel_button.set_sensitive(True)
        self.cancel_button.show()
        self.install_caps.set_text("SUNRISE")
        self.show_step("install")
        self.set_progress(0.0)
        self.set_status("Installing — keep the computer on")
        self.log_line("Checking repositories and packages before touching the disk…")
        self.caption.set_text("Checking repositories and packages before touching the disk…")
        if self.demo:
            password = ""

            def simulate():
                for fraction, text in ((0.08, "DEMO: creating partitions"), (0.16, "DEMO: installing the base system"),
                                       (0.42, "DEMO: installing your packages (4 of 12)"), (0.62, "DEMO: installing your packages (8 of 12)"),
                                       (0.8, "DEMO: installing your packages (12 of 12)"), (0.9, "DEMO: setting up the system")):
                    time.sleep(0.9)
                    soon(self.worker_event, {"kind": "progress", "fraction": fraction, "text": text})
                time.sleep(0.9)
                soon(self.worker_event, {"kind": "progress", "fraction": 1.0,
                                                  "text": "DEMO finished. No real system was installed."})
                return 0
            self.background(simulate, self.worker_done)
            return
        if not self.snapshot["live"]:
            self.worker_event({"kind": "error", "text": "Disks can be written only from the booted AGI OS live system"})
            return
        request = {"configuration": config.as_dict(), "fingerprint": disk["fingerprint"],
                   "consent_digest": config.digest(), "password": password}
        password = ""
        try:
            self.worker = subprocess.Popen(["sudo", "-n", "--", "/usr/bin/python", "-E", "-s", str(HERE / "worker.py")],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
            self.worker.stdin.write(json.dumps(request) + "\n")
            self.worker.stdin.flush()
        except OSError:
            self.worker_event({"kind": "error", "text": "Could not start the install engine"})
            return
        finally:
            request.pop("password", None)

        def read_worker():
            for line in self.worker.stdout:
                try:
                    soon(self.worker_event, json.loads(line))
                except ValueError:
                    continue
            return self.worker.wait()
        self.background(read_worker, self.worker_done)

    @staticmethod
    def fraction_of(event):
        """Share of the sunrise for a worker event: the engine reports stages and texts, not percentages."""
        if "fraction" in event:
            return event["fraction"]
        text = event.get("text", "")
        packages = re.search(r"\((\d+) из (\d+)\)", text)
        if event["kind"] == "installed":
            return 1.0
        if packages and text.startswith("Устанавливаю выбранные"):
            return 0.42 + 0.38 * int(packages[1]) / max(1, int(packages[2]))
        if text.startswith("Создаю"):
            return 0.08
        if text.startswith("Шифрую"):
            return 0.12
        if text.startswith("Устанавливаю базовую"):
            return 0.16
        return {4: 0.03, 6: 0.82, 7: 1.0}.get(event.get("stage"), 0.0)

    def log_line(self, text):
        buffer = self.progress_log.get_buffer()
        buffer.insert(buffer.get_end_iter(), text + "\n")
        adj = self.log_scroll.get_vadjustment()
        soon(lambda: adj.set_value(adj.get_upper()) and False)

    def worker_event(self, event):
        text = english(event.get("text", ""))
        self.log_line(text)
        if event["kind"] == "error":
            self.install_state = "error"
            self.controller.installing = False
            self.cancel_button.set_sensitive(False)
            self.install_caps.set_text("STOPPED")
            self.pct.set_markup(f'<span font_features="tnum">{round(self.progress * 100)}</span><span size="40%" foreground="#8f887e">%</span>')
            self.caption.set_markup(f'<span foreground="#ff8159">{GLib.markup_escape_text(text)}</span>')
            self.set_status("Installation did not finish. Check the disk before trying again.")
            self.aim_sky()
            return
        self.caption.set_text(text)
        if event["kind"] == "installed":
            self.installed_received = True
        self.set_progress(self.fraction_of(event))

    def worker_done(self, code):
        if not self.demo and not self.installed_received:
            code = 1
        self.controller.installing = False
        self.cancel_button.set_sensitive(False)
        self.sky.busy = False
        if code == 0 and self.install_state == "running":
            self.install_state = "done"
            self.set_progress(1.0)
            self.shutdown_button.set_sensitive(not self.demo and self.installed_received)
            self.done_text.set_text("Demo finished — nothing was installed." if self.demo else
                                    "Your system is on the disk. Shut down, remove the install media "
                                    "and power on again — the first-boot check opens after you sign in.")
            self.set_status("Demo finished" if self.demo else "Written to disk; first boot is waiting to be checked")
            GLib.timeout_add(900 if animations() else 0, lambda: self.show_step("done") or False)
        elif self.install_state == "running":
            self.install_state = "stopped"
            self.install_caps.set_text("STOPPED")
            self.caption.set_text("Installation stopped. Check the disk before trying again.")
            self.set_status("Installation stopped")
            self.aim_sky()
        if self.worker:
            self.worker.stdin.close()
            self.worker.stdout.close()

    def cancel_install(self, *_):
        if self.worker and self.worker.poll() is None:
            self.worker.stdin.write('{"cancel": true}\n')
            self.worker.stdin.flush()
            self.cancel_button.set_sensitive(False)
            self.set_status("Stopping the current step and unmounting partitions…")

    def shutdown(self, *_):
        if not self.demo and not (self.controller and self.controller.installing):
            subprocess.Popen(["systemctl", "poweroff"])

    # ── shared ───────────────────────────────────────────────

    def background(self, task, done, failed=None):
        def run():
            try:
                result = task()
            except Exception as exc:
                safe = english(str(exc)) if isinstance(exc, (ProviderError, ValidationError)) else \
                    "The operation didn’t finish. Check the connection and try again."
                soon(failed or self.show_error, safe)
            else:
                soon(done, result)
        threading.Thread(target=run, daemon=True).start()

    def inventory_ready(self, snapshot):
        self.snapshot = snapshot
        self.connect_button.set_sensitive(True)
        self.set_status("Ready to connect a model")
        if BRIDGE_PORT.exists() and not self.demo:
            self.kind = "bridge"
            self.provider_changed()
            self.connect_provider()
        if not snapshot["live"] and not self.demo:
            self.set_banner("Running outside the live system: chat works, disk writes are off.")

    def set_status(self, text):
        self.status.set_text(text)

    def show_error(self, text):
        self.busy = False
        self.set_status(text)
        self.send_button.set_sensitive(self.controller is not None)
        self.connect_button.set_sensitive(hasattr(self, "snapshot"))
        self.aim_sky()

    def on_close(self, *_):
        if self.controller and self.controller.installing:
            self.set_status("Stop the installation first and wait until the partitions are unmounted.")
            return True
        self.reset_provider()
        Gtk.main_quit()
        return False


def main():
    parser = argparse.ArgumentParser(description="AGI OS Installer")
    parser.add_argument("--demo", action="store_true", help="UI preview with fake data; no network or disk operations")
    parser.add_argument("--animations", action="store_true",
                        help="play animations even when the desktop turned GTK animations off")
    args = parser.parse_args()
    if args.animations:
        Gtk.Settings.get_default().props.gtk_enable_animations = True
    InstallerWindow(demo=args.demo)
    Gtk.main()


if __name__ == "__main__":
    main()
