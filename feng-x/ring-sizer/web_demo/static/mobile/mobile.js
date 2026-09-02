// Mobile flow entrypoint. Registers six steps that mirror the
// desktop page broken into discrete screens:
//
//   1. intro    — value prop (desktop hero copy)
//   2. form     — name + ring model (desktop hero-card top)
//   3. guide    — photo tips + "like this" sample, opens the camera
//   4. capture  — fullscreen camera coach
//   5. confirm  — preview the captured image, fire measurement
//   6. result   — overlay image + ring-size cards + size reference
//
// Cross-step state lives in `session.js` so back-navigation preserves
// what the user has already entered. Step 3 also exposes an "Upload
// from photos" escape hatch that skips the capture step and hands the
// picked file straight to confirm — same downstream path as a camera
// capture, just with `imageSource = "upload"`.

import { registerStep, setOrder, start } from "./steps.js";
import intro from "./steps/intro.js";
import form from "./steps/form.js";
import guide from "./steps/guide.js";
import capture from "./steps/capture.js";
import confirm from "./steps/confirm.js";
import result from "./steps/result.js";

registerStep("intro", intro);
registerStep("form", form);
registerStep("guide", guide);
registerStep("capture", capture);
registerStep("confirm", confirm);
registerStep("result", result);

setOrder(["intro", "form", "guide", "capture", "confirm", "result"]);

const root = document.getElementById("mobileRoot");
if (root) start(root);
