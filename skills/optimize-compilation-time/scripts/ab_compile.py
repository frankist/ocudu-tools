#!/usr/bin/env python3
"""Interleaved A/B compile-time measurement for one or more translation units.

Each variant is a directory holding the repo-relative files that differ between
the versions under test (e.g. the headers you edited). The script swaps the
variants in and out, alternating them within every round so that machine drift
hits both sides equally, and reports the median per TU.

  ab_compile.py --build-dir build \
                --tu lib/scheduler/cell_scheduler.cpp \
                --tu tests/unittests/adt/bounded_bitset_test.cpp \
                --variant before=/tmp/v/before --variant after=/tmp/v/after \
                --rounds 5

Build the variant directories by copying the files in their two states, e.g.
  for f in $(git diff --name-only HEAD); do
    mkdir -p /tmp/v/after/$(dirname $f)  && cp $f /tmp/v/after/$f
    mkdir -p /tmp/v/before/$(dirname $f) && git show HEAD:$f > /tmp/v/before/$f
  done
"""
import argparse, json, os, re, shlex, shutil, statistics, subprocess, sys, tempfile, time

# GCC -ftime-report rows worth tracking; these are the phases that header and
# template work actually move.
PHASES = ('template instantiation', 'parser (global)', 'parser (function)')
PHASE_RE = re.compile(r'^\s*(' + '|'.join(map(re.escape, PHASES)) + r')\s*:.*?([\d.]+)\s*\(')


def load_commands(build_dir):
    with open(os.path.join(build_dir, 'compile_commands.json')) as fp:
        return {e['file']: e for e in json.load(fp)}


def compile_args(entry, obj_path):
    """Strip ccache and the build tree's own -o/-M* flags."""
    argv = shlex.split(entry['command'])
    if 'ccache' in os.path.basename(argv[0]):
        argv = argv[1:]
    out, i = [], 0
    while i < len(argv):
        if argv[i] in ('-o', '-MT', '-MF'):
            i += 2
            continue
        if argv[i] == '-MD':
            i += 1
            continue
        out.append(argv[i])
        i += 1
    return out + ['-ftime-report', '-o', obj_path]


def apply_variant(variant_dir, repo_root):
    for dirpath, _, names in os.walk(variant_dir):
        for name in names:
            src = os.path.join(dirpath, name)
            shutil.copyfile(src, os.path.join(repo_root, os.path.relpath(src, variant_dir)))


def measure(entry, obj_path, reps):
    """Best-of-reps, to shave off the worst of the scheduling noise."""
    best = None
    for _ in range(reps):
        argv = compile_args(entry, obj_path)
        start = time.perf_counter()
        proc = subprocess.run(argv, cwd=entry['directory'], capture_output=True)
        elapsed = time.perf_counter() - start
        if proc.returncode != 0:
            sys.exit(proc.stderr.decode(errors='ignore')[-4000:])
        phases = {}
        for line in proc.stderr.decode(errors='ignore').splitlines():
            m = PHASE_RE.match(line)
            if m:
                phases[m.group(1)] = float(m.group(2))
        if best is None or elapsed < best[0]:
            best = (elapsed, phases)
    return best


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--build-dir', required=True)
    ap.add_argument('--tu', action='append', required=True, help='repo-relative source path')
    ap.add_argument('--variant', action='append', required=True, metavar='NAME=DIR')
    ap.add_argument('--repo-root', default=None, help='defaults to $PWD')
    ap.add_argument('--rounds', type=int, default=5)
    ap.add_argument('--reps', type=int, default=2, help='best-of per round')
    ap.add_argument('--phase', default='template instantiation', choices=PHASES)
    args = ap.parse_args()

    repo_root = os.path.abspath(args.repo_root or os.getcwd())
    variants = []
    for spec in args.variant:
        name, _, path = spec.partition('=')
        if not path:
            ap.error(f'--variant expects NAME=DIR, got {spec!r}')
        variants.append((name, os.path.abspath(path)))

    commands = load_commands(args.build_dir)
    entries = {}
    for tu in args.tu:
        key = os.path.join(repo_root, tu)
        if key not in commands:
            ap.error(f'{tu} is not in compile_commands.json')
        entries[tu] = commands[key]

    results = {(name, tu): [] for name, _ in variants for tu in args.tu}
    with tempfile.TemporaryDirectory() as tmp:
        obj = os.path.join(tmp, 'out.o')
        for rnd in range(args.rounds):
            for name, path in variants:
                apply_variant(path, repo_root)
                for tu in args.tu:
                    results[(name, tu)].append(measure(entries[tu], obj, args.reps))
            print(f'round {rnd + 1}/{args.rounds} done', flush=True)
        # Leave the tree on the last variant rather than a random one.
        apply_variant(variants[-1][1], repo_root)

    base = variants[0][0]
    print(f'\nmetric: median of {args.rounds} rounds, best of {args.reps}; phase = {args.phase!r}')
    print(f'tree left on variant {variants[-1][0]!r}\n')
    head = f'{"TU":46s}' + ''.join(f'{n + " wall":>13s}{n + " phase":>14s}' for n, _ in variants)
    print(head)
    print('-' * len(head))
    for tu in args.tu:
        row = f'{tu[-46:]:46s}'
        ref = None
        for name, _ in variants:
            wall = statistics.median(r[0] for r in results[(name, tu)])
            phase = statistics.median(r[1].get(args.phase, 0.0) for r in results[(name, tu)])
            if name == base:
                ref = (wall, phase)
                row += f'{wall:12.3f}s{phase:13.2f}s'
            else:
                dw = (wall - ref[0]) / ref[0] * 100 if ref[0] else 0.0
                dp = (phase - ref[1]) / ref[1] * 100 if ref[1] else 0.0
                row += f'{wall:8.3f}s{dw:+5.0f}%{phase:9.2f}s{dp:+5.0f}%'
        print(row)
    print(f'\nwall clock drifts by tens of percent between rounds; when it disagrees with '
          f'{args.phase!r}, trust the phase.')


if __name__ == '__main__':
    main()
