const DATA = {

    TextZoom: {

        description:
            "Real paired scene text super-resolution evaluation.",

        metricScope:
            "Focused 30-image TextZoom evaluation (Table 4.4).",

        metrics: [
            ["Bicubic", "56.7%", "0.0%", "26.2%"],
            ["Real-ESRGAN", "60.0%", "0.0%", "19.9%"],
            ["TSRN", "83.3%", "30.0%", "54.8%"],
            ["C3-STISR", "96.7%", "46.7%", "74.4%"]
        ],

        samples: {

            "easy_097 — Galore": {

                image:
                    "assets/textzoom/easy_097_galore.png",

                groundTruth:
                    "Galore",

                description:
                    "Easy TextZoom example. C3-STISR produced the strongest textual reconstruction in this focused comparison."
            },

            "medium_041 — behind": {
                image:
                    "assets/textzoom/medium_041_behind.png",

                groundTruth:
                    "behind",

                description:
                    "Medium TextZoom example showing partial character reconstruction. C3-STISR produced a result closer to the ground truth than TSRN, although neither reconstruction was completely correct."
            },
            
            "hard_042 — Mochi": {

                image:
                    "assets/textzoom/hard_042_mochi.png",

                groundTruth:
                    "Mochi",

                description:
                    "Hard TextZoom example. TSRN contains merged or incorrectly reconstructed character structure, while C3-STISR preserves the word more successfully."
            }
        }
    },


    CUTE80: {

        description:
            "Synthetic cross-dataset evaluation containing curved and irregular scene text.",

        metricScope:
            "Complete 288-image CUTE80 evaluation (Table 4.5).",

        metrics: [
            ["Bicubic", "75.7%", "34.4%", "54.8%"],
            ["Real-ESRGAN", "77.4%", "33.3%", "56.2%"],
            ["TSRN", "70.8%", "37.2%", "54.4%"],
            ["C3-STISR", "70.8%", "35.4%", "53.9%"]
        ],

        samples: {
            "cute80_0054 — VILLA": {

                image:
                    "assets/cute80/cute80_0054_villa.png",

                groundTruth:
                    "VILLA",

                description:
                    "CUTE80 example where all methods preserve the word correctly. Real-ESRGAN produces the cleanest visual result, while C3-STISR introduces visible colour artefacts."
            },

            "cute80_0122 — FRIENDSHIP": {

                image:
                    "assets/cute80/cute80_0122_friendship.png",

                groundTruth:
                    "FRIENDSHIP",

                description:
                    "Curved-text CUTE80 example. Real-ESRGAN was judged visually strongest, while its OCR result remained imperfect."
            },

            "cute80_0215 — RESTAURANT": {

                image:
                    "assets/cute80/cute80_0215_restaurant.png",

                groundTruth:
                    "RESTAURANT",

                description:
                    "Curved CUTE80 example demonstrating the difference between visual quality and preservation of textual content."
            }
        }
    }
};


const datasetSelect =
    document.getElementById("dataset");

const sampleSelect =
    document.getElementById("sample");

const comparisonImage =
    document.getElementById("comparison-image");

const sampleTitle =
    document.getElementById("sample-title");

const groundTruth =
    document.getElementById("ground-truth");

const sampleDescription =
    document.getElementById("sample-description");

const datasetDescription =
    document.getElementById("dataset-description");

const metricScope =
    document.getElementById("metric-scope");

const metricsBody =
    document.getElementById("metrics-body");


function updateSampleOptions() {

    const dataset =
        DATA[datasetSelect.value];

    sampleSelect.innerHTML = "";

    Object.keys(dataset.samples).forEach(
        sampleName => {

            const option =
                document.createElement("option");

            option.value = sampleName;
            option.textContent = sampleName;

            sampleSelect.appendChild(option);
        }
    );

    updateDisplay();
}


function updateMetrics(dataset) {

    metricsBody.innerHTML = "";

    dataset.metrics.forEach(row => {

        const tr =
            document.createElement("tr");

        row.forEach(value => {

            const td =
                document.createElement("td");

            td.textContent = value;
            tr.appendChild(td);
        });

        metricsBody.appendChild(tr);
    });
}


function updateDisplay() {

    const dataset =
        DATA[datasetSelect.value];

    const sample =
        dataset.samples[sampleSelect.value];

    sampleTitle.textContent =
        sampleSelect.value;

    datasetDescription.textContent =
        dataset.description;

    comparisonImage.src =
        sample.image;

    comparisonImage.alt =
        `${sampleSelect.value} super-resolution comparison`;

    groundTruth.innerHTML =
        `Ground truth: <span>${sample.groundTruth}</span>`;

    sampleDescription.textContent =
        sample.description;

    metricScope.textContent =
        dataset.metricScope;

    updateMetrics(dataset);
}


datasetSelect.addEventListener(
    "change",
    updateSampleOptions
);

sampleSelect.addEventListener(
    "change",
    updateDisplay
);


updateSampleOptions();
