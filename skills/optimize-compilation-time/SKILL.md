---
name: optimize-compilation-time
description: >
  Make a C++ build cheaper, and prove it. Finds which headers and templates
  actually cost the build, bounds the achievable win before any work starts,
  and measures honestly enough to catch the common case where a plausible
  refactor is neutral or a regression. Use this skill whenever the user wants
  to speed up compilation, asks "why is this file so slow to compile", "what
  does this header cost us", "how do we cut build time", mentions compile time,
  build time, compile memory, template bloat, header bloat, transitive
  includes, include-what-you-use, extern template, precompiled headers,
  -ftime-report or -ftime-trace, or proposes a refactor whose stated goal is
  fewer template instantiations or a lighter include graph -- even when they
  never say "profile" or "measure" out loud. Also use it to audit a
  compile-time claim that has already been made, especially a single
  before/after number, and to decide whether a proposed cleanup is worth its
  fallout. For executing an include sweep once a target is chosen, this skill
  hands off to the header-include-cleanup skill.
version: 1.0.0
user-invocable: true
---

# Optimizing compilation time

Two things go wrong here, independently, and both fail quietly in the
flattering direction: the **measurement** is noise, or the **model of where the
cost comes from** is wrong. Treat every claimed win as a hypothesis until it
survives Phase 3 and 4.

## The idea that governs all of it: cost is per translation unit

The compiler is invoked once per TU and charges per TU. Repo-wide counts of
anything -- includes, template instantiations, call sites -- do not predict what
any single compile pays. Two consequences that account for most wasted effort:

- **Template side.** 112 distinct `Foo<...>` argument combinations tree-wide can
  be 1-3 per TU. Member functions of a class template instantiate lazily, so the
  ones a TU never calls were never a cost.
- **Include side.** A header's cost is its **transitive closure**, not its
  include list, and the include guard means each header is parsed once per TU no
  matter how many paths reach it.

`header-include-cleanup` states the same thing from IWYU's viewpoint -- "IWYU
only ever sees the usage inside ONE translation unit". Same phenomenon, two
directions.

## Phase 1 -- find what is actually expensive

- **Rank, do not guess.** `header-include-cleanup/scripts/gen_dependency_tree.py`
  then `header_line_cost.py` give `cost(header) = lines × TUs whose closure
  contains it`. The product is the point: a 12-line header in 4000 TUs and a
  4000-line header in 12 TUs cost the same, and only one looks wrong by eye.
- **This is a static estimate in physical lines, for choosing targets only.**
  Lines are not uniformly expensive and it cannot see the preprocessor. It never
  settles whether an edit helped.
- **Get fanout from the build graph, not grep.** `ninja -C <build> -t deps` is
  the real closure per object; grepping `#include` misses transitive arrivals.
  Dump it **once** and reuse it -- regenerating per-header is slow enough to look
  like failure -- and check it is non-empty, because a silent partial dump reads
  as "nothing depends on this" rather than "the dump broke".
- **Measure the per-TU multiplier for template work**: distinct template-argument
  spellings reachable from the TUs you care about, never a repo-wide grep.

## Phase 2 -- bound the win before doing the work

- `scripts/header_cost.sh <hdr>...` times `#include <hdr>` against an empty TU.
  Reference (GCC 15, `-O2`): `<complex>` 0.28s (it drags in `<sstream>`),
  `<sstream>` 0.19s, `<functional>` 0.13s, `<vector>` 0.07s.
- `ceiling ≈ per-TU cost × affected TUs / parallelism`. Compare against total
  build time.
- **Then apply the stop rule.** If the ceiling is a few percent and the change
  needs an include-what-you-use sweep across hundreds of files, say so and stop.
  A quantified "not worth it" is a result, not a failure.

## Phase 3 -- build a harness that is not lying

- **Bypass ccache.** `compile_commands.json` entries start with
  `/usr/bin/ccache`; drop `argv[0]`. A hit is ~0.01s, so otherwise you time the
  cache.
- **Strip `-o`, `-MD`, `-MT`, `-MF`** and send `-o` to scratch, or you clobber
  the build tree's objects and dependency files.
- **Quiet the machine.** A background `ctest` stretched one TU 8.8s -> 11.8s,
  larger than anything being measured.
