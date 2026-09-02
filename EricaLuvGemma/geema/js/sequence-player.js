import { animationManifest } from "./animation-manifest.js";

export class SequencePlayer {
    constructor(canvas, options = {}) {
        if (!(canvas instanceof HTMLCanvasElement)) {
            throw new TypeError(
                "SequencePlayer requires a valid canvas element."
            );
        }

        this.canvas = canvas;
        this.ctx = canvas.getContext("2d");

        if (!this.ctx) {
            throw new Error(
                "The browser could not create a 2D canvas context."
            );
        }

        this.basePath = options.basePath || "";
        this.defaultFPS = options.fps || 12;

        this.frames = [];
        this.currentFrame = 0;

        this.playing = false;
        this.loop = true;

        this.animationName = null;
        this.animationFrameId = null;

        this.lastFrameTime = 0;
        this.frameDuration = 1000 / this.defaultFPS;

        this.onComplete = null;
        this.playRequestId = 0;

        this.ctx.imageSmoothingEnabled = false;

        this.resize();

        window.addEventListener("resize", () => {
            this.resize();
        });
    }

    getAnimation(name) {
        const animation = animationManifest[name];

        if (!animation) {
            throw new Error(
                `Animation "${name}" does not exist in the manifest.`
            );
        }

        if (
            !Array.isArray(animation.frames) ||
            animation.frames.length === 0
        ) {
            throw new Error(
                `Animation "${name}" does not contain any frames.`
            );
        }

        return animation;
    }

    async play(name, options = {}) {
        const requestId = ++this.playRequestId;

        this.stop(false);

        const animation = this.getAnimation(name);

        this.animationName = name;

        this.loop =
            options.loop ??
            animation.loop ??
            true;

        this.onComplete =
            typeof options.onComplete === "function"
                ? options.onComplete
                : null;

        const fps =
            options.fps ??
            animation.fps ??
            this.defaultFPS;

        this.frameDuration = 1000 / fps;

        const folder =
            animation.path || name;

        const loadedFrames = await this.loadFrames(
            folder,
            animation.frames
        );

        /*
         * Ignore old loading requests if the user selected
         * another animation before loading completed.
         */
        if (requestId !== this.playRequestId) {
            return;
        }

        this.frames = loadedFrames;
        this.currentFrame = 0;
        this.lastFrameTime = 0;
        this.playing = true;

        this.drawFrame(this.frames[0]);

        this.animationFrameId = requestAnimationFrame(
            (timestamp) => this.tick(timestamp)
        );
    }

    async loadFrames(folder, filenames) {
        const framePromises = filenames.map((filename) => {
            const url = this.createFrameURL(
                folder,
                filename
            );

            return this.loadImage(url);
        });

        return Promise.all(framePromises);
    }

    createFrameURL(folder, filename) {
        const cleanBasePath =
            this.basePath.replace(/\/+$/, "");

        const cleanFolder =
            folder.replace(/^\/+|\/+$/g, "");

        const cleanFilename =
            filename.replace(/^\/+/, "");

        return (
            `${cleanBasePath}/` +
            `${cleanFolder}/` +
            `${cleanFilename}`
        );
    }

    loadImage(url) {
        return new Promise((resolve, reject) => {
            const image = new Image();

            image.onload = () => {
                resolve(image);
            };

            image.onerror = () => {
                reject(
                    new Error(
                        `Could not load frame: ${url}`
                    )
                );
            };

            image.src = url;
        });
    }

    tick(timestamp) {
        if (!this.playing) {
            return;
        }

        if (this.lastFrameTime === 0) {
            this.lastFrameTime = timestamp;
        }

        const elapsed =
            timestamp - this.lastFrameTime;

        if (elapsed >= this.frameDuration) {
            this.lastFrameTime =
                timestamp -
                (elapsed % this.frameDuration);

            this.advanceFrame();
        }

        if (this.playing) {
            this.animationFrameId =
                requestAnimationFrame(
                    (nextTimestamp) =>
                        this.tick(nextTimestamp)
                );
        }
    }

    advanceFrame() {
        const nextFrame =
            this.currentFrame + 1;

        if (nextFrame >= this.frames.length) {
            if (this.loop) {
                this.currentFrame = 0;
            } else {
                this.finish();
                return;
            }
        } else {
            this.currentFrame = nextFrame;
        }

        this.drawFrame(
            this.frames[this.currentFrame]
        );
    }

    drawFrame(image) {
        if (!image) {
            return;
        }

        const canvasWidth = this.canvas.width;
        const canvasHeight = this.canvas.height;

        this.ctx.clearRect(
            0,
            0,
            canvasWidth,
            canvasHeight
        );

        const paddingRatio = 0.08;

        const availableWidth =
            canvasWidth *
            (1 - paddingRatio * 2);

        const availableHeight =
            canvasHeight *
            (1 - paddingRatio * 2);

        const scale = Math.min(
            availableWidth / image.width,
            availableHeight / image.height
        );

        const drawWidth =
            image.width * scale;

        const drawHeight =
            image.height * scale;

        const drawX =
            (canvasWidth - drawWidth) / 2;

        const drawY =
            (canvasHeight - drawHeight) / 2;

        this.ctx.imageSmoothingEnabled = false;

        this.ctx.drawImage(
            image,
            drawX,
            drawY,
            drawWidth,
            drawHeight
        );
    }

    resize() {
        const rect =
            this.canvas.getBoundingClientRect();

        const pixelRatio =
            window.devicePixelRatio || 1;

        const width = Math.max(
            1,
            Math.floor(rect.width * pixelRatio)
        );

        const height = Math.max(
            1,
            Math.floor(rect.height * pixelRatio)
        );

        if (
            this.canvas.width !== width ||
            this.canvas.height !== height
        ) {
            this.canvas.width = width;
            this.canvas.height = height;
        }

        this.ctx.imageSmoothingEnabled = false;

        if (this.frames.length > 0) {
            this.drawFrame(
                this.frames[this.currentFrame]
            );
        }
    }

    finish() {
        this.playing = false;

        if (this.animationFrameId !== null) {
            cancelAnimationFrame(
                this.animationFrameId
            );

            this.animationFrameId = null;
        }

        const completionCallback =
            this.onComplete;

        this.onComplete = null;

        if (completionCallback) {
            completionCallback();
        }
    }

    stop(invalidateRequest = true) {
        this.playing = false;

        if (invalidateRequest) {
            this.playRequestId++;
        }

        if (this.animationFrameId !== null) {
            cancelAnimationFrame(
                this.animationFrameId
            );

            this.animationFrameId = null;
        }

        this.frames = [];
        this.currentFrame = 0;
        this.lastFrameTime = 0;
        this.onComplete = null;
    }
}