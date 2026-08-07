---
name: header-include-cleanup
description: >
  Use when the user asks to clean up, trim, or reduce #include statements in a directory
  of headers - e.g. "clean up the includes in include/ocudu/adt", "reduce header bloat in
  lib/support", "remove unused includes from X", "use forward declarations to cut down
  includes in Y". Also applies to reducing compile-time/compile-memory cost via header
  hygiene. Not for a single ad-hoc file (just edit it directly) - this skill is for
  systematically sweeping every header under a directory.
version: 1.1.0
user-invocable: true
---

# Header Include Cleanup

Systematically remove unused `#include`s (and optionally replace them with forward
declarations, add back only what a recompile proves missing, or make transitive includes
explicit) across every header under a target directory, using `include-what-you-use`
(IWYU) + `fix_include`, validated by full-project rebuilds. This is slow, iterative, and requires judgment at nearly every step - budget for
that rather than expecting a fire-and-forget sweep.

## Why this is hard (read before starting)

IWYU only ever sees the usage inside ONE translation unit (TU). A removal that looks
perfectly safe from that one TU's viewpoint can:
- break a completely different file elsewhere in the codebase that relied on the header
  re-exporting a symbol transitively (the single most common failure mode encountered)
- break the SAME file, in a way IWYU's own suggestion didn't account for (elided default
  template arguments, `extern template` instantiation, a type alias that can never be
  forward-declared at all)
- be outright spurious - IWYU can misattribute a forward-declare need to a generic
  template header just because some OTHER file instantiates it with a concrete type
  elsewhere in the checked TU