- **`-ftime-trace` is clang-only.** GCC has `-ftime-report`.
- **Hand full clean rebuilds to the user to run in their own terminal.** They
  take a genuinely long time, and babysitting one through a background call
  wastes the session and misreports exit codes.

## Phase 4 -- choose a metric that survives noise

- **Per-TU wall clock drifts ±25%** across a session. A single A-then-B pair
  proves nothing; expect a TU to get slower while its instantiation time drops.
- **`-ftime-report` phase times are steadier and attribute the cost.**
  `template instantiation` and `parser (global)` are the two that move.
- **Interleave the variants** -- alternate A and B *within* each round, median
  over 5+. Sequential A-then-B measures drift. `scripts/ab_compile.py` does this.
- **Establish the noise floor with a null A/B** (two identical variants) before
  believing any delta. On a normal desktop that already reads +5% wall and +3%
  instantiation.
- **Add noise-free structural counters** to confirm the change happened at all:
  `-E -P | wc -l` for preprocessed lines on the *same* TU before and after, and
  `-H` for unique headers.
- **Peak RSS is a second axis, often the binding one** (parallel compiles OOM
  long before they get slow) and much less noisy than time.
  `header-include-cleanup/scripts/run_mem_trace_build.sh` does a clean
  ccache-disabled rebuild wrapping each compile in `/usr/bin/time` and ranks
  worst-first. If a sweep does not move the baseline's worst offenders, the wrong
  target was picked -- go back to Phase 1.

## Phase 5 -- template instantiation traps

- **A forwarder layer adds instantiations rather than sharing them.** Moving a
  body into a shared base and calling it through a thin wrapper instantiates two
  functions where there was one: a loss at multiplier 1, a win only once the
  multiplier is large. Measured: -20% instantiation time at multiplier 36, +10%
  at multiplier 1.
- **Header-inline bodies buy front-end time only.** Codegen still duplicates per
  call site wherever the inliner chooses to, so object size is unchanged.
- **`std::is_convertible_v<F, std::function<Sig>>` in a `static_assert` is
  expensive** -- it instantiates a `std::function` conversion just to test a
  signature. `std::is_invocable_v<F&, Args...>` is cheaper and also accepts
  move-only callables.

`references/case-study.md` is a worked example of a refactor that looked like a
112x win, measured -21% in two files and +10% everywhere else, and was reverted.

## Phase 6 -- include-graph traps

- **Removing an include helps only if that header was the sole path to it.**
  Heavy standard headers usually arrive by two or three routes; removing one
  changes neither the closure nor the time. Verify with `-H` on a TU you expect
  to benefit.
- **Pruning a redundant include saves nothing** -- it was already parsed once via
  another path. It is a line-count change, not a cost change. By the same logic,
  making transitive includes explicit cannot reduce compile time by construction.
- **A swap can be net negative.** Dropping one heavy header and adding the
  several small ones its symbols came from wins only if they bring less with
  them. IWYU has no notion of weight, so no tool catches this.
- **Budget for the fallout, then decide with numbers.** Dropping a transitively
  supplied include breaks every file that was free-riding. Enumerate the whole
  tail in one pass with `ninja -k 0` and classify by the **first** error per file
  -- the rest are cascades. Then count how many other files rely on that same
  transitive path (`header-include-cleanup/scripts/check_fanout.sh`): single
  digits means fix them properly, low tens or more means revert the removal
  instead. Real cases: `task_executor.h` 22+ hidden consumers and `async_task.h`
  11+, both reverted rather than chased.

## Phase 7 -- act

Once Phase 1 has a target and Phase 2 says the win is worth having, the actual
include sweep is a separate, slow, judgment-heavy workflow: invoke the
**header-include-cleanup** skill, which owns IWYU mechanics, forward-declare
fragility, batching and per-batch rebuild validation. Come back here to measure
the result.

## Reporting

- Give the median, name the metric, and say plainly when wall clock was
  noise-dominated instead of dressing it up as signal.
- State the per-TU multiplier or closure delta you measured -- that is what lets
  a reader judge whether the conclusion generalizes past the files you sampled.
- Report a negative result as the answer. It is cheaper than shipping a refactor
  that costs time, and it is the outcome this skill exists to catch.
