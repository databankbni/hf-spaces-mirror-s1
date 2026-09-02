/*
 * GEEMA CHARACTER RIG
 *
 * Loads a Spriter SCML character and reconstructs its
 * separated PNG parts on an HTML canvas.
 */

export class CharacterRig {
    constructor(canvas, options = {}) {
        if (!(canvas instanceof HTMLCanvasElement)) {
            throw new TypeError(
                "CharacterRig requires a valid canvas element."
            );
        }

        this.canvas = canvas;
        this.ctx = canvas.getContext("2d");

        if (!this.ctx) {
            throw new Error(
                "Could not create the canvas 2D context."
            );
        }

        this.basePath =
            options.basePath ??
            "./assets/skeleton-crusader/png/vector-parts/";

        this.scmlFile =
            options.scmlFile ??
            "Animations.scml";

        this.entityName =
            options.entityName ??
            "Skeleton_Crusader";

        this.animationName =
            options.animationName ??
            "Base";

        this.images = new Map();
        this.files = new Map();
        this.timelines = new Map();

        this.objectRefs = [];
        this.boneRefs = [];

        this.partOverrides = new Map();

        this.character = {
            x: 0,
            y: 0,
            scale: 0.55,
            rotation: 0
        };

        this.ready = false;

        this.ctx.imageSmoothingEnabled = true;

        this.resize();

        this.handleResize = () => {
            this.resize();

            if (this.ready) {
                this.render();
            }
        };

        window.addEventListener(
            "resize",
            this.handleResize
        );
    }

    /*
     * Load the SCML file and every image referenced by it.
     */

    async load() {
        const scmlURL =
            this.createURL(this.scmlFile);

        const response = await fetch(scmlURL);

        if (!response.ok) {
            throw new Error(
                `Could not load SCML file: ${scmlURL}`
            );
        }

        const xmlText = await response.text();

        const parser = new DOMParser();

        const xml = parser.parseFromString(
            xmlText,
            "application/xml"
        );

        const parseError =
            xml.querySelector("parsererror");

        if (parseError) {
            throw new Error(
                "Animations.scml contains invalid XML."
            );
        }

        this.readFiles(xml);
        this.readAnimation(xml);

        await this.loadImages();

        this.ready = true;
        this.render();
    }

    /*
     * Read PNG file definitions from the SCML.
     */

    readFiles(xml) {
        const fileElements =
            xml.querySelectorAll("folder > file");

        fileElements.forEach((fileElement) => {
            const id =
                Number(fileElement.getAttribute("id"));

            const name =
                fileElement.getAttribute("name");

            if (!name) {
                return;
            }

            this.files.set(id, {
                id,
                name,

                width:
                    Number(
                        fileElement.getAttribute("width")
                    ) || 0,

                height:
                    Number(
                        fileElement.getAttribute("height")
                    ) || 0,

                pivotX:
                    Number(
                        fileElement.getAttribute("pivot_x")
                    ) || 0,

                pivotY:
                    Number(
                        fileElement.getAttribute("pivot_y")
                    ) || 0
            });
        });
    }

    /*
     * Read the selected entity and animation.
     */

    readAnimation(xml) {
        const entities =
            [...xml.querySelectorAll("entity")];

        const entity = entities.find(
            (item) =>
                item.getAttribute("name") ===
                this.entityName
        );

        if (!entity) {
            throw new Error(
                `Entity "${this.entityName}" was not found.`
            );
        }

        const animations = [
            ...entity.querySelectorAll(
                ":scope > animation"
            )
        ];

        const animation = animations.find(
            (item) =>
                item.getAttribute("name") ===
                this.animationName
        );

        if (!animation) {
            throw new Error(
                `Animation "${this.animationName}" was not found.`
            );
        }

        this.readTimelines(animation);
        this.readMainline(animation);
    }

    /*
     * Read the first key of each timeline.
     *
     * For this first engine test, we reconstruct only
     * the starting pose of the selected animation.
     */