- be outright spurious in a way the tooling's dead-declare check *can't* catch: a symbol
  name coincidentally matching a variable/parameter/member name rather than an actual type
  usage. `process_header.py`'s dead-forward-declare filter only checks whether the bare
  word appears anywhere else in the file's real code (comments/strings excluded) - it
  cannot tell type position from value position. Real incidents: `soa_table.h` got
  `enum class ColId;` added because `ColId` is used throughout as a *template parameter
  name* (`template <auto ColId>`), never as a type; `spmc_slot_ring.h` got an
  **anonymous-namespace** `struct payload;` added because `payload` is only ever a
  *member field name* (`T payload;`). Both compiled fine as dead code (redundant/unused
  declarations aren't errors) so a rebuild alone won't catch them - manually skim every
  forward-declare addition and confirm the symbol is actually used as a type (followed by
  `<`, `::`, `&`/`*`, or as a variable's declared type) before trusting it, at
  `forward-declare` level and above.
- be invisible to every check the tooling has, compile-verified or not, when the usage is
  inside a template member function body that is never instantiated by merely including
  the header. The recurring concrete shape: a `template <> struct fmt::formatter<T>`
  specialization whose `format()` passes a nested member (a `std::optional<U>`, a
  `std::variant`, a container) *directly* to another format call rather than
  dereferencing it first - that needs `fmt/std.h` (or a sibling `*_formatters.h`) for the
  nested type's own formatter, but `format()`'s body is a template and is not
  type-checked until something ELSE in the exact TU being checked actually calls
  `fmt::format` on `T`. Neither `targeted`'s associated-TU recompile nor its solo-header
  self-check (see below) can trigger that instantiation themselves, so both stay green
  right up until the full project rebuild finds the one file that does call it. Real
  incidents: `csi_report_formatters.h` and `pdcp_config.h`, both losing `fmt/std.h` to a
  `targeted`-level removal that looked completely unused from every check this tool runs.
  Treat removing `fmt/std.h`/`fmt/ranges.h`/a sibling `*_formatters.h` from a file
  containing an `fmt::formatter` specialization as high-risk - grep the `format()` bodies
  for a bare (non-`.value()`/non-dereferenced) member access before trusting the removal.

None of this is visible from IWYU's output alone. The only real safety net is a full
project rebuild (and ideally the full test suite) after every batch - see Phase 3. Treat
every "should remove"/"should add" line as a hypothesis to verify, not a fact.

### Why enums and template classes never get forward-declared

Unlike a plain (non-template) class/struct, forward-declaring an enum or a template
class/struct buys little while adding real fragility:
- An enum definition is cheap to include, so there's little to save. A plain `enum` with
  no explicit underlying type cannot be forward-declared at all, and one that does specify
  an underlying type must repeat it *exactly* - if the real declaration's underlying type
  ever changes, the forward-declare silently goes stale and breaks in a confusing way far
  from its cause.
- A template forward-declare must repeat every template parameter (after default-stripping,
  see "Why defaults must be stripped" above) *exactly* - a signature change upstream (a
  parameter added, reordered, or its default changed) silently breaks it the same way, and
  the mismatch usually surfaces as a confusing error far from the header that needs fixing.

The tooling therefore never leaves either shape behind, at `forward-declare` level or
above, in a header OR a `.cpp`: whenever a removal would otherwise need one, it resolves
the real header instead, trying (in order) IWYU's own full include-list for the symbol,
then a header this same run removed and that genuinely declares it (verified against its
real on-disk content, not guessed), then a project-wide search of the repo's own public
headers for the one unambiguous definition. Only falls back to leaving the forward-declare
in place if none of those three find anything - rare, and still safe (a forward-declare
that compiles beats none), just not the ideal outcome; see
`targeted_repair.remove_fragile_forward_declares`. A plain, non-template class/struct
forward-declare is unaffected - that's the intended, safe case `forward-declare` level
exists for.

IWYU's own full include-list just names *a* header in the TU's graph that touches the
symbol - not necessarily the one that defines it, since a header that merely *uses* the
symbol pervasively (while itself `#include`ing the real definition) matches equally well
from IWYU's point of view. Real incident: `search_space.h` needed `nr_band`, and this
resolved to `band_helper.h` - a large header that uses `nr_band` throughout its own body -
instead of the few-line `nr_band.h` that actually defines it, simply because
`band_helper.h` happened to be IWYU's answer. Before trusting IWYU's full-list candidate,
the tooling now verifies the candidate header's own on-disk content actually *defines* the
symbol (the same enum/class/alias/typedef check the project-wide search uses); if it
doesn't, resolution falls through to the next step instead. This is also why
`find_defining_removed_include`'s own "does this removed header declare it" check
recognizes `enum class X` and not just bare `enum X` - the earlier, narrower pattern
silently downgraded every enum-class definition to the same weak "bare word appears
somewhere" match a heavy, merely-*using* header gets, letting a tie go to whichever
candidate was found first rather than the one that actually defines the symbol.

IWYU also occasionally suggests a C standard-library header (`<stdint.h>`, `<math.h>`)
in a C++ TU where this codebase's own convention is the C++ wrapper form (`<cstdint>`,
`<cmath>`) - every added `#include` line is canonicalized against a small known-equivalents
table before being written, at every level and every resolution path.

## Input

- `<target_dir>` (required) - directory whose headers to clean up (e.g.
  `include/ocudu/adt`). This defines the WORK LIST (every `.h`/`.hpp` under it). Files
  *outside* this directory routinely still need edits as a side effect - fixing a distant
  consumer that relied on a trimmed header transitively, or an associated `.cpp` sitting
  elsewhere. That's expected, not a scope violation.
- `[level]` (optional, default `remove`) - how aggressive to be:
  - **`remove`** - only strip genuinely-unused `#include` lines. Never adds anything.
    Safest; a wrong removal just fails to compile loudly, caught by the rebuild.
  - **`forward-declare`** - additionally replace a removable `#include` with a forward
    declaration when the file only needs an incomplete type (by pointer/reference, or a
    by-value plain class/struct). Real reduction in transitive header cost, but more ways to
    get subtly wrong (see the failure modes above) - expect to hand-fix real cases the
    tooling can't get right on its own (elided-default usages, type aliases, extern
    template instantiations). **Never forward-declares an enum or a template class/struct**,
    at this level or above - see "Why enums and template classes never get forward-declared"
    below; any such forward-declare IWYU suggests is resolved back to the real header
    instead, in every file, .h or .cpp alike. A plain, non-template class/struct
    forward-declare is unaffected.
  - **`targeted`** - `forward-declare`, plus the minimum set of `#include` lines needed
    to repair what those edits actually broke - and nothing else. IWYU's raw output
    cannot distinguish "needed now that we removed its provider" from "pure
    self-sufficiency bloat, already resolvable through an untouched include", so this
    level does what no filter can: after applying the edits it **recompiles the same TU
    IWYU was run on**. Symbols that still resolve are left alone; for each symbol the
    compiler reports missing it adds the provider IWYU itself published for that symbol
    (upgrading a forward-declare to the real header when the diagnostic proves a
    declaration cannot satisfy the use - free function, value context, complete-type
    requirement, elided default template arguments), or, failing that, puts back the one
    include of its own that declared the symbol. It never invents a header. Up to 3
    recompile rounds, since the first missing symbol's error can mask the next.
    It also compiles the header **on its own** (a synthetic one-line TU that does
    nothing but `#include` it, same `-I`/`-D`/`-std` flags as the associated TU - see
    `targeted_repair.solo_compile_header`) - the associated TU's own recompile can stay
    green while the header itself has quietly stopped being self-sufficient, if that TU
    happens to reach the same symbol through some OTHER, untouched include (real
    incidents: `pcch_configuration.h` losing `std::optional`, `prach_format_type.h`
    losing `uint8_t`/`strcmp`/`std::underlying_type_t` - both passed their associated-TU
    check and only broke once the full project rebuild needed the header standing
    alone). If anything is left unresolved - an unknown symbol, or breakage in a file
    this run never touched - it **reverts the header and its paired `.cpp` to their
    pre-run content** and reports `skipped` naming what it could not resolve; it never
    leaves a file half-migrated. Expect diffs the size of `forward-declare`'s plus a
    handful of lines, versus `explicit`'s 10-50+ (real case: `bit_buffer.h` needs 2 of
    the 10 includes `explicit` would add). This is the right level for "reduce header
    bloat, but keep it compiling". One thing it cannot judge: whether the headers it
    adds back weigh less than the one that was removed - pair it with `measure_closure`
    to find out.
    **It does not replace Phase 3.** Both checks only prove the edited file
    self-consistent against a TU it happens to be compiled in. Neither can see a distant
    file that relied on the header re-exporting a symbol transitively - the single most
    common failure mode of this whole exercise (`ring_buffer.h` dropping `expected.h` /
    `noop_functor.h` broke 210 other files, and passes both checks without a murmur), nor
    a template body (an `fmt::formatter` specialization's own `format()`) that neither
    check ever instantiates - see "Why this is hard" above. The full-project rebuild is
    still mandatory.
  - **`explicit`** - additionally add plain `#include` lines for every symbol used
    directly but only reached transitively (IWYU's full self-sufficiency
    recommendation). Unlike `targeted` this is unconditional: every "should add"
    suggestion is applied whether or not anything actually needed it. This does **not**
    reduce compile time or memory - the headers are already pulled in transitively - it
    only trades a short include list for defensive self-sufficiency, often adding 10-50+
    lines per file. Only use when the user explicitly wants full IWYU compliance, not for
    a "reduce header bloat" ask. If a user believes otherwise, run it with
    `measure_closure` on and show them the `saved: 0` (see "Measuring the win").
- `[fallback_tu]` (optional) - a `.cpp` known to compile a broad swath of the codebase,
  used when a header has no `.cpp` of its own (see Phase 2). If omitted,
  `find_fallback_tu.py` tries to discover one per-header; ask the user for one if it can't.
- `[measure_closure]` (optional, default off) - report per-header how many preprocessed
  lines each edit actually saved. See "Measuring the win" below. Worth turning on whenever
  the goal is stated as reducing compile time or memory rather than tidying include lists.

If the user doesn't specify a level, ask - don't assume. If they don't specify a target
directory, ask for one; don't infer scope from context.

## Phase 0 - Prerequisites

Confirm the toolchain is available:
```bash
which include-what-you-use fix_include clang-format-18
```
If any are missing, stop and tell the user what to install (`include-what-you-use` and
`fix_include` typically ship together as the `iwyu` package; `clang-format-18` from LLVM).

Confirm a compile database exists at `<build_dir>/compile_commands.json` (generated by
`-DCMAKE_EXPORT_COMPILE_COMMANDS=On`). If not, stop and ask the user to configure/build
first.

Find `SKILL_DIR` (the directory containing this SKILL.md) for absolute script paths, and
set `WORK_DIR` to the session scratchpad directory (all intermediate lists, batches, dumps
and results below live there, never in the repo).

## Phase 1 - Discover the work list

```bash
bash "$SKILL_DIR/scripts/discover_headers.sh" <target_dir> > "$WORK_DIR/headers.txt"
wc -l "$WORK_DIR/headers.txt"
```

Split into module-sized batches (by subdirectory, or chunks of ~20-40 files) so each
validation cycle (Phase 3) stays a manageable size:
```bash
split -l 30 -d "$WORK_DIR/headers.txt" "$WORK_DIR/batch_"
```

Also generate the Ninja deps dump **once**, up front, for headers with no `.cpp` of their
own (see Phase 2):
```bash
python3 "$SKILL_DIR/scripts/dump_ninja_deps.py" <build_dir> "$WORK_DIR/ninja_deps_dump.txt"
```
Do this once per run, not per header - see Phase 2's warning. It exits non-zero if Ninja
couldn't produce a dump; don't proceed with a missing or empty one, every header would
silently degrade to the weaker grep-based TU search.

## Phase 2 - Process each batch

For each batch file, run it through `run_batch.sh` **in the foreground**, as a real
invocation of the script file, passing the deps dump generated in Phase 1:

```bash
bash "$SKILL_DIR/scripts/run_batch.sh" <repo_root> <build_dir> "$WORK_DIR/batch_00" \
  "$WORK_DIR/results_batch_00.jsonl" <level> "$WORK_DIR/ninja_deps_dump.txt" [measure_closure]
```

The 7th argument is optional; pass `1` to enable the per-header measurement described in
"Measuring the win" below.

Use **one results file per batch** (named after the batch, as above). A single shared
results file appends across batches, so the per-batch review below silently reports
cumulative counts and re-lists every header changed in earlier batches.

**Always pass the deps dump.** Without it, every header lacking its own `.cpp` makes
`find_fallback_tu.py` regenerate the entire project's `ninja -t deps` output itself - slow
enough to hit internal timeouts, which fall through to a worse (or no) fallback TU. If a
batch has an unexpectedly high skip count (`"not mentioned in iwyu output"` or `"no
fallback TU could be resolved"` on headers that should be reachable), suspect this first -
regenerate the dump and rerun before concluding those headers are unreachable.

**Never** construct the equivalent multi-line while-loop as an inline string and run it
through a backgrounded shell/eval call - that exact pattern was observed to hang silently
mid-session (the outer shell stayed alive with no child doing real work, nothing written to
the results file, no error surfaced). A foreground call to the actual script file gives an
immediate, unambiguous pass/fail. If a batch is large enough that you're tempted to
background it, split it into smaller batches instead.

After each batch, inspect that batch's results file:
```bash
python3 -c "
import json, sys
statuses, changed, skipped, saved_total = {}, [], [], 0
for line in open(sys.argv[1]):
    line = line.strip()
    if not line: continue
    d = json.loads(line)
    statuses[d['status']] = statuses.get(d['status'], 0) + 1
    if d['status'] in ('removed', 'added'):
        # actual_* reflects the file's real final content; removed_lines/added_lines
        # are only the raw pre-repair suggestion - fall back to them only when
        # actual_* is absent (dry-run, or a level with no later fixup to diverge).
        changed.append((d['header'], d.get('actual_removed_lines', d.get('removed_lines')),
                        d.get('actual_added_lines', d.get('added_lines')),
                        d.get('other_file_changes'), d.get('closure'), d.get('solo_header_findings')))
        saved_total += (d.get('closure') or {}).get('saved') or 0
    if d['status'] == 'skipped':
        skipped.append((d['header'], d.get('detail')))
print('counts:', statuses)
for h, rl, al, other, closure, solo in changed:
    print('CHANGED', h, 'removed:', rl, 'added:', al)
    if other: print('  ALSO EDITED', list(other))
    if solo: print('  SOLO-HEADER CHECK CAUGHT', solo)
    if closure and 'saved' in closure:
        print('  PREPROCESSED LINES', closure['saved'], 'saved of', closure['before'], 'in', closure['tu'])
    elif closure:
        print('  CLOSURE UNMEASURED', closure.get('detail'))
for h, detail in skipped: print('SKIPPED', h, detail)
print('preprocessed lines saved across batch:', saved_total)
" "$WORK_DIR/results_batch_00.jsonl"
```

`ALSO EDITED` marks headers processed in `associated_cpp` mode where the `.cpp` was edited
too - note them, they matter when reverting (Phase 3, step 5).

A `skipped` status with `"detail": "iwyu compile error"` is very often IWYU's own analysis
choking on a legitimate pattern (PIMPL, coroutine machinery) when checked from the wrong
vantage point - not a real bug. Don't force it; move on. A handful of skips per batch is
normal and fine.

Other skip details mean different things, and only the first is routine:
- `iwyu timeout after Ns` - a genuinely huge TU. Fine to leave.
- `no associated .cpp and no fallback TU could be resolved` - see the deps-dump note above.
- `hard timeout` or an exception detail (`TypeError: ...`) - a tooling problem, not a
  property of the header. Investigate before writing the header off; every header always
  gets exactly one result line, so a header missing from the results entirely means the
  batch itself died.
- `targeted: ...` (that level only) - the edits were applied, failed the recompile, could
  not be repaired from IWYU's own suggestions, and were **reverted**; the file on disk is
  untouched. The detail names what was left unresolved (a symbol with no known provider,
  or breakage in a file this run never edited). Worth reading: `validation failed outside
  the edited files` is an early warning that this header is relied on transitively, i.e.
  a Phase 3 decision-tree case found one batch sooner than usual.

At `targeted` level each header costs one IWYU run plus up to 3 recompiles (plus the
solo-header self-check, see the level description above), so batches take noticeably
longer; `run_batch.sh` widens its own hard timeout to match. Results carry extra fields:
`targeted_additions` (each with the reason it was added), `validation_rounds`, and
`solo_header_findings` (populated only when the solo self-check, not the associated-TU
recompile, is what caught something - worth noting when it fires, since that's a concrete
sign the check is pulling its weight and not just redundant with the associated-TU one).

**`removed_lines`/`added_lines` are the raw suggestion asked for, not a report of what
ended up on disk** - `remove_fragile_forward_declares`, `upgrade_cpp_forward_declares`,
and (at `targeted`) the repair loop can all still rewrite the file after that suggestion
was recorded (a removal can get fully restored while an unrelated forward-declare
resolves to a real header elsewhere in the same file, netting to an add with no net
remove at all, yet the stale fields would still say "removed"). Prefer
`actual_removed_lines`/`actual_added_lines` when present - computed from a real diff of
the file's pre-run backup against its final content, after every later fixup has had its
say - and treat `status` as accurate (it's recomputed from the same actual diff too).
The raw `removed_lines`/`added_lines` are still worth keeping around as a record of what
was originally asked for, useful mainly when it disagrees with the actual fields.

**Immediately after reviewing a batch's results, go straight to Phase 3 and rebuild -
before starting the next batch.** Do not process every batch first and rebuild once at
the end: `ninja`'s own incrementality means the total compile work is the same either
way, but debugging a rebuild scoped to one ~30-header batch (1-2 root causes) is far
faster than untangling one scoped to nine batches at once (5+ simultaneous, unrelated
root causes competing for attention in a single sprawling error log - this is exactly
what made the ran/ cleanup pass slower than it needed to be). Only after Phase 3 comes
back clean for this batch should the next one start.

## Measuring the win

With the 7th argument to `run_batch.sh` set, every changed header gets a `closure` field:

```json
"closure": {"tu": "/abs/path/to/checked_tu.cpp", "before": 812345, "after": 799012, "saved": 13333}
```

`before`/`after` are the line counts the preprocessor hands the parser for the same TU
IWYU was run on, measured with the project's own compiler (`-E -P`, spelled identically by
gcc and clang - no clang needed on a gcc build). Two preprocess-only runs per changed
header, skipped entirely for `no_change` headers.

Why this is the only number worth trusting: **an include's cost is set by the transitive
closure, not by the include list.** Two consequences that are easy to get backwards:
- Adding a direct `#include` for a header already reached transitively changes nothing -
  include guards mean it was parsed exactly once either way. This is why `explicit` cannot
  reduce compile time or memory no matter how many lines it adds, and the measurement will
  show `saved: 0` for it. Equally, *pruning* such a redundant include saves nothing either;
  it is a line-count change, not a cost change.
- Only removals and forward-declares shrink the closure - and a swap can come out **net
  negative**: dropping one heavy header and adding the several small ones its symbols came
  from is a win only if those bring less with them. IWYU has no notion of weight, so
  nothing else in this pipeline can catch that. A negative `saved` is exactly that case;
  consider reverting the header even though it compiles fine.

Interpret the number against which TU was measured:
- **Header with its own `.cpp`** - the delta is that TU's, the closest thing to the
  header's own weight.
- **Header with no `.cpp`** (`fallback_check_also` mode) - the measured TU is the fallback,
  which includes far more than this header. The delta is real for that TU but is not the
  header's weight in isolation; compare deltas across headers measured through the *same*
  fallback, not across different ones.
- **Unity mode** - the measured TU is the whole unity chunk, so the same dilution applies;
  `closure.tu` names the generated `unity_N_cxx.cxx` to make this visible.

A `closure` field carrying only `detail` means the measurement failed or timed out - it
never affects whether the header's edits were kept.

## Measuring the whole-project win (optional, expensive - for reporting back)

`measure_closure`'s preprocessed-line delta is real, but it is still a proxy: a line
count, not what the compiler actually spends memory and time on (template instantiation,
symbol tables, optimization passes all scale with more than line count). When the goal is
a concrete "compiling this got cheaper by X" number for the whole target directory - not
just per-header sanity checks along the way - run a full clean-build memory trace before
starting and again once every batch is done, then diff the two reports:

```bash
bash "$SKILL_DIR/scripts/run_mem_trace_build.sh" <path-to-repo-or-worktree>
```

This does a **full clean rebuild with clang, ccache disabled**, wrapping every compile
invocation in `/usr/bin/time` to record peak RSS, and writes a ranked report (worst
offenders first) plus a CSV and a metadata file under
`<repo>/build-mem-trace/reports/clang-mem-trace-<timestamp>/`. It reconfigures
`build-mem-trace` from scratch each run, so it never touches the repo's real build
directory or working tree.

**Hand this command to the user to run themselves, in their own terminal - do not try to
run it via a background Bash call.** A full clean rebuild with no ccache takes a genuinely
long time (this is a real constraint, not caution for its own sake), and the script's own
header says as much. Report progress by asking them to share the finished report's path,
not by attempting to babysit it yourself.

How to use it for a before/after comparison:
- **Before Phase 1**, on the pre-cleanup commit, run it once and note the report
  directory (or have the user do so) - this is the baseline.
- **After Phase 4** goes green, run it again on the cleaned-up state.
- Compare the two `mem-report.txt` files: the mean/median/max peak-RSS lines, and whether
  the specific translation units that were the worst offenders in the baseline actually
  dropped in the after report. A directory-wide sweep that doesn't move the worst
  offenders at all is a sign the wrong directory was picked for this goal, not that the
  edits inside it were wrong.
- This is a whole-project number, not a per-header one - it complements `measure_closure`
  (which can pinpoint which specific edit helped or hurt) rather than replacing it. Skip
  it entirely for a small or exploratory sweep; it earns its cost only when the user wants
  a real "before vs after" figure to report, not a running sanity check.

## Phase 3 - Validate immediately after EACH batch with a full rebuild

Run this right after every single batch from Phase 2, not once after the whole target
directory is done - see the note at the end of Phase 2 for why. This step is not
optional and not skippable, regardless of level or of how confident the per-file output
looks - `targeted`'s own checks are per-file, never project-wide:

```bash
ninja -C <build_dir> -j$(nproc)
```

Run it with the Bash tool's `run_in_background` (these are often foundational headers, so
the rebuild can touch hundreds of TUs and take minutes) - it notifies on exit, so don't
poll it.

