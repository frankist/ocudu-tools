#!/usr/bin/env python3
"""Filter raw include-what-you-use output before feeding it to fix_include,
according to a cleanup --level. Reads IWYU output on stdin, writes filtered
IWYU-format output on stdout.

Levels (each includes the previous one's behavior):

  remove (default)
    Only ever REMOVE #include lines. Never add anything (no new #include,
    no forward-declare). Safest option - a removal that turns out to be
    wrong just makes that one file fail to compile loudly (caught by the
    mandatory rebuild), rather than silently breaking something elsewhere.
    Never removes an existing forward-declaration/template-declaration
    line, even if IWYU says to - see "Why forward-declare removals are
    unsafe" below.

  forward-declare
    Additionally ADD forward-declarations (never new #include lines) when
    doing so lets a removal go through. Template forward-declares have
    their default arguments stripped (see "Why defaults must be stripped"
    below). A forward-declare addition whose symbol never appears in the
    target file's own body is dropped as a misattributed/spurious
    suggestion (see "Why dead forward-declares happen" below).

    An enum or template class/struct forward-declare added here is not the
    final answer: this script still emits one (same as any other
    forward-declare candidate), but process_header.py's
    remove_fragile_forward_declares() runs right after fix_include applies
    these edits and resolves it back to the real header in every file, .h or
    .cpp alike - see that function's docstring in targeted_repair.py for why
    neither is ever left forward-declared. A plain, non-template class/struct
    forward-declare is unaffected.

  targeted
    Same filtering as forward-declare for a HEADER target - this script
    cannot tell which additions are genuinely needed, only a compiler can,
    and the extra work happens after fix_include: process_header.py
    recompiles the file and adds back only the providers of symbols that
    actually broke (see targeted_repair.py). For a .cpp target, though,
    ADDS NOTHING here at all - unlike forward-declare level, which still
    unconditionally trusts IWYU's suggestion for a .cpp (see "Why a .cpp
    target never gets a bare forward-declare"). A .cpp has no
    forward-declare fallback to reach for, so applying forward-declare's
    "just trust IWYU" behavior there would defeat targeted's whole
    distinction between genuine breakage and self-sufficiency bloat for
    every .cpp target. Every addition for a .cpp is instead left entirely
    to targeted_repair.py's compile-verified loop.

  explicit
    Additionally ADD plain #include lines from IWYU's "should add"
    section - i.e. apply IWYU's full self-sufficiency recommendation, not
    just what's needed to pair with a removal. This makes every header
    directly include everything it uses, even symbols already reachable
    transitively. It does NOT reduce compile time or memory (the headers
    are already pulled in transitively) - it only trades a shorter
    include list for defensive self-sufficiency. Expect large diffs (each
    file can gain 10-50+ new lines). Use only when the user explicitly
    wants full IWYU compliance over a lean include list. Forward-declare
    additions still go through the same filtering as at the
    forward-declare level - a more aggressive level must never be a less
    safe one.

Why forward-declare removals are unsafe
----------------------------------------
IWYU only sees ONE translation unit's usage. An existing (possibly
primary, never-defined) template forward-declared in header H can be
required by *other* headers/TUs that provide partial specializations of
it, or otherwise rely on it being visible transitively through H - even
though the one TU used to check H doesn't exercise it itself. Real
incident: removing detail/concurrent_queue_params.h's `concurrent_queue`
primary-template forward-declare (flagged "unused" from one TU's view)
broke six unrelated queue headers that specialize it project-wide.
Removing #includes is the real "redundant header" cleanup; removing a
forward-declare line saves nothing (it's free to keep) and risks breaking
consumers this single-TU view can't see.

Why defaults must be stripped from added template forward-declares
--------------------------------------------------------------------
IWYU can print a forward-declare for a template WITH its default
template arguments even when a real primary declaration with those same
defaults already exists elsewhere. Real incident: IWYU added
`template <class Signature, size_t Capacity = N, bool ForbidAlloc =
false> class unique_function;` into a header that ends up in the same TU
as unique_function.h's real declaration, which already provides that
same default. C++ forbids redefining a default template argument even
with an identical value - this silently breaks any TU where both
declarations end up visible. A forward-declare with the defaults
stripped can never collide with a real declaration's defaults, so it's
always safe to add regardless of what else is visible in the TU. The
flip side: if the FILE ITSELF uses the type with elided/default-reliant
arguments (e.g. `unique_function<Sig>` with only 1 of 3 args), a
defaults-stripped forward-declare is not enough - that file needs the
real #include kept. This script can't detect that case; the skill's
per-file review step (checking the rebuild) is what catches it.

Why dead forward-declares happen
----------------------------------
A generic template header (e.g. `type_storage<T, MinSize, AlignSize>`)
can get a forward-declare suggestion for some concrete type C purely
because ANOTHER file in the checked TU instantiates
`type_storage<C, ...>` - IWYU's analysis misattributes the need for C's
declaration back to type_storage.h itself, even though type_storage.h's
own body never names C. Such a forward-declare is dead weight: it's
never referenced anywhere in the file. Dropping those is process_header.py's
job (it has the target file's on-disk content to check against), applied
to this script's output - see its drop_dead_forward_declares().

Why a .cpp target never gets a bare forward-declare
------------------------------------------------------
A forward-declare's whole payoff is amortized: keep a heavy header out of
every OTHER file that includes this one, so its parse/template cost isn't
paid repeatedly. A .cpp is nobody's dependency - it compiles into exactly
one translation unit, once. There is no downstream consumer to protect, so
forward-declaring there buys nothing while adding the same fragility a
header risks (elided default template arguments, complete-type needs a
rebuild would have to discover). At `forward-declare` level, a .cpp target
therefore always prefers the real #include IWYU's own "full include-list"
names for the symbol over a bare forward-declare, where a header target
would get the lighter form. At `targeted` level a .cpp gets neither form
from this script at all - see the `targeted` level description above.
"""
import argparse
import re
import sys