    readTimelines(animation) {
        this.timelines.clear();

        const timelines = animation.querySelectorAll(
            ":scope > timeline"
        );

        timelines.forEach((timeline) => {
            const timelineId =
                Number(
                    timeline.getAttribute("id")
                );

            const timelineName =
                timeline.getAttribute("name") ??
                `timeline-${timelineId}`;

            const objectType =
                timeline.getAttribute("object_type") ??
                "sprite";

            const firstKey =
                timeline.querySelector(
                    ":scope > key"
                );

            if (!firstKey) {
                return;
            }

            const dataElement =
                firstKey.querySelector(
                    ":scope > object, :scope > bone"
                );

            if (!dataElement) {
                return;
            }

            this.timelines.set(
                timelineId,
                {
                    id: timelineId,
                    name: timelineName,
                    objectType,

                    folder:
                        Number(
                            dataElement.getAttribute(
                                "folder"
                            )
                        ) || 0,

                    file:
                        Number(
                            dataElement.getAttribute(
                                "file"
                            )
                        ),

                    x:
                        Number(
                            dataElement.getAttribute("x")
                        ) || 0,

                    y:
                        Number(
                            dataElement.getAttribute("y")
                        ) || 0,

                    angle:
                        Number(
                            dataElement.getAttribute(
                                "angle"
                            )
                        ) || 0,

                    scaleX:
                        Number(
                            dataElement.getAttribute(
                                "scale_x"
                            )
                        ) || 1,

                    scaleY:
                        Number(
                            dataElement.getAttribute(
                                "scale_y"
                            )
                        ) || 1,

                    alpha:
                        dataElement.hasAttribute("a")
                            ? Number(
                                  dataElement.getAttribute(
                                      "a"
                                  )
                              )
                            : 1,

                    pivotX:
                        dataElement.hasAttribute(
                            "pivot_x"
                        )
                            ? Number(
                                  dataElement.getAttribute(
                                      "pivot_x"
                                  )
                              )
                            : null,

                    pivotY:
                        dataElement.hasAttribute(
                            "pivot_y"
                        )
                            ? Number(
                                  dataElement.getAttribute(
                                      "pivot_y"
                                  )
                              )
                            : null
                }
            );
        });
    }

    /*
     * Read the hierarchy and drawing order.
     */

    readMainline(animation) {
        const mainlineKey =
            animation.querySelector(
                "mainline > key"
            );

        if (!mainlineKey) {
            throw new Error(
                "The animation does not contain a mainline key."
            );
        }

        this.boneRefs = [
            ...mainlineKey.querySelectorAll(
                ":scope > bone_ref"
            )
        ].map((reference) => ({
            id:
                Number(
                    reference.getAttribute("id")
                ),

            timeline:
                Number(
                    reference.getAttribute(
                        "timeline"
                    )
                ),

            parent:
                reference.hasAttribute("parent")
                    ? Number(
                          reference.getAttribute(
                              "parent"
                          )
                      )
                    : null
        }));

        this.objectRefs = [
            ...mainlineKey.querySelectorAll(
                ":scope > object_ref"
            )
        ]
            .map((reference) => ({
                id:
                    Number(
                        reference.getAttribute("id")
                    ),

                timeline:
                    Number(
                        reference.getAttribute(
                            "timeline"
                        )
                    ),

                parent:
                    reference.hasAttribute("parent")
                        ? Number(
                              reference.getAttribute(
                                  "parent"
                              )
                          )
                        : null,

                zIndex:
                    Number(
                        reference.getAttribute(
                            "z_index"
                        )
                    ) || 0
            }))
            .sort(
                (a, b) =>
                    a.zIndex - b.zIndex
            );
    }

    /*
     * Load every PNG referenced in the SCML.
     */

    async loadImages() {
        const jobs = [];

        this.files.forEach((file) => {
            jobs.push(
                this.loadImage(
                    file.id,
                    this.createURL(file.name)
                )
            );
        });

        await Promise.all(jobs);
    }

    loadImage(fileId, url) {
        return new Promise(
            (resolve, reject) => {
                const image = new Image();

                image.onload = () => {
                    this.images.set(
                        fileId,
                        image
                    );

                    resolve(image);
                };

                image.onerror = () => {
                    reject(
                        new Error(
                            `Could not load rig part: ${url}`
                        )
                    );
                };

                image.src = url;
            }
        );
    }

    /*
     * Render the complete character.
     */

    render() {
        if (!this.ready) {
            return;
        }

        const width = this.canvas.width;
        const height = this.canvas.height;

        this.ctx.clearRect(
            0,
            0,
            width,
            height
        );

        const boneTransforms =
            this.calculateBones();

        this.ctx.save();

        this.ctx.translate(
            width / 2 + this.character.x,
            height * 0.72 + this.character.y
        );

        this.ctx.rotate(
            this.degreesToRadians(
                this.character.rotation
            )
        );

        this.ctx.scale(
            this.character.scale,
            this.character.scale
        );

        for (const reference of this.objectRefs) {
            const timeline =
                this.timelines.get(
                    reference.timeline
                );

            if (
                !timeline ||
                timeline.objectType === "bone"
            ) {
                continue;
            }

            const parentTransform =
                reference.parent !== null
                    ? boneTransforms.get(
                          reference.parent
                      )
                    : null;

            this.drawTimeline(
                timeline,
                parentTransform
            );
        }

        this.ctx.restore();
    }

    /*
     * Calculate all bone transforms.
     */

