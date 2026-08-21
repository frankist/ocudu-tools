# Case study: a template refactor that measured as a loss

Worked example from `ocudu`'s `bounded_bitset`. Useful because the plan was
plausible, the reasoning was specific, and it was still wrong -- and the
measurement is what caught it.

## The proposal

`bounded_bitset<N, LowestInfoBitIsMSB, Tag>` carried every bit-manipulation body
as a member. Nothing in those bodies depended on `N`: it appeared only in
`max_size()`, in the `std::array<word_type, ...>` member, and in one
`static_vector<size_t, N>` return type. A repo-wide grep found **112 distinct
`bounded_bitset<...>` argument combinations**, times 2 for the bit order.

So: move the heavy bodies down into a base templated only on the bit order,
have them take `span<word_type>` plus a bit count, and leave one-line forwarders
behind. 112 instantiations collapse to 2. `bounded_bitset.h` was in the include
closure of **1201 of 1911** object files, so the payoff looked large.

## What the measurement said

Interleaved A/B, median of 5 rounds, `-ftime-report` `template instantiation`:

| TU | distinct `N` in TU | before | after |
|---|---|---|---|
| `bounded_bitset_test.cpp` | 36 | 1.25s | 0.99s (**-21%**) |
| `fixed_bitset_test.cpp` | 14 | 1.63s | 1.35s (**-17%**) |
| `cell_scheduler.cpp` | ~2 | 2.09s | 2.08s (-0.5%) |
| `du_cell_config_validation.cpp` | ~1 | 1.54s | 1.70s (**+10%**) |

Net across the sample: **+0.5%**. Reverted.

## Why the plan was wrong

- **112 was a repo-wide count.** Instantiation is charged per TU, and no TU used
  more than 3 distinct spellings -- except the bitset tests themselves. The
  cost the refactor set out to remove had never existed in any TU.
- **Lazy instantiation.** Member functions of a class template are instantiated
  only when called, so the unused ones were free already.
- **The forwarder added instantiations.** Wrapper plus shared body is two
  function instantiations where there had been one. That is why the multiplier-1
  TU got 10% *worse*: the change is a strict loss until the multiplier is large
  enough to amortise the extra wrapper.

The refactor did exactly what it was designed to do. It just only helped two
test files, because those were the only TUs with a large multiplier.

## The header half, and its ceiling

The same effort included dropping `math_utils.h` from a widely included header
(it reached `adt/complex.h` -> `<complex>` -> `<sstream>`, i.e. iostreams) for a
single `divide_ceil` call.

Measured effect on the sampled TUs: **-10 headers, -94 preprocessed lines.**
Nearly nothing, because `<complex>` also arrived via `ran/phy_time_unit.h`
(756 of 1911 TUs, needing only `divide_round` and `pow2`) and `<functional>` via
`adt/expected.h`. Removing one path out of three changes nothing.

The ceiling check settled whether to chase the other paths: `<complex>` costs
0.25s per TU, against a 7.35s TU -- about 3% of the build even if every path
were fixed, in exchange for an include-what-you-use sweep across hundreds of
files. Not worth it, and knowing the number is what made that a decision rather
than a guess.

## What did pay

Two small things, both from de-templating rather than re-layering:

- `nof_words`, `assert_within_bounds` and `assert_range_bounds` became plain
  **non-template free functions**. They carry the `fmt`-based assert machinery,
  so they had real weight, and they now instantiate zero times.
- `std::is_convertible_v<T, std::function<void(size_t)>>` in a `static_assert`
  became `std::is_invocable_v<T&, size_t>`. Instantiating a `std::function`
  conversion purely to test a signature is expensive; on one TU this alone moved
  instantiation time 1.54s -> 1.47s. It also accepts move-only callables.

## Fallout worth budgeting for

Dropping the transitively-supplied include broke **83 objects** across 16 files
that had been free-riding on it (`math_utils.h` x7, `<vector>` x6, `<sstream>`
x2). `ninja -k 0` enumerated them in one pass; classifying by the *first* error
per file separated the 16 real causes from ~109 cascade errors.