ADD_HEADER_SUFFIX = " should add these lines:"
REMOVE_HEADER_SUFFIX = " should remove these lines:"
TOTAL_HEADER_RE = re.compile(r"^The full include-list for (.*):$")
_INCLUDE_RE = re.compile(r'\s*#\s*include\s+([<"][^">]+[>"])')
_REMOVE_LINE_RE = re.compile(r"^-\s*(.*)$")
_TEMPLATE_KEYWORD_RE = re.compile(r"template\s*<")
_FOR_COMMENT_RE = re.compile(r"//\s*for\s+(.*)$")
_TRAILING_COMMENT_RE = re.compile(r"\s*//.*$")
_FWD_DECL_SYMBOL_RE = re.compile(r"\b(?:class|struct|union)\s+([A-Za-z_][\w:]*)\s*[;{]")
_FWD_DECL_ENUM_RE = re.compile(r"\benum(?:\s+(?:class|struct))?\s+([A-Za-z_][\w:]*)\s*[:;]")
# A forward-declare of the shape `class Outer::Inner;` - IWYU sometimes suggests this for a
# nested member type, but it's invalid C++: you cannot forward-declare a nested class without
# its enclosing class already being defined. Always drop these, regardless of namespace
# wrapping - the underlying #include must be kept instead.
_NESTED_CLASS_FWD_DECL_RE = re.compile(r"\b(?:class|struct)\s+[A-Za-z_]\w*::[\w:]*\s*;")
_CPP_SUFFIXES = (".cpp", ".cc")

# IWYU sometimes suggests a C standard-library header even in a C++ TU (e.g.
# <stdint.h> for uint8_t, <math.h> for M_PI) where this codebase's own
# convention is the C++ wrapper form - verified by grep: <cstdint> outnumbers
# <stdint.h> 66:2 project-wide, and both <stdint.h> hits trace back to a
# prior run of this same tool. Canonicalize the common ones on the way out
# rather than leave a style drive-by for the user to catch by hand.
_C_HEADER_TO_CXX = {
    "<stdint.h>": "<cstdint>",
    "<stddef.h>": "<cstddef>",
    "<string.h>": "<cstring>",
    "<stdio.h>": "<cstdio>",
    "<stdlib.h>": "<cstdlib>",
    "<math.h>": "<cmath>",
    "<assert.h>": "<cassert>",
    "<ctype.h>": "<cctype>",
    "<time.h>": "<ctime>",
    "<limits.h>": "<climits>",
    "<float.h>": "<cfloat>",
    "<errno.h>": "<cerrno>",
    "<signal.h>": "<csignal>",
    "<wchar.h>": "<cwchar>",
}


def canonicalize_c_header_include(line):
    """Rewrite a known C header #include to its C++ wrapper form
    (<stdint.h> -> <cstdint>), leaving anything else - including the line's
    own leading whitespace and any trailing comment - untouched."""
    m = _INCLUDE_RE.search(line)
    if not m:
        return line
    replacement = _C_HEADER_TO_CXX.get(m.group(1))
    if not replacement:
        return line
    return line[:m.start(1)] + replacement + line[m.end(1):]


def _forward_declare_symbol(line):
    for regex in (_FWD_DECL_SYMBOL_RE, _FWD_DECL_ENUM_RE):
        m = regex.search(line)
        if m:
            return m.group(1).rsplit("::", 1)[-1]
    return None


def build_full_list_symbol_to_include(text):
    """{file: {symbol: include_statement}} from every "full include-list"
    section's #include lines, keyed by the same trailing `// for a, b`
    annotation targeted_repair.py's symbol tables use. This is how a .cpp
    target's forward-declare candidate gets upgraded to the real header."""
    result = {}
    current_file = None
    in_full = False
    for raw in text.split("\n"):
        line = raw.rstrip()
        m_tot = TOTAL_HEADER_RE.match(line)
        if m_tot:
            current_file = m_tot.group(1)
            in_full = True
            result.setdefault(current_file, {})
            continue
        if line.strip() == "---":
            in_full = False
            continue
        if in_full and current_file and _INCLUDE_RE.match(line):
            m = _FOR_COMMENT_RE.search(line)
            if not m:
                continue
            stmt = _TRAILING_COMMENT_RE.sub("", line).strip()
            for part in m.group(1).split(","):
                name = part.strip().split(" ")[0].strip().rstrip(".")
                if name:
                    result[current_file].setdefault(name, stmt)
    return result


