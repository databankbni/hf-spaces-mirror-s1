const API = "";

let chart, prevChart;

let currentSession =
  JSON.parse(localStorage.getItem("currentSession")) || [];

let previousSession =
  JSON.parse(localStorage.getItem("previousSession")) || [];

let currentFocus = 0.5;
let currentFatigue = 0.3;
let currentDistractions = [];

let isLoading = false;


/* -----------------------------
   TYPING EFFECT
----------------------------- */
function typeText(element, text) {
  element.innerHTML = "";
  element.classList.remove("loading");

  let i = 0;

  function typing() {
    if (i < text.length) {
      element.innerHTML += text.charAt(i);
      i++;
      setTimeout(typing, 18);
    }
  }

  typing();
}


/* -----------------------------
   INIT CHARTS
----------------------------- */
function initCharts() {
  const focusCanvas =
    document.getElementById("focusChart");

  const previousCanvas =
    document.getElementById("prevChart");

  if (!focusCanvas || !previousCanvas) {
    console.error("Chart elements not found.");
    return;
  }

  const ctx1 =
    focusCanvas.getContext("2d");

  const ctx2 =
    previousCanvas.getContext("2d");


  const chartOptions = {
    responsive: true,

    scales: {
      y: {
        min: 0,
        max: 1,

        ticks: {
          color: "#94a3b8",
        },

        grid: {
          color:
            "rgba(148,163,184,0.1)",
        },
      },

      x: {
        ticks: {
          color: "#94a3b8",
        },

        grid: {
          color:
            "rgba(148,163,184,0.1)",
        },
      },
    },

    plugins: {
      legend: {
        labels: {
          color: "#e2e8f0",
        },
      },
    },
  };


  chart = new Chart(ctx1, {
    type: "line",

    data: {
      labels: currentSession.map(
        (_, i) => `Step ${i + 1}`
      ),

      datasets: [
        {
          label: "Focus Level",
          data: currentSession,

          borderColor: "#3b82f6",

          backgroundColor:
            "rgba(59,130,246,0.1)",

          tension: 0.4,
          fill: true,
        },
      ],
    },

    options: chartOptions,
  });


  prevChart = new Chart(ctx2, {
    type: "line",

    data: {
      labels: previousSession.map(
        (_, i) => `Step ${i + 1}`
      ),

      datasets: [
        {
          label: "Focus Level",
          data: previousSession,

          borderColor: "#f97316",

          backgroundColor:
            "rgba(249,115,22,0.1)",

          tension: 0.4,
          fill: true,
        },
      ],
    },

    options: chartOptions,
  });


  if (currentSession.length > 0) {
    currentFocus =
      currentSession[
        currentSession.length - 1
      ];
  }
}


/* -----------------------------
   RESET SESSION
----------------------------- */
function resetSession() {
  localStorage.setItem(
    "previousSession",
    JSON.stringify(currentSession)
  );

  localStorage.setItem(
    "currentSession",
    JSON.stringify([])
  );

  location.reload();
}


/* -----------------------------
   UPDATE LOCAL STATE
----------------------------- */
function updateState(action) {
  currentFatigue += 0.03;


  if (action === "continue") {

    currentFocus +=
      0.04 * (1 - currentFatigue);
  }


  else if (action === "take_break") {

    currentFatigue -= 0.25;
    currentFocus += 0.08;
  }


  else if (
    action === "block_distraction"
  ) {

    if (
      currentDistractions.length > 0
    ) {

      currentDistractions.shift();
      currentFocus += 0.06;
    }
  }


  if (Math.random() < 0.1) {

    currentDistractions.push(
      "instagram"
    );

    currentFocus -= 0.03;
  }


  currentFocus -= 0.02;

  currentFocus -=
    currentFatigue * 0.05;


  currentFocus = Math.max(
    0.05,
    Math.min(
      1,
      currentFocus
    )
  );


  currentFatigue = Math.max(
    0,
    Math.min(
      1,
      currentFatigue
    )
  );
}


/* -----------------------------
   SAFE FETCH
----------------------------- */
async function fetchWithRetry(
  url,
  options,
  retries = 2
) {

  try {

    const response =
      await fetch(
        url,
        options
      );


    if (!response.ok) {

      const errorText =
        await response.text();

      throw new Error(
        `Server error ${response.status}: ${errorText}`
      );
    }


    return await response.json();

  }


  catch (error) {

    if (retries > 0) {

      await new Promise(
        (resolve) =>
          setTimeout(
            resolve,
            500
          )
      );


      return await fetchWithRetry(
        url,
        options,
        retries - 1
      );
    }


    throw error;
  }
}


