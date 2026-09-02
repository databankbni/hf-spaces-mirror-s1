function createFrames(prefix, totalFrames) {
    return Array.from({ length: totalFrames }, (_, index) => {
        const frameNumber = String(index).padStart(3, "0");
        return `${prefix}${frameNumber}.png`;
    });
}

export const animationManifest = {
    "idle-blinking": {
        path: "idle-blinking",
        frames: createFrames(
            "0_Skeleton_Crusader_Idle_Blinking_",
            18
        ),
        fps: 10,
        loop: true
    },

    walking: {
        path: "walking",
        frames: createFrames(
            "0_Skeleton_Crusader_Walking_",
            24
        ),
        fps: 12,
        loop: true
    },

    running: {
        path: "running",
        frames: createFrames(
            "0_Skeleton_Crusader_Running_",
            12
        ),
        fps: 15,
        loop: true
    },

    "jump-start": {
        path: "jump-start",
        frames: createFrames(
            "0_Skeleton_Crusader_Jump_Start_",
            6
        ),
        fps: 12,
        loop: false,
        next: "jump-loop"
    },

    "jump-loop": {
        path: "jump-loop",
        frames: createFrames(
            "0_Skeleton_Crusader_Jump_Loop_",
            6
        ),
        fps: 12,
        loop: false,
        next: "idle-blinking"
    },

    kicking: {
        path: "kicking",
        frames: createFrames(
            "0_Skeleton_Crusader_Kicking_",
            12
        ),
        fps: 14,
        loop: false,
        next: "idle-blinking"
    },

    slashing: {
        path: "slashing",
        frames: createFrames(
            "0_Skeleton_Crusader_Slashing_",
            12
        ),
        fps: 14,
        loop: false,
        next: "idle-blinking"
    },

    sliding: {
        path: "sliding",
        frames: createFrames(
            "0_Skeleton_Crusader_Sliding_",
            6
        ),
        fps: 12,
        loop: false,
        next: "idle-blinking"
    },

    "falling-down": {
        path: "falling-down",
        frames: createFrames(
            "0_Skeleton_Crusader_Falling_Down_",
            6
        ),
        fps: 10,
        loop: false,
        next: "idle-blinking"
    }
};