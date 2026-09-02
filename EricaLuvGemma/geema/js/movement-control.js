import { CharacterRig } from "./character-rig.js";

export class MovementControl {
    constructor(canvas, options = {}) {
        this.rig = new CharacterRig(canvas, {
            basePath:
                options.basePath ??
                "./assets/skeleton-crusader/png/vector-parts/",

            scmlFile:
                options.scmlFile ??
                "Animations.scml",

            entityName:
                options.entityName ??
                "Skeleton_Crusader",

            animationName:
                options.animationName ??
                "Base"
        });

        this.busy = false;
        this.animationFrameId = null;
        this.movementToken = 0;
    }

    async load() {
        await this.rig.load();
    }

    /*
     * Smoothly animate numeric values.
     */

    animate({
        duration = 300,
        easing = this.easeInOut,
        update
    }) {
        const token = ++this.movementToken;

        if (this.animationFrameId !== null) {
            cancelAnimationFrame(
                this.animationFrameId
            );

            this.animationFrameId = null;
        }

        return new Promise((resolve) => {
            const startTime =
                performance.now();

            const frame = (time) => {
                if (token !== this.movementToken) {
                    resolve(false);
                    return;
                }

                const elapsed =
                    time - startTime;

                const progress =
                    Math.min(
                        elapsed / duration,
                        1
                    );

                update(
                    easing(progress)
                );

                if (progress < 1) {
                    this.animationFrameId =
                        requestAnimationFrame(
                            frame
                        );
                } else {
                    this.animationFrameId = null;
                    resolve(true);
                }
            };

            this.animationFrameId =
                requestAnimationFrame(frame);
        });
    }

    /*
     * First movement test:
     * move down slightly, tilt the head,
     * then return to the base pose.
     */

    async crouch() {
        if (this.busy) {
            return;
        }

        this.busy = true;

        try {
            await this.animate({
                duration: 250,

                update: (progress) => {
                    this.rig.setCharacter({
                        y: 20 * progress
                    });

                    this.rig.setPart("Head", {
                        rotation:
                            -5 * progress
                    });
                }
            });

            await this.wait(180);

            await this.animate({
                duration: 300,

                update: (progress) => {
                    const reverse =
                        1 - progress;

                    this.rig.setCharacter({
                        y: 20 * reverse
                    });

                    this.rig.setPart("Head", {
                        rotation:
                            -5 * reverse
                    });
                }
            });

            this.rig.resetPose();
        } finally {
            this.busy = false;
        }
    }

    /*
     * Move the complete character upward and back down.
     * This tests whole-character movement before
     * creating a full body-part jump.
     */

    async hop() {
        if (this.busy) {
            return;
        }

        this.busy = true;

        try {
            await this.animate({
                duration: 180,
                easing: this.easeOut,

                update: (progress) => {
                    this.rig.setCharacter({
                        y: -80 * progress
                    });
                }
            });

            await this.animate({
                duration: 220,
                easing: this.easeIn,

                update: (progress) => {
                    this.rig.setCharacter({
                        y:
                            -80 +
                            80 * progress
                    });
                }
            });

            this.rig.resetPose();
        } finally {
            this.busy = false;
        }
    }

    /*
     * Test an individual body part.
     */

    async headTilt() {
        if (this.busy) {
            return;
        }

        this.busy = true;

        try {
            await this.animate({
                duration: 250,

                update: (progress) => {
                    this.rig.setPart("Head", {
                        rotation:
                            12 * progress
                    });
                }
            });

            await this.wait(300);

            await this.animate({
                duration: 250,

                update: (progress) => {
                    this.rig.setPart("Head", {
                        rotation:
                            12 *
                            (1 - progress)
                    });
                }
            });

            this.rig.resetPart("Head");
        } finally {
            this.busy = false;
        }
    }

    reset() {
        this.movementToken++;

        if (this.animationFrameId !== null) {
            cancelAnimationFrame(
                this.animationFrameId
            );

            this.animationFrameId = null;
        }

        this.busy = false;
        this.rig.resetPose();
    }

    wait(milliseconds) {
        return new Promise((resolve) => {
            setTimeout(
                resolve,
                milliseconds
            );
        });
    }

    easeInOut(value) {
        return value < 0.5
            ? 2 * value * value
            : 1 -
                Math.pow(
                    -2 * value + 2,
                    2
                ) /
                    2;
    }

    easeIn(value) {
        return value * value;
    }

    easeOut(value) {
        return (
            1 -
            Math.pow(
                1 - value,
                2
            )
        );
    }

    destroy() {
        this.reset();
        this.rig.destroy();
    }
}