/* -----------------------------
   STEP ENVIRONMENT
----------------------------- */
async function stepEnv() {

  if (isLoading) {
    return;
  }

  isLoading = true;


  const button =
    document.querySelector(
      ".controls button:first-child"
    );


  if (button) {
    button.disabled = true;
  }


  const adviceElement =
    document.getElementById(
      "advice"
    );


  if (adviceElement) {

    adviceElement.className =
      "typing loading";

    adviceElement.innerHTML =
      "🤖 Thinking...";
  }


  await new Promise(
    (resolve) =>
      setTimeout(
        resolve,
        400
      )
  );


  /* -----------------------------
     INITIAL INPUT
  ----------------------------- */

  if (
    currentSession.length === 0
  ) {

    const focusInput =
      document.getElementById(
        "focusInput"
      );

    const fatigueInput =
      document.getElementById(
        "fatigueInput"
      );

    const distractionInput =
      document.getElementById(
        "distractionInput"
      );


    const focusValue =
      parseFloat(
        focusInput.value
      );

    const fatigueValue =
      parseFloat(
        fatigueInput.value
      );

    const distractionValue =
      distractionInput.value;


    currentFocus =
      isNaN(focusValue)
        ? 0.5
        : Math.max(
            0,
            Math.min(
              1,
              focusValue
            )
          );


    currentFatigue =
      isNaN(fatigueValue)
        ? 0.3
        : Math.max(
            0,
            Math.min(
              1,
              fatigueValue
            )
          );


    currentDistractions =
      distractionValue
        .split(",")
        .map(
          (item) =>
            item.trim()
        )
        .filter(
          (item) => item
        );
  }


  try {

    /* -----------------------------
       SEND STATE TO FASTAPI
    ----------------------------- */

    const data =
      await fetchWithRetry(
        `${API}/step`,
        {
          method: "POST",

          headers: {
            "Content-Type":
              "application/json",
          },

          body: JSON.stringify({
            focus_level:
              currentFocus,

            fatigue:
              currentFatigue,

            distractions:
              currentDistractions,

            time_spent: 0,

            deadline: 60,
          }),
        }
      );


    /* -----------------------------
       BACKEND RL RESPONSE
    ----------------------------- */

    const action =
      data.suggested_action ||
      data.action ||
      "continue";


    const reason =
      data.reason ||
      "Using learned productivity policy.";


    /*
      IMPORTANT:
      Use the advice and confidence
      calculated by the backend.
    */

    const advice =
      data.advice ||
      "Continue working according to the learned policy.";


    const confidence =
      typeof data.confidence === "number"
        ? `${(
            data.confidence * 100
          ).toFixed(0)}%`
        : "0%";


    /* -----------------------------
       UPDATE UI WITH RL RESULTS
    ----------------------------- */

    const actionElement =
      document.getElementById(
        "action"
      );

    const reasonElement =
      document.getElementById(
        "reason"
      );

    const confidenceElement =
      document.getElementById(
        "confidence"
      );


    if (actionElement) {

      actionElement.innerText =
        action;
    }


    if (reasonElement) {

      reasonElement.innerText =
        reason;
    }


    if (confidenceElement) {

      confidenceElement.innerText =
        confidence;
    }


    if (adviceElement) {

      adviceElement.className =
        "typing";

      typeText(
        adviceElement,
        advice
      );
    }


    /* -----------------------------
       UPDATE NEXT SESSION STATE
    ----------------------------- */

    updateState(
      action
    );


    /* -----------------------------
       UPDATE INPUT DISPLAY
    ----------------------------- */

    document.getElementById(
      "focusInput"
    ).value =
      currentFocus.toFixed(2);


    document.getElementById(
      "fatigueInput"
    ).value =
      currentFatigue.toFixed(2);


    document.getElementById(
      "distractionInput"
    ).value =
      currentDistractions.join(
        ", "
      );


    /* -----------------------------
       SAVE SESSION
    ----------------------------- */

    currentSession.push(
      parseFloat(
        currentFocus.toFixed(2)
      )
    );


    localStorage.setItem(
      "currentSession",
      JSON.stringify(
        currentSession
      )
    );


    /* -----------------------------
       UPDATE CHART
    ----------------------------- */

    if (chart) {

      chart.data.labels =
        currentSession.map(
          (_, index) =>
            `Step ${index + 1}`
        );


      chart.data.datasets[0].data =
        currentSession;


      chart.update();
    }


  }


  catch (error) {

    if (adviceElement) {

      adviceElement.className =
        "typing";

      adviceElement.innerHTML =
        "⚠️ Could not reach server. Please try again.";
    }


    console.error(
      "Step error:",
      error
    );
  }


  if (button) {
    button.disabled = false;
  }

  isLoading = false;
}


/* -----------------------------
   PAGE LOAD
----------------------------- */
window.onload = initCharts;