**If it fails**, do NOT just revert the header that seems implicated. Work through this
decision tree:

1. **Read the actual compiler error** to find the real missing symbol/type, and which file
   is failing to compile - it is very often NOT the header you just changed, but some
   distant consumer of it.
2. **Is the failing file the one you edited, needing something in its OWN body** (e.g. an
   `extern template class Foo<ConcreteArgs>;` needing a concrete specialization, a
   `unique_function<Sig>` call site eliding default template args, a data member storing
   the type by value)? Then the edit was wrong for this file specifically - revert it (or
   the specific removal within it) and don't retry it at a higher level.
3. **Is the failing file a DIFFERENT file that relied on your header transitively
   re-exporting a symbol** (the most common case)? Then check the fanout before deciding
   how to respond:
   ```bash
   bash "$SKILL_DIR/scripts/check_fanout.sh" <repo_root> '<usage-grep-pattern>' '<direct-include-grep-pattern>'
   ```
   - **Narrow fanout (roughly 1-3 files)**: fix it properly - add the missing direct
     `#include` to each real consumer. This *completes* the IWYU cleanup as it should be
     done; it is not a workaround. Keep the original removal.
   - **Wide fanout (dozens, or growing with each rebuild cycle)**: this header is too
     pervasively relied-upon transitively at this codebase's scale for the small win of
     removing one include. Revert the original removal instead of chasing every consumer.
     (Seen directly: `task_executor.h` had 22+ hidden consumers, `async_task.h` had 11+ -
     both reverted rather than chased, after 2-3 direct fixes revealed the pattern wasn't
     narrowing.)
