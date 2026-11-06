import { Quaternion } from "three";
import type { Model, Sample } from "./api";
export type Pose = Omit<Sample, "status"> & {
    status: "estimated" | "interpolated";
};
export type Plane = "XY" | "XZ" | "YZ";

export function contiguousSegments(samples: Sample[]): Sample[][] {
    const result: Sample[][] = [];
    let previous: Sample | undefined;
    for (const sample of samples) {
        if (sample.status === "missing" || !sample.position) {
            previous = undefined;
            continue;
        }
        if (!previous || previous.segmentId !== sample.segmentId)
            result.push([]);
        result[result.length - 1].push(sample);
        previous = sample;
    }
    return result;
}

export function poseAt(samples: Sample[], time: number): Pose | null {
    if (
        !samples.length ||
        time < samples[0].timeSec ||
        time > samples[samples.length - 1].timeSec
    )
        return null;
    let low = 0,
        high = samples.length - 1;
    while (low < high) {
        const mid = Math.ceil((low + high) / 2);
        if (samples[mid].timeSec <= time) low = mid;
        else high = mid - 1;
    }
    const left = samples[low],
        right = samples[low + 1];
    if (!left.position || !left.orientationXyzw || left.status === "missing")
        return null;
    if (Math.abs(time - left.timeSec) < 1e-7)
        return { ...left, status: "estimated" };
    if (
        !right?.position ||
        !right.orientationXyzw ||
        right.status === "missing" ||
        right.segmentId !== left.segmentId
    )
        return null;
    const fraction = (time - left.timeSec) / (right.timeSec - left.timeSec);
    const orientation = new Quaternion(...left.orientationXyzw).slerp(
        new Quaternion(...right.orientationXyzw),
        fraction,
    );
    return {
        ...left,
        timeSec: time,
        status: "interpolated",
        position: left.position.map(
            (v, i) => v + (right.position![i] - v) * fraction,
        ) as [number, number, number],
        orientationXyzw: orientation.toArray(),
    };
}

export function projection(
    model: Pick<Model, "samples">,
    plane: Plane,
    width: number,
    height: number,
) {
    const [a, b] = plane === "XY" ? [0, 1] : plane === "XZ" ? [0, 2] : [1, 2];
    const samples = model.samples.filter(
        (s) => s.position && s.status === "estimated",
    );
    if (!samples.length) return [];
    const xs = samples.map((s) => s.position![a]),
        ys = samples.map((s) => s.position![b]);
    const minX = Math.min(...xs),
        maxX = Math.max(...xs),
        minY = Math.min(...ys),
        maxY = Math.max(...ys);
    const scale =
        0.5 * Math.min(width / (maxX - minX || 1), height / (maxY - minY || 1));
    return samples.map((sample) => ({
        sample,
        x: width / 2 + (sample.position![a] - (minX + maxX) / 2) * scale,
        y: height / 2 - (sample.position![b] - (minY + maxY) / 2) * scale,
    }));
}