    calculateBones() {
        const calculated = new Map();

        const resolveBone = (boneReference) => {
            if (
                calculated.has(
                    boneReference.id
                )
            ) {
                return calculated.get(
                    boneReference.id
                );
            }

            const timeline =
                this.timelines.get(
                    boneReference.timeline
                );

            if (!timeline) {
                return null;
            }

            let transform = {
                x: timeline.x,
                y: -timeline.y,

                angle: -timeline.angle,

                scaleX: timeline.scaleX,
                scaleY: timeline.scaleY
            };

            if (
                boneReference.parent !== null
            ) {
                const parentReference =
                    this.boneRefs.find(
                        (item) =>
                            item.id ===
                            boneReference.parent
                    );

                if (parentReference) {
                    const parent =
                        resolveBone(
                            parentReference
                        );

                    if (parent) {
                        transform =
                            this.combineTransforms(
                                parent,
                                transform
                            );
                    }
                }
            }

            calculated.set(
                boneReference.id,
                transform
            );

            return transform;
        };

        this.boneRefs.forEach(
            resolveBone
        );

        return calculated;
    }

    /*
     * Draw one sprite timeline.
     */

    drawTimeline(timeline, parentTransform) {
        const file =
            this.files.get(timeline.file);

        const image =
            this.images.get(timeline.file);

        if (!file || !image) {
            return;
        }

        const override =
            this.partOverrides.get(
                timeline.name
            ) ?? {};

        let localTransform = {
            x:
                timeline.x +
                (override.x ?? 0),

            y:
                -timeline.y +
                (override.y ?? 0),

            angle:
                -timeline.angle +
                (override.rotation ?? 0),

            scaleX:
                timeline.scaleX *
                (override.scaleX ?? 1),

            scaleY:
                timeline.scaleY *
                (override.scaleY ?? 1)
        };

        if (parentTransform) {
            localTransform =
                this.combineTransforms(
                    parentTransform,
                    localTransform
                );
        }

        const pivotX =
            timeline.pivotX ??
            file.pivotX;

        const pivotY =
            timeline.pivotY ??
            file.pivotY;

        const drawX =
            -pivotX * image.width;

        const drawY =
            -(1 - pivotY) *
            image.height;

        this.ctx.save();

        this.ctx.globalAlpha =
            timeline.alpha *
            (override.alpha ?? 1);

        this.ctx.translate(
            localTransform.x,
            localTransform.y
        );

        this.ctx.rotate(
            this.degreesToRadians(
                localTransform.angle
            )
        );

        this.ctx.scale(
            localTransform.scaleX,
            localTransform.scaleY
        );

        this.ctx.drawImage(
            image,
            drawX,
            drawY
        );

        this.ctx.restore();
    }

    /*
     * Combine a child transform with its parent.
     */

    combineTransforms(parent, child) {
        const radians =
            this.degreesToRadians(
                parent.angle
            );

        const scaledX =
            child.x * parent.scaleX;

        const scaledY =
            child.y * parent.scaleY;

        const rotatedX =
            scaledX * Math.cos(radians) -
            scaledY * Math.sin(radians);

        const rotatedY =
            scaledX * Math.sin(radians) +
            scaledY * Math.cos(radians);

        return {
            x:
                parent.x +
                rotatedX,

            y:
                parent.y +
                rotatedY,

            angle:
                parent.angle +
                child.angle,

            scaleX:
                parent.scaleX *
                child.scaleX,

            scaleY:
                parent.scaleY *
                child.scaleY
        };
    }

    /*
     * Change one body part.
     *
     * Example:
     *
     * rig.setPart("Head", {
     *     rotation: 12,
     *     x: 5,
     *     y: -8
     * });
     */

    setPart(name, values = {}) {
        const current =
            this.partOverrides.get(name) ??
            {};

        this.partOverrides.set(
            name,
            {
                ...current,
                ...values
            }
        );

        this.render();
    }

    getPart(name) {
        return {
            ...(
                this.partOverrides.get(name) ??
                {}
            )
        };
    }

    resetPart(name) {
        this.partOverrides.delete(name);
        this.render();
    }

    resetPose() {
        this.partOverrides.clear();

        this.character.x = 0;
        this.character.y = 0;
        this.character.rotation = 0;

        this.render();
    }

    /*
     * Move the whole character.
     */

    setCharacter(values = {}) {
        Object.assign(
            this.character,
            values
        );

        this.render();
    }

    resize() {
        const rectangle =
            this.canvas.getBoundingClientRect();

        const ratio =
            window.devicePixelRatio || 1;

        const width = Math.max(
            1,
            Math.floor(
                rectangle.width * ratio
            )
        );

        const height = Math.max(
            1,
            Math.floor(
                rectangle.height * ratio
            )
        );

        if (
            this.canvas.width !== width ||
            this.canvas.height !== height
        ) {
            this.canvas.width = width;
            this.canvas.height = height;
        }

        this.ctx.imageSmoothingEnabled = true;
    }

    createURL(filename) {
        const base =
            this.basePath.replace(
                /\/+$/,
                ""
            );

        const file =
            filename.replace(
                /^\/+/,
                ""
            );

        return `${base}/${file}`;
    }

    degreesToRadians(degrees) {
        return (
            degrees *
            Math.PI /
            180
        );
    }

    destroy() {
        window.removeEventListener(
            "resize",
            this.handleResize
        );

        this.images.clear();
        this.files.clear();
        this.timelines.clear();
        this.partOverrides.clear();
    }
}