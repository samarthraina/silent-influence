"""Check record coverage, hashes and primary point estimates without importing the analysis.

--compare-reanalysis also compares all saved fields with scripts/analyze_results.py output.
Standard library only; no model, network, GPU, or generation is used.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

EXT = Path(__file__).resolve().parents[1]


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def close(a, b):
    assert math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12), (a, b)


def mean(values):
    return math.fsum(values) / len(values)


def records(folder, manifest):
    planned = {r['unit_id'] for r in lines(manifest)}
    found = {}
    for path in sorted(folder.glob('attempts*.jsonl')):
        for rec in lines(path):
            payload = rec['payload']
            body = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
            assert hashlib.sha256(body.encode()).hexdigest() == rec['payload_sha256'], path
            assert rec['unit_id'] in planned
            if rec['status'] not in ('accepted', 'permanent_failure'):
                continue
            assert rec['unit_id'] not in found, 'duplicate final unit'
            found[rec['unit_id']] = payload
    return found, planned


def compare(a, b, path=''):
    if isinstance(a, (float, int)) and not isinstance(a, bool):
        close(a, b)
    elif isinstance(a, dict):
        assert a.keys() == b.keys(), path
        for key in a:
            compare(a[key], b[key], path + '/' + key)
    elif isinstance(a, list):
        assert len(a) == len(b), path
        for i, (x, y) in enumerate(zip(a, b)):
            compare(x, y, path + '/' + str(i))
    else:
        assert a == b, path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compare-reanalysis', action='store_true')
    args = parser.parse_args()
    saved = {name: json.loads((EXT / f'results/analysis/{name}.json').read_text())
             for name in ('calibration', 'study_llama', 'study_qwen')}
    calibration_manifest = EXT / 'artifacts/calibration/run_manifest_v1.jsonl'
    units = {r['unit_id']: r for r in lines(calibration_manifest)}
    all_calibration = {}
    for model in ('llama', 'qwen'):
        recs, planned = records(EXT / f'results/raw/calibration/{model}', calibration_manifest)
        assert len(recs) == 180
        assert set(recs) == {uid for uid, u in units.items() if u['model_key'] == model}
        all_calibration.update(recs)
        cells = {}
        for uid, p in recs.items():
            u = units[uid]
            cells[u['base_task_id'], u['rubric_id'], u['context']] = (
                p['analysis_score'] if p['analysis_valid'] else None)
        paired = []
        for task in sorted({u['base_task_id'] for u in units.values()}):
            values = [cells[task, rubric, context] for rubric in ('original', 'explicit_v1')
                      for context in ('no_history', 'self_low_2')]
            if all(v is not None for v in values):
                original, explicit = values[0] - values[1], values[2] - values[3]
                paired.append((original, explicit))
        primary = saved['calibration'][model]['primary_interaction']['complete_case']
        assert len(paired) == primary['n']
        close(mean([a - b for a, b in paired]), primary['estimate'])
        print(f'{model} calibration: {len(recs)} units, {len(paired)} paired tasks; '
              f'original effect {mean([a for a, _ in paired]):.6f}, '
              f'explicit effect {mean([b for _, b in paired]):.6f}')
    assert len(all_calibration) == 360
    assert dict(Counter(p['analysis_validity'] for p in all_calibration.values())) == saved['calibration']['status_counts']

    for model, site, dirname, filename in (
        ('llama', 24, 'matched_history_patching', 'mhp_manifest_v1.jsonl'),
        ('qwen', 27, 'matched_history_patching_qwen', 'mhp_qwen_manifest_v1.jsonl')):
        recs, planned = records(EXT / f'results/raw/study_{model}', EXT / dirname / filename)
        assert set(recs) == planned and len(recs) == 720
        result = saved[f'study_{model}']
        assert dict(Counter(p['analysis_validity'] for p in recs.values())) == result['validity_counts']
        rows = {(p['base_task_id'], p['key']): p for p in recs.values()}
        tasks = sorted({task for task, _ in rows})
        assert len(tasks) == 72
        checks = 0
        for task in tasks:
            for context in ('self_high_10', 'self_low_2'):
                base = rows[task, 'baseline:' + context]['generated_token_ids_sha256']
                assert base
                for kind in ('noop', 'same_state'):
                    assert rows[task, kind + ':' + context]['generated_token_ids_sha256'] == base
                    checks += 1
        assert checks == result['identity']['checked'] == 288
        score = lambda task, key: rows[task, key]['analysis_score'] if rows[task, key]['analysis_valid'] else None
        gaps = [score(t, 'baseline:self_high_10') - score(t, 'baseline:self_low_2') for t in tasks]
        close(mean(gaps), result['primary']['baseline_high_minus_low']['mean'])
        for source, target in (('self_high_10', 'self_low_2'), ('self_low_2', 'self_high_10')):
            direction = source + '->' + target
            values = []
            for task in tasks:
                src, tgt = score(task, 'baseline:' + source), score(task, 'baseline:' + target)
                sp, ctl = score(task, f'patch:L{site}:' + direction), score(task, 'patch:L2:' + direction)
                if all(v is not None for v in (src, tgt, sp, ctl)) and src != tgt:
                    values.append(((sp - tgt) - (ctl - tgt)) / (src - tgt))
            expected = result['primary'][direction]['paired_site_minus_control']
            assert len(values) == expected['n']
            close(mean(values), expected['mean'])
        print(f'{model} patching: 720 units, 72 tasks, 288 identity checks, primary estimates match')
    if args.compare_reanalysis:
        for name, expected in saved.items():
            actual = json.loads((EXT / f'outputs/analysis/{name}.json').read_text())
            compare(expected, actual, name)
        print('All reanalysed fields match the saved results within 1e-12.')
    print('PASS: 1,800 final units, payload hashes, coverage, identities, and primary estimates.')


if __name__ == '__main__':
    main()