def strip_template_defaults(params_text):
    """Split a template parameter list on top-level commas (respecting
    nested <...>/(...) so defaults like std::vector<T> don't get split
    early) and drop any top-level '= default' clause from each parameter."""
    parts = []
    depth = 0
    current = []
    for ch in params_text:
        if ch in "<(":
            depth += 1
        elif ch in ">)":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))

    cleaned = []
    for part in parts:
        depth = 0
        eq_index = None
        for i, ch in enumerate(part):
            if ch in "<(":
                depth += 1
            elif ch in ">)":
                depth -= 1
            elif ch == "=" and depth == 0:
                eq_index = i
                break
        cleaned.append((part[:eq_index] if eq_index is not None else part).strip())
    return ", ".join(cleaned)


def strip_template_defaults_in_line(line):
    """Find every 'template <...>' span anywhere in the line (IWYU may
    wrap it as `namespace X { template <...> class Y; }`) and strip
    default template arguments from each, leaving the rest of the line -
    including any namespace wrapper - untouched."""
    out = []
    pos = 0
    while True:
        m = _TEMPLATE_KEYWORD_RE.search(line, pos)
        if not m:
            out.append(line[pos:])
            break
        out.append(line[pos:m.end()])
        start = m.end()
        depth = 1
        i = start
        while i < len(line) and depth > 0:
            if line[i] == "<":
                depth += 1
            elif line[i] == ">":
                depth -= 1
            i += 1
        params_end = i - 1
        if depth != 0:
            out.append(line[start:])
            pos = len(line)
            break
        out.append(strip_template_defaults(line[start:params_end]))
        pos = params_end
    return "".join(out)


def filter_output(text, level):
    full_list_map = build_full_list_symbol_to_include(text)
    lines = text.split("\n")
    out = []
    section = None  # None | "add" | "remove"
    current_file = None
    for line in lines:
        stripped = line.rstrip()
        if stripped.endswith(ADD_HEADER_SUFFIX):
            section = "add"
            current_file = stripped[:-len(ADD_HEADER_SUFFIX)]
            out.append(line)
            continue
        if stripped.endswith(REMOVE_HEADER_SUFFIX):
            section = "remove"
            current_file = stripped[:-len(REMOVE_HEADER_SUFFIX)]
            out.append(line)
            continue
        if TOTAL_HEADER_RE.match(stripped):
            section = None
            out.append(line)
            continue

        if section == "add":
            is_cpp = bool(current_file) and current_file.endswith(_CPP_SUFFIXES)
            # targeted's whole point is that only a compiler can tell genuine
            # breakage apart from self-sufficiency bloat - so for a .cpp target
            # (where forward-declaring isn't an option to fall back on, see
            # "Why a .cpp target never gets a bare forward-declare") it must
            # add NOTHING here, deferring every addition to targeted_repair.py's
            # compile-verified loop. Applying the forward-declare level's
            # unconditional "just trust IWYU" behavior here - as if targeted were
            # forward-declare with extra steps - would silently defeat that
            # whole distinction for every .cpp target.
            if level == "targeted" and is_cpp:
                continue
            if _INCLUDE_RE.match(line):
                # New #include lines are the explicit level's whole point, and out of
                # scope at every level below it - except a .cpp target, which always
                # gets them: see "Why a .cpp target never gets a bare forward-declare".
                if level == "explicit" or is_cpp:
                    out.append(canonicalize_c_header_include(line))
                continue
            if level == "remove":
                continue  # remove-only level adds nothing, forward-declares included
            if _NESTED_CLASS_FWD_DECL_RE.search(line):
                continue  # invalid C++ as a bare forward-declare - keep the real #include instead
            if is_cpp:
                symbol = _forward_declare_symbol(line)
                real_include = full_list_map.get(current_file, {}).get(symbol) if symbol else None
                if real_include:
                    out.append(canonicalize_c_header_include(real_include))
                    continue
                # IWYU's full include-list didn't name a header for this symbol either -
                # fall through to the forward-declare rather than silently drop it; a
                # forward-declare that still compiles beats no declaration at all.
            out.append(strip_template_defaults_in_line(line))
            continue

        if section == "remove":
            m = _REMOVE_LINE_RE.match(stripped)
            if m and not _INCLUDE_RE.match(m.group(1)):
                continue  # never remove an existing forward-declare/template-declare
            out.append(line)
            continue

        out.append(line)
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", choices=["remove", "forward-declare", "targeted", "explicit"], default="remove")
    args = ap.parse_args()
    text = sys.stdin.read()
    sys.stdout.write(filter_output(text, args.level))


if __name__ == "__main__":
    main()
