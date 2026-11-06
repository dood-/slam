export type State =
    "idle" | "running" | "succeeded" | "partial" | "failed" | "cancelled";
export interface Video {
    id: string;
    name: string;
    width: number;
    height: number;
    durationSec: number;
    frameCount: number;
    codec: string;
    sha256: string;
    sizeBytes?: number;
    previewUrl: string;
}
export interface Status {
    state: State;
    runId: string | null;
    videoId: string | null;
    stage: string;
    processed?: number;
    total?: number;
    error?: { code: string; message: string } | null;
}
export interface Sample {
    frameId: number;
    timeSec: number;
    segmentId: string | null;
    status: "estimated" | "missing";
    position: [number, number, number] | null;
    orientationXyzw: [number, number, number, number] | null;
}
export interface Model {
    id: string;
    camera: { model: string; width: number; height: number; params: number[] };
    samples: Sample[];
    segments: { id: string; startTimeSec: number; endTimeSec: number }[];
    quality: {
        registeredFrames: number;
        sampledFrames: number;
        coverage: number;
        points3D: number;
        meanReprojectionErrorPx: number | null;
        maxGapSec: number;
    };
}
export interface Trajectory {
    schemaVersion: number;
    runId: string;
    videoId: string;
    video: Video;
    createdAt: string;
    engine: string;
    units: "arbitrary";
    scaleSource: null;
    poseConvention: string;
    settings: Record<string, number>;
    primaryModelId: string;
    models: Model[];
    warnings: string[];
}
const req = async <T>(url: string, init?: RequestInit): Promise<T> => {
    const r = await fetch("/api" + url, init);
    if (!r.ok) {
        const e = await r.json().catch(() => ({}));
        throw new Error(e.error?.message || `Ошибка API ${r.status}`);
    }
    return r.json();
};
export const api = {
    upload: (file: File) => {
        const f = new FormData();
        f.append("file", file);
        return req<Video>("/videos", { method: "POST", body: f });
    },
    status: () => req<Status>("/status"),
    start: (videoId: string, settings: Record<string, number>) =>
        req<Status>("/runs", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ videoId, settings }),
        }),
    cancel: (id: string) =>
        req<Status>(`/runs/${id}/cancel`, { method: "POST" }),
    results: () =>
        req<
            {
                runId: string;
                videoId: string;
                videoName: string;
                createdAt: string;
                state: "succeeded" | "partial";
                registeredFrames: number;
                sampledFrames: number;
            }[]
        >("/results"),
    result: (id: string) => req<Trajectory>(`/results/${id}`),
};