4. **A type alias** (`using X = Y;`) can **never** be forward-declared - if a removal
   depends on forward-declaring an alias, it's simply wrong; keep the real `#include`, or
   push the fix to the actual consumer if the alias-using file is the distant one.
5. **Is the error inside an `fmt::formatter<T>` specialization's own `format()` body**
   (a `type_is_unformattable_for<...>` error, or a missing member on a config/data
   struct that formatter formats)? This is template-body breakage - see "Why this is
   hard" above - and neither `targeted`'s associated-TU check nor its solo-header check
   can see it, since that body is never instantiated by including the header alone.
   Usually means a removed `fmt/std.h`/`fmt/ranges.h`/sibling `*_formatters.h` was
   actually needed for a nested member (a `std::optional<U>`, a `std::variant`, another
   custom type) the formatter passes to a further format call without dereferencing
   first. Add the real header back to whichever file defines the formatter, not
   wherever the rebuild happened to first instantiate it.
6. When you DO revert a header change, **also check for and revert any associated `.cpp`
   changes** - `process_header.py` in `associated_cpp` mode can modify both the header and
   its own `.cpp` in one pass, and reports the pair under `other_file_changes` /
   `touched_files` in the results. Reverting only the `.h` half of a broken pair leaves a
   dangling, unreverted `.cpp` mutation that will silently resurface as a "mystery" failure
   in a later batch. Always check with a repo-wide `git status`, not just the directory you
   think you touched:
   ```bash
   git status --short | grep -v '^??'
   ```
7. Rebuild again to confirm green before moving to the next batch.

## Phase 4 - Final validation

Once every batch is processed and the project rebuilds clean, run the full test suite:
```bash
ctest --test-dir <build_dir> -j$(nproc) --schedule-random --output-on-failure
```
Fix any failures the same way (root-cause via Phase 3's decision tree), rebuild+retest
until green.

## Reporting back

Never run `git commit` - leave all edits in the working tree for the user to review and
commit themselves, unless they explicitly ask you to commit. When reporting a completed
batch or the final result, keep it short: what changed, the rebuild/test verdict, and
anything skipped and why. Don't paste diffs into chat - the user can run `git diff`
themselves; a one-line "done, ready for review" is enough unless something surprising
happened.
