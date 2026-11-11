import itertools
import json
import os
from pathlib import Path
import struct
import subprocess

out = Path('legacy-quote-probe-evidence').resolve()
out.mkdir()
probe = out / 'argv_probe.exe'
subprocess.run(['rustc', '--edition=2021', 'tests/fixtures/curl_argv.rs', '-o', str(probe)], check=True)

cases = [
    'two words\\', 'a"b c\\', 'one\\"two words\\',
    'one\\\\"two words\\\\', 'it\'s "quoted" \\', 'a b"c\\',
    'a"b c"d\\', ' a"b\\', '你好 "test" \\',
    '$env:USERNAME; $(throw \'literal\') %PATH% \\',
]
patterns = [''.join(p) for n in range(1, 7) for p in itertools.product('\\"', repeat=n) if '"' in p]

def ps_string(s):
    return "'" + s.replace("'", "''") + "'"

def native(s, pattern):
    result = '"'
    slashes = 0
    for ch in s:
        if ch == '\\':
            slashes += 1
            continue
        if ch == '"':
            result += '\\' * (2 * slashes) + pattern
        else:
            result += '\\' * slashes + ch
        slashes = 0
    return result + '\\' * (2 * slashes) + '"'

def read_args(path):
    if not path.exists():
        return None
    data = path.read_bytes()
    count, = struct.unpack_from('<I', data)
    pos = 4
    args = []
    for _ in range(count):
        size, = struct.unpack_from('<I', data, pos)
        pos += 4
        args.append(data[pos:pos+size].decode('utf-8'))
        pos += size
    if pos != len(data):
        raise ValueError('Unexpected extra invocation')
    return args

results = {}
for shell in ['powershell.exe', 'pwsh.exe']:
    lines = ["$ErrorActionPreference = 'Stop'", "$PSNativeCommandArgumentPassing = 'Legacy'"]
    specs = []
    for i, pattern in enumerate(patterns):
        for j, case in enumerate(cases):
            path = out / f'{shell}-{i}-{j}.bin'
            encoded = native(case, pattern)
            lines += [f'$env:XH_CURL_ARGV_FILE = {ps_string(str(path))}', f'& {ps_string(str(probe))} {ps_string(encoded)}']
            specs.append((i, j, path, encoded))
    script = out / f'{shell}.ps1'
    script.write_text('\n'.join(lines), encoding='utf-8-sig')
    version = subprocess.check_output([shell, '-NoProfile', '-Command', '$PSVersionTable.PSVersion.ToString()'], text=True).strip()
    run = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(script)], capture_output=True, text=True, timeout=240)
    (out / f'{shell}.log').write_text(run.stdout + run.stderr, encoding='utf-8')
    if run.returncode:
        raise RuntimeError(f'{shell}: {run.returncode}: {run.stderr}')
    records = [{'pattern': patterns[i], 'case': cases[j], 'encoded': encoded, 'args': read_args(path)} for i, j, path, encoded in specs]
    passed = [p for p in patterns if all(r['args'] == [r['case']] for r in records if r['pattern'] == p)]
    results[shell] = {'version': version, 'passing_patterns': passed, 'records': records}
    print(shell, version, 'passing patterns:', passed)
common = sorted(set.intersection(*(set(r['passing_patterns']) for r in results.values())))
print('COMMON:', common)
(out / 'results.json').write_text(json.dumps({'common': common, 'results': results}, ensure_ascii=False, indent=2), encoding='utf-8')
(out / 'provenance.txt').write_text(subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True) + subprocess.check_output(['rustc', '--version'], text=True), encoding='utf-8')
