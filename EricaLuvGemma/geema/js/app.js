import { MovementControl } from "./movement-control.js";

const canvas =
    document.getElementById("animation-canvas");

const controls =
    document.getElementById("controls");

if (!(canvas instanceof HTMLCanvasElement)) {
    throw new Error(
        "Animation canvas was not found."
    );
}

if (!(controls instanceof HTMLElement)) {
    throw new Error(
        "Animation controls were not found."
    );
}

const movement =
    new MovementControl(canvas, {
        basePath:
            "./assets/skeleton-crusader/png/vector-parts/",

        scmlFile:
            "Animations.scml",

        entityName:
            "Skeleton_Crusader",

        animationName:
            "Base"
    });

let ready = false;

/*
 * Run one movement command.
 */

async function runMovement(name) {
    if (!ready || movement.busy) {
        return;
    }

    clearError();
    setActiveButton(name);

    try {
        switch (name) {
            case "head-tilt":
                await movement.headTilt();
                break;

            case "crouch":
                await movement.crouch();
                break;

            case "hop":
                await movement.hop();
                break;

            case "reset":
                movement.reset();
                break;

            default:
                console.warn(
                    `Unknown movement: ${name}`
                );
        }
    } catch (error) {
        console.error(
            `Movement "${name}" failed.`,
            error
        );

        showError(
            `Could not perform "${name}". Check the browser console.`
        );
    } finally {
        setActiveButton(null);
    }
}

/*
 * Highlight the selected control.
 */

function setActiveButton(name) {
    const buttons =
        controls.querySelectorAll(
            "[data-movement]"
        );

    buttons.forEach((button) => {
        const active =
            button.dataset.movement === name;

        button.classList.toggle(
            "active",
            active
        );

        button.setAttribute(
            "aria-pressed",
            String(active)
        );
    });
}

/*
 * Show an error below the stage.
 */

function showError(message) {
    let errorBox =
        document.getElementById(
            "engine-error"
        );

    if (!errorBox) {
        errorBox =
            document.createElement("p");

        errorBox.id =
            "engine-error";

        document
            .getElementById("app")
            ?.appendChild(errorBox);
    }

    errorBox.textContent =
        message;
}

function clearError() {
    document
        .getElementById("engine-error")
        ?.remove();
}

/*
 * Button controls.
 */

controls.addEventListener(
    "click",
    (event) => {
        const target =
            event.target;

        if (!(target instanceof Element)) {
            return;
        }

        const button =
            target.closest(
                "[data-movement]"
            );

        if (
            !(
                button instanceof
                HTMLButtonElement
            )
        ) {
            return;
        }

        const movementName =
            button.dataset.movement;

        if (!movementName) {
            return;
        }

        runMovement(
            movementName
        );
    }
);

/*
 * Keyboard controls.
 *
 * 1 = Head tilt
 * 2 = Crouch
 * 3 = Hop
 * 0 = Reset
 */

const keyboardMovements = {
    "1": "head-tilt",
    "2": "crouch",
    "3": "hop",
    "0": "reset"
};

window.addEventListener(
    "keydown",
    (event) => {
        const movementName =
            keyboardMovements[
                event.key
            ];

        if (movementName) {
            runMovement(
                movementName
            );
        }
    }
);

/*
 * Start the rig engine.
 */

async function start() {
    console.log(
        "Loading Geema movement engine..."
    );

    clearError();

    try {
        await movement.load();

        ready = true;

        console.log(
            "Geema movement engine ready."
        );

        /*
         * Automatic proof-of-life test.
         */

        await movement.crouch();
    } catch (error) {
        console.error(
            "Movement engine failed to load.",
            error
        );

        showError(
            "The movement engine could not load. Check the browser console."
        );
    }
}

start();