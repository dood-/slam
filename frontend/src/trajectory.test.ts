import { describe, expect, it } from 'vitest'
import { contiguousSegments, poseAt, projection } from './trajectory'
import type { Model, Sample } from './api'

const sample = (timeSec:number, position:[number,number,number]|null, orientationXyzw:[number,number,number,number]|null, status:'estimated'|'missing'='estimated'):Sample => ({ frameId: timeSec * 10, timeSec, segmentId: status === 'estimated' ? 'a' : null, status, position, orientationXyzw })

describe('trajectory public seam', () => {
  it('does not invent poses outside coverage or across missing samples', () => {
    const samples = [sample(1, [0,0,0], [0,0,0,1]), sample(2, null, null, 'missing'), sample(3, [3,0,0], [0,0,0,1])]
    expect(poseAt(samples, 0)).toBeNull()
    expect(poseAt(samples, 2)).toBeNull()
    expect(poseAt(samples, 4)).toBeNull()
  })

  it('linearly interpolates position and slerps orientation only inside a segment', () => {
    const samples = [sample(0, [0,2,0], [0,0,0,1]), sample(2, [4,6,0], [0,0,1,0])]
    const pose = poseAt(samples, 1)
    expect(pose?.position).toEqual([2,4,0])
    expect(pose?.orientationXyzw?.[2]).toBeCloseTo(Math.SQRT1_2, 5)
    expect(pose?.orientationXyzw?.[3]).toBeCloseTo(Math.SQRT1_2, 5)
  })

  it('keeps disconnected sample runs as separate segments', () => {
    const samples = [sample(0,[0,0,0],[0,0,0,1]), sample(1,null,null,'missing'), sample(2,[2,0,0],[0,0,0,1])]
    expect(contiguousSegments(samples).map(s => s.map(x => x.timeSec))).toEqual([[0],[2]])
  })

  it('projects without independently stretching axes', () => {
    const model = { samples: [sample(0,[0,0,0],[0,0,0,1]),sample(1,[10,0,5],[0,0,0,1])], segments: [], quality: {} } as unknown as Model
    const points = projection(model, 'XZ', 400, 200)
    expect(Math.abs(points[1].x - points[0].x)).toBeCloseTo(200, 5)
    expect(Math.abs(points[1].y - points[0].y)).toBeCloseTo(100, 5)
  })
})
