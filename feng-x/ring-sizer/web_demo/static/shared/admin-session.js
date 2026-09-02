(function (root) {
  "use strict";

  const FINGERS = ["index", "middle", "ring"];

  function present(value) {
    return value !== null && value !== undefined && value !== "";
  }

  function summary(row) {
    const recommendation = row && row.session_recommendation;
    if (!recommendation || typeof recommendation !== "object" || Array.isArray(recommendation)) {
      return null;
    }

    const perFinger = {};
    const storedPerFinger = recommendation.per_finger;
    if (storedPerFinger && typeof storedPerFinger === "object") {
      FINGERS.forEach((finger) => {
        const item = storedPerFinger[finger];
        if (item && item.status === "ok" && present(item.best_match)) {
          perFinger[finger] = item.best_match;
        }
      });
    }

    const sessionId = present(row.session_id)
      ? String(row.session_id)
      : (present(recommendation.session_id) ? String(recommendation.session_id) : "");

    return {
      overallSize: present(recommendation.overall_best_size)
        ? recommendation.overall_best_size
        : null,
      handedness: present(recommendation.handedness) ? recommendation.handedness : "",
      successfulShots: present(recommendation.successful_shots)
        ? recommendation.successful_shots
        : null,
      attemptIndex: present(row.session_attempt_index)
        ? row.session_attempt_index
        : (present(recommendation.attempt_index) ? recommendation.attempt_index : null),
      sessionId,
      shortSessionId: sessionId ? sessionId.slice(0, 8) : "",
      perFinger,
    };
  }

  root.AdminSession = { summary };
}(window));
