"""Compare overlapping camera paths up to a 3D similarity transform.

A user-accepted partial reconstruction is a reference, NOT metric ground truth.
Run with backend/.venv/bin/python; optional threshold detects disagreement only.
"""
import argparse
import json
from pathlib import Path
import numpy as np

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--storage', type=Path, default=Path('storage'))
parser.add_argument('--reference', required=True)
parser.add_argument('--candidate', required=True)
parser.add_argument('--max-relative-rmse', type=float)
args = parser.parse_args()


def load(run_id):
    trajectory = json.loads((args.storage/'runs'/run_id/'manifest.json').read_text())['trajectory']
    model = next(model for model in trajectory['models'] if model['id'] == trajectory['primaryModelId'])
    return trajectory, model


def interpolate(samples, times, time):
    index = int(np.searchsorted(times, time, side='right'))-1
    if index < 0:
        return None
    left = samples[index]
    if left['position'] is None:
        return None
    if abs(left['timeSec']-time) < 1e-7:
        return np.array(left['position'])
    if index+1 >= len(samples):
        return None
    right = samples[index+1]
    if right['position'] is None or right['segmentId'] != left['segmentId']:
        return None
    fraction = (time-left['timeSec'])/(right['timeSec']-left['timeSec'])
    return np.array(left['position'])*(1-fraction)+np.array(right['position'])*fraction


reference, reference_model = load(args.reference)
candidate, candidate_model = load(args.candidate)
if reference['video']['sha256'] != candidate['video']['sha256']:
    raise SystemExit('Different input videos')
times = np.array([s['timeSec'] for s in candidate_model['samples']])
pairs = []
for sample in reference_model['samples']:
    if sample['position'] is None:
        continue
    position = interpolate(candidate_model['samples'], times, sample['timeSec'])
    if position is not None:
        pairs.append((sample['position'], position))
if len(pairs) < 3:
    raise SystemExit('Insufficient overlapping valid samples')
reference_positions, candidate_positions = np.array(pairs).transpose(1,0,2)
p = reference_positions-reference_positions.mean(0)
q = candidate_positions-candidate_positions.mean(0)
u, singular, vt = np.linalg.svd(q.T@p)
proper = np.eye(3)
proper[-1,-1] = np.linalg.det(u@vt)
rotation = u@proper@vt
scale = np.sum(singular*np.diag(proper))/np.sum(q*q)
error = np.linalg.norm(scale*q@rotation-p, axis=1)
spread = np.sqrt(np.mean(np.sum(p*p, axis=1)))
relative_rmse = float(np.sqrt(np.mean(error*error))/spread)
print(json.dumps({'reference':args.reference,'candidate':args.candidate,
    'overlappingSamples':len(pairs),'relativeRmseToReferenceSpread':relative_rmse,
    'referenceCamera':reference_model['camera'],'candidateCamera':candidate_model['camera'],
    'note':'Disagreement after Sim(3) alignment; not error in meters or proof of reference accuracy'},indent=2))
if args.max_relative_rmse is not None and relative_rmse > args.max_relative_rmse:
    raise SystemExit(2)
