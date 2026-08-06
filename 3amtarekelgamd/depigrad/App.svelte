<script>
  let transactionData = {
    TransactionDT: 0,
    TransactionAmt: 0,
    card1_amt_mean: 0,
    card1_amt_std: 0,
    V2_te: 0,
    V3_te: 0,
    C1: 0,
    D1: 0,
    id_01: 0,
  };

  // Need valid check for import meta inside vite, fallback gracefully
  let backendUrl = "";
  try {
    backendUrl = import.meta.env.VITE_BACKEND_URL ?? "";
  } catch (e) {}

  let loading = false;
  let result = null;
  let errorMessage = "";

  function getPredictUrl() {
    const trimmed = backendUrl.trim().replace(/\/$/, "");
    return trimmed;
  }

  function loadNormalSample() {
    result = null;
    errorMessage = "";
    transactionData = {
      TransactionDT: 12045.0,
      TransactionAmt: 145.99,
      card1_amt_mean: 140.0,
      card1_amt_std: 15.0,
      V2_te: 0.05,
      V3_te: 0.05,
      C1: 1.0,
      D1: 0.0,
      id_01: 0.0,
    };
  }

  function loadFraudSample() {
    result = null;
    errorMessage = "";
    transactionData = {
      TransactionDT: 7440202.00000,
      TransactionAmt: 226.00000,
      ProductCD: 4.00000,
      card4: 4.00000,
      card6: 1.00000,
      addr1: 299.00000,
      addr2: 87.00000,
      dist1: 130.00000,
      C1: 2.00000,
      C3: 0.00000,
      C5: 0.00000,
      C7: 0.00000,
      C9: 3.00000,
      C13: 7.00000,
      D1: 5.00000,
      D2: 5.00000,
      D3: 0.00000,
      D4: 0.00000,
      D5: 0.00000,
      D6: 0.00000,
      D8: 37.87500,
      D9: 0.66650,
      D10: 4.00000,
      D11: 4.00000,
      D12: 0.00000,
      D13: 0.00000,
      D14: 0.00000,
      D15: 3.00000,
      M1: 1.00000,
      M2: 1.00000,
      M3: 0.00000,
      M4: 1.00000,
      M5: 1.00000,
      M6: 1.00000,
      M7: 0.00000,
      M8: 0.00000,
      M9: 1.00000,
      id_01: -5.00000,
      id_02: 125800.50000,
      id_03: 0.00000,
      id_04: 0.00000,
      id_05: 0.00000,
      id_06: 0.00000,
      id_09: 0.00000,
      id_10: 0.00000,
      id_11: 100.00000,
      id_12: 2.00000,
      id_13: 52.00000,
      id_14: -300.00000,
      id_15: 3.00000,
      id_16: 2.00000,
      id_17: 166.00000,
      id_19: 341.00000,
      id_20: 472.00000,
      id_28: 2.00000,
      id_29: 2.00000,
      id_30: 74.00000,
      id_31: 96.00000,
      id_32: 24.00000,
      id_33: 260.00000,
      id_34: 4.00000,
      id_35: 2.00000,
      id_36: 2.00000,
      id_37: 2.00000,
      id_38: 2.00000,
      DeviceType: 1.00000,
      DeviceInfo: 1735.00000,
      dist1_was_missing: 0.00000,
      R_emaildomain_was_missing: 0.00000,
      D2_was_missing: 0.00000,
      D3_was_missing: 0.00000,
      D5_was_missing: 0.00000,
      D6_was_missing: 0.00000,
      D8_was_missing: 0.00000,
      D9_was_missing: 0.00000,
      DT_hour_of_day: 2.72278,
      DT_day_of_week: 2.11345,
      DT_week: 12.00000,
      DT_is_night: 1.00000,
      TransactionAmt_log: 5.42578,
      TransactionAmt_decimal: 0.00000,
      TransactionAmt_is_round: 1.00000,
      card1_amt_mean: 254.04256,
      card1_amt_std: 70.36302,
      card1_amt_zscore: -0.39854,
      card2_amt_mean: 125.70373,
      card2_amt_std: 205.93976,
      card2_amt_zscore: 0.48702,
      M_sum: 5.00000,
      M_miss_count: 0.00000,
      V2_te: 0.03004,
      V3_te: 0.07948,
      V4_te: 0.03644,
      V5_te: 0.28522,
      V6_te: 0.03521,
      V7_te: 0.03512,
      V8_te: 0.03503,
      V9_te: 0.04834,
      V10_te: 0.04351,
      V12_te: 0.02773,
      V13_te: 0.02723,
      V15_te: 0.02522,
      V17_te: 0.02540,
      V19_te: 0.03643,
      V20_te: 0.05586,
      V23_te: 0.03232,
      V24_te: 0.03234,
      V25_te: 0.03459,
      V26_te: 0.07718,
      V29_te: 0.04858,
      V31_te: 0.02527,
      V35_te: 0.02728,
      V36_te: 0.02692,
      V37_te: 0.02998,
      V38_te: 0.02870,
      V39_te: 0.02537,
      V40_te: 0.02534,
      V42_te: 0.02557,
      V44_te: 0.02900,
      V45_te: 0.02820,
      V46_te: 0.03306,
      V47_te: 0.03181,
      V48_te: 0.04542,
      V50_te: 0.02507,
      V51_te: 0.10166,
      V53_te: 0.14800,
      V54_te: 0.08795,
      V55_te: 0.08867,
      V56_te: 0.09883,
      V57_te: 0.02635,
      V59_te: 0.02672,
      V61_te: 0.11421,
      V62_te: 0.28189,
      V63_te: 0.02683,
      V64_te: 0.02673,
      V66_te: 0.03349,
      V67_te: 0.13404,
      V69_te: 0.04863,
      V71_te: 0.02659,
      V73_te: 0.09921,
      V75_te: 0.04435,
      V76_te: 0.02751,
      V77_te: 0.03059,
      V78_te: 0.14343,
      V79_te: 0.02484,
      V80_te: 0.02537,
      V82_te: 0.03549,
      V83_te: 0.17566,
      V84_te: 0.02550,
      V85_te: 0.02546,
      V86_te: 0.02933,
      V87_te: 0.02865,
      V90_te: 0.04878,
      V92_te: 0.02492,
      V95_te: 0.10988,
      V96_te: 0.06221,
      V98_te: 0.03380,
      V99_te: 0.02498,
      V100_te: 0.03666,
      V104_te: 0.03426,
      V105_te: 0.03391,
      V109_te: 0.03387,
      V114_te: 0.03357,
      V115_te: 0.03353,
      V116_te: 0.03350,
      V123_te: 0.03221,
      V124_te: 0.03258,
      V125_te: 0.03221,
      V129_te: 0.03380,
      V130_te: 0.15228,
      V131_te: 0.17265,
      V135_te: 0.03426,
      V136_te: 0.03391,
      V137_te: 0.03397,
      V138_te: 0.03471,
      V139_te: 0.03308,
      V140_te: 0.03283,
      V142_te: 0.03453,
      V144_te: 0.03389,
      V146_te: 0.03334,
      V147_te: 0.03320,
      V148_te: 0.03368,
      V152_te: 0.03375,
      V157_te: 0.03338,
      V161_te: 0.03454,
      V162_te: 0.03449,
      V165_te: 0.03384,
      V166_te: 0.03389,
      V169_te: 0.03388,
      V170_te: 0.02627,
      V171_te: 0.02570,
      V172_te: 0.03430,
      V173_te: 0.03475,
      V174_te: 0.03339,
      V175_te: 0.03333,
      V176_te: 0.02848,
      V180_te: 0.03171,
      V181_te: 0.03230,
      V183_te: 0.03193,
      V184_te: 0.03203,
      V185_te: 0.03199,
      V186_te: 0.02960,
      V187_te: 0.02851,
      V188_te: 0.02912,
      V189_te: 0.02861,
      V190_te: 0.02832,
      V191_te: 0.03301,
      V194_te: 0.03266,
      V195_te: 0.03244,
      V197_te: 0.03282,
      V198_te: 0.03267,
      V200_te: 0.02717,
      V201_te: 0.02668,
      V203_te: 0.02558,
      V205_te: 0.03430,
      V206_te: 0.03475,
      V207_te: 0.03370,
      V208_te: 0.03339,
      V209_te: 0.03331,
      V210_te: 0.03333,
      V214_te: 0.03230,
      V215_te: 0.03175,
      V216_te: 0.03193,
      V217_te: 0.02591,
      V218_te: 0.02486,
      V220_te: 0.03384,
      V221_te: 0.02428,
      V223_te: 0.03414,
      V224_te: 0.03265,
      V226_te: 0.03388,
      V227_te: 0.03301,
      V228_te: 0.02791,
      V229_te: 0.02650,
      V230_te: 0.02699,
      V234_te: 0.03071,
      V235_te: 0.03204,
      V236_te: 0.03106,
      V238_te: 0.03213,
      V239_te: 0.03175,
      V242_te: 0.02892,
      V243_te: 0.02812,
      V245_te: 0.02668,
      V246_te: 0.02774,
      V247_te: 0.03279,
      V248_te: 0.03195,
      V250_te: 0.02991,
      V252_te: 0.03311,
      V255_te: 0.02988,
      V257_te: 0.02689,
      V258_te: 0.02620,
      V259_te: 0.02513,
      V260_te: 0.03210,
      V261_te: 0.03046,
      V262_te: 0.03105,
      V263_te: 0.02591,
      V264_te: 0.02486,
      V265_te: 0.02516,
      V266_te: 0.03414,
      V267_te: 0.03265,
      V268_te: 0.03324,
      V270_te: 0.03308,
      V271_te: 0.03294,
      V274_te: 0.02678,
      V275_te: 0.02713,
      V276_te: 0.03204,
      V277_te: 0.03106,
      V278_te: 0.03154,
      V281_te: 0.22861,
      V282_te: 0.25284,
      V283_te: 0.10384,
      V284_te: 0.05711,
      V285_te: 0.02760,
      V286_te: 0.03480,
      V287_te: 0.06783,
      V288_te: 0.04424,
      V289_te: 0.07067,
      V290_te: 0.10229,
      V291_te: 0.05843,
      V294_te: 0.18494,
      V297_te: 0.03446,
      V300_te: 0.03409,
      V301_te: 0.03379,
      V302_te: 0.02118,
      V303_te: 0.02101,
      V309_te: 0.08762,
      V310_te: 0.35379,
      V311_te: 0.03480,
      V312_te: 0.63593,
      V313_te: 0.32655,
      V314_te: 0.44904,
      V315_te: 0.63108,
      V319_te: 0.03446,
      V320_te: 0.03365,
      V321_te: 0.03394,
      V325_te: 0.03489,
      V326_te: 0.03467,
      V327_te: 0.03470,
      V328_te: 0.03460,
      V334_te: 0.03489,
      V335_te: 0.03467,
      V336_te: 0.03470,
      V337_te: 0.03460,
      V338_te: 0.03446,
      V339_te: 0.03455,
      card1_te: 0.56831,
      card2_te: 0.02252,
      card3_te: 0.02449,
      card5_te: 0.02981,
      P_emaildomain_te: 0.02250,
      R_emaildomain_te: 0.02085,
    };
  }

  function handleCsvUpload(event) {
    const file = event.currentTarget.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = () => {
      const text = String(reader.result || "").trim();
      const [headerLine, rowLine] = text.split(/\r?\n/);
      if (!headerLine || !rowLine) {
        alert("CSV must contain a header row and one data row.");
        return;
      }
      const headers = headerLine.split(",").map((value) => value.trim());
      const values = rowLine.split(",").map((value) => value.trim());
      const nextData = { ...transactionData };
      headers.forEach((header, index) => {
        if (header !== "Class" && header !== "isFraud") {
          nextData[header] = Number(values[index] ?? 0);
        }
      });
      transactionData = nextData;
      alert(
        "CSV loaded successfully. Model will evaluate raw real-world values.",
      );
    };
    reader.readAsText(file);
    event.currentTarget.value = "";
  }

  async function analyzeTransaction() {
    loading = true;
    result = null;
    errorMessage = "";
    const currUrl = getPredictUrl() || "";
    const endpoint = currUrl + "/predict";

    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(transactionData),
      });
      if (!response.ok) throw new Error(`Server returned ${response.status}`);
      result = await response.json();
    } catch (error) {
      errorMessage =
        "Unable to reach the AI backend engine. Ensure server is online.";
    } finally {
      loading = false;
    }
  }
</script>

<svelte:head>
  <style>
    @import url("https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap");
    :global(body) {
      margin: 0;
      padding: 0;
      background-color: #0d1117;
      color: #e6edf3;
      font-family: "Inter", sans-serif;
      min-height: 100vh;
      overflow-x: hidden;
    }
    * {
      box-sizing: border-box;
    }
  </style>
</svelte:head>

<div class="wrapper">
  <!-- Glowing Background Orbs -->
  <div class="orb orb-1"></div>
  <div class="orb orb-2"></div>
  <div class="orb orb-3"></div>

  <main class="dashboard">
    <header>
      <div class="badge">VISION AI</div>
      <h1>FraudGuard <span class="accent">Sentinel</span></h1>
      <p>Next-Generation XGBoost Anomaly Detection</p>
    </header>

    <div class="panels">
      <!-- INPUT PANEL -->
      <section class="glass-panel input-panel">
        <div class="panel-header">
          <h2>
            <div class="icon">⚡</div>
            Payload Entry
          </h2>
        </div>

        <div class="input-grid">
          <label class="full-width">
            <span>API Endpoint (Relative if empty)</span>
            <input
              type="text"
              bind:value={backendUrl}
              placeholder="e.g. http://localhost:8000"
            />
          </label>
          <label>
            <span>Date/Time (DT)</span>
            <input type="number" bind:value={transactionData.TransactionDT} />
          </label>
          <label>
            <span>Amount ($)</span>
            <input type="number" bind:value={transactionData.TransactionAmt} />
          </label>
          <label>
            <span>Ext C1 Count</span>
            <input type="number" bind:value={transactionData.C1} />
          </label>
          <label>
            <span>Ext D1 Count</span>
            <input type="number" bind:value={transactionData.D1} />
          </label>
        </div>

        <div class="actions">
          <button class="secondary safe-btn" on:click={loadNormalSample}
            >Normal Auto-fill</button
          >
          <button class="secondary warn-btn" on:click={loadFraudSample}
            >Fraud Auto-fill</button
          >
          <label class="file-upload secondary">
            Scan CSV Row
            <input
              type="file"
              accept=".csv"
              on:change={handleCsvUpload}
              style="display: none;"
            />
          </label>
        </div>

        <button
          class="primary {loading ? 'pulse' : ''}"
          on:click={analyzeTransaction}
          disabled={loading}
        >
          {#if loading}
            <span class="spinner"></span> Analyzing Deep Patterns...
          {:else}
            Run Neural Analysis
          {/if}
        </button>
      </section>

      <!-- RESULTS PANEL -->
      <section
        class="glass-panel results-panel {result
          ? result.is_fraud
            ? 'fraud-mode'
            : 'safe-mode'
          : ''}"
      >
        <div class="panel-header">
          <h2>
            <div class="icon">📊</div>
            Evaluation Engine
          </h2>
        </div>

        <div class="results-content">
          {#if loading}
            <div class="loader-cont">
              <div class="radar"></div>
              <p>Scanning 310 features vectors...</p>
            </div>
          {:else if errorMessage}
            <div class="error-msg">
              <div class="err-icon">!</div>
              <p>{errorMessage}</p>
            </div>
          {:else if result}
            <div class="verdict-banner">
              {#if result.is_fraud}
                <div class="icon-pulse fail">✗</div>
                <h3>CRITICAL RISK</h3>
              {:else}
                <div class="icon-pulse pass">✓</div>
                <h3>AUTHORIZED</h3>
              {/if}
            </div>

            <div class="metrics">
              <div class="metric">
                <div class="metric-head">
                  <span class="label">Algorithmic Risk Score</span>
                  <span
                    class="val {result.is_fraud ? 'text-red' : 'text-green'}"
                    >{result.risk_score}%</span
                  >
                </div>
                <div class="bar-bg">
                  <div
                    class="bar-fill {result.is_fraud ? 'bg-red' : 'bg-green'}"
                    style="width: {result.risk_score}%; box-shadow: 0 0 10px var({result.is_fraud
                      ? '--red'
                      : '--green'});"
                  ></div>
                </div>
              </div>
              <div class="metric mt-2">
                <span class="label">SHAP Highest Impact Factor</span>
                <span class="val highlight">{result.top_risk_feature}</span>
              </div>
            </div>
          {:else}
            <div class="empty-state">
              <div class="dormant-icon">Zz</div>
              <p>Enter data and click analyze to start.</p>
            </div>
          {/if}
        </div>
      </section>
    </div>
  </main>
</div>

<style>
  :root {
    --primary: #3b82f6;
    --primary-hover: #2563eb;
    --green: #10b981;
    --red: #ef4444;
    --bg-glass: rgba(17, 24, 39, 0.6);
    --border-glass: rgba(255, 255, 255, 0.08);
    --input-bg: rgba(0, 0, 0, 0.3);
  }

  .wrapper {
    position: relative;
    width: 100%;
    min-height: 100vh;
    display: flex;
    justify-content: center;
    align-items: center;
    padding: 40px 20px;
    z-index: 1;
  }

  /* Animated Orbs */
  .orb {
    position: absolute;
    border-radius: 50%;
    filter: blur(80px);
    z-index: -1;
    opacity: 0.5;
    animation: float 20s infinite ease-in-out alternate;
  }
  .orb-1 {
    width: 400px;
    height: 400px;
    background: radial-gradient(circle, #3b82f6 0%, transparent 70%);
    top: -100px;
    left: -100px;
  }
  .orb-2 {
    width: 500px;
    height: 500px;
    background: radial-gradient(circle, #8b5cf6 0%, transparent 70%);
    bottom: -150px;
    right: -100px;
    animation-delay: -5s;
  }
  .orb-3 {
    width: 300px;
    height: 300px;
    background: radial-gradient(circle, #10b981 0%, transparent 70%);
    top: 40%;
    left: 30%;
    opacity: 0.2;
    animation-duration: 25s;
  }

  @keyframes float {
    0% {
      transform: translateY(0) scale(1);
    }
    100% {
      transform: translateY(50px) scale(1.1);
    }
  }

  .dashboard {
    width: 100%;
    max-width: 1000px;
    display: flex;
    flex-direction: column;
    gap: 30px;
  }

  header {
    text-align: center;
    margin-bottom: 10px;
  }
  .badge {
    display: inline-block;
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 2px;
    background: rgba(59, 130, 246, 0.2);
    color: #60a5fa;
    padding: 4px 12px;
    border-radius: 20px;
    border: 1px solid rgba(59, 130, 246, 0.3);
    margin-bottom: 10px;
  }
  h1 {
    font-size: 2.8rem;
    font-weight: 800;
    margin: 0 0 10px;
    background: linear-gradient(to right, #ffffff, #9ca3af);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }
  h1 .accent {
    background: linear-gradient(to right, #3b82f6, #8b5cf6);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }
  header p {
    color: #94a3b8;
    font-size: 1.1rem;
    margin: 0;
  }

  .panels {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 24px;
  }
  @media (max-width: 850px) {
    .panels {
      grid-template-columns: 1fr;
    }
  }

  /* Glassmorphism Panel */
  .glass-panel {
    background: var(--bg-glass);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border: 1px solid var(--border-glass);
    border-radius: 20px;
    padding: 30px;
    box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
    transition: all 0.4s ease;
    display: flex;
    flex-direction: column;
  }

  .results-panel {
    position: relative;
    overflow: hidden;
  }
  .results-panel::before {
    content: "";
    position: absolute;
    inset: 0;
    opacity: 0;
    transition: opacity 0.5s;
    z-index: -1;
  }
  .fraud-mode {
    border-color: rgba(239, 68, 68, 0.4);
    box-shadow: 0 0 30px rgba(239, 68, 68, 0.15);
  }
  .safe-mode {
    border-color: rgba(16, 185, 129, 0.4);
    box-shadow: 0 0 30px rgba(16, 185, 129, 0.15);
  }

  .panel-header {
    display: flex;
    align-items: center;
    margin-bottom: 24px;
    border-bottom: 1px solid var(--border-glass);
    padding-bottom: 16px;
  }
  .panel-header h2 {
    font-size: 1.25rem;
    font-weight: 600;
    margin: 0;
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .icon {
    background: rgba(255, 255, 255, 0.1);
    width: 32px;
    height: 32px;
    display: flex;
    justify-content: center;
    align-items: center;
    border-radius: 8px;
    font-size: 1rem;
  }

  .input-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    margin-bottom: 24px;
  }
  .full-width {
    grid-column: 1 / -1;
  }

  label {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  label span {
    font-size: 0.85rem;
    font-weight: 500;
    color: #cbd5e1;
  }
  input {
    background: var(--input-bg);
    border: 1px solid rgba(255, 255, 255, 0.1);
    color: #fff;
    padding: 12px 16px;
    border-radius: 10px;
    font-size: 1rem;
    font-family: inherit;
    outline: none;
    transition:
      border 0.2s,
      box-shadow 0.2s;
  }
  input:focus {
    border-color: var(--primary);
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.25);
  }

  .actions {
    display: flex;
    gap: 10px;
    margin-bottom: 24px;
    flex-wrap: wrap;
  }

  button,
  .file-upload {
    font-family: inherit;
    font-weight: 600;
    font-size: 0.9rem;
    border-radius: 10px;
    cursor: pointer;
    transition: all 0.2s;
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 8px;
    text-align: center;
  }
  .secondary {
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.1);
    color: #e2e8f0;
    padding: 10px 16px;
    flex: 1;
    min-width: 120px;
  }
  .secondary:hover {
    background: rgba(255, 255, 255, 0.1);
  }
  .safe-btn:hover {
    border-color: rgba(16, 185, 129, 0.5);
    color: #34d399;
  }
  .warn-btn:hover {
    border-color: rgba(239, 68, 68, 0.5);
    color: #f87171;
  }

  .primary {
    width: 100%;
    padding: 16px;
    font-size: 1.05rem;
    background: linear-gradient(135deg, var(--primary), var(--primary-hover));
    color: white;
    border: none;
    font-weight: 700;
    box-shadow: 0 4px 15px rgba(59, 130, 246, 0.3);
  }
  .primary:hover:not(:disabled) {
    transform: translateY(-2px);
    box-shadow: 0 8px 25px rgba(59, 130, 246, 0.4);
  }
  .primary:disabled {
    opacity: 0.7;
    cursor: not-allowed;
  }

  /* Animation utils */
  .pulse {
    animation: pulseBtn 1.5s infinite;
  }
  @keyframes pulseBtn {
    0% {
      box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.7);
    }
    70% {
      box-shadow: 0 0 0 10px rgba(59, 130, 246, 0);
    }
    100% {
      box-shadow: 0 0 0 0 rgba(59, 130, 246, 0);
    }
  }

  .spinner {
    width: 18px;
    height: 18px;
    border: 2px solid rgba(255, 255, 255, 0.3);
    border-radius: 50%;
    border-top-color: #fff;
    animation: spin 1s infinite linear;
  }
  @keyframes spin {
    100% {
      transform: rotate(360deg);
    }
  }

  /* Results styling */
  .results-content {
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    text-align: center;
    height: 100%;
    min-height: 250px;
  }
  .empty-state {
    color: #64748b;
  }
  .dormant-icon {
    font-size: 3rem;
    opacity: 0.3;
    margin-bottom: 10px;
  }

  .loader-cont {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 20px;
  }
  .radar {
    width: 60px;
    height: 60px;
    border-radius: 50%;
    border: 1px solid rgba(59, 130, 246, 0.3);
    position: relative;
    overflow: hidden;
  }
  .radar::before {
    content: "";
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: conic-gradient(
      from 0deg,
      transparent 70%,
      rgba(59, 130, 246, 0.8) 100%
    );
    animation: spin 2s infinite linear;
    transform-origin: center;
  }

  .verdict-banner {
    margin-bottom: 30px;
  }
  .verdict-banner h3 {
    font-size: 1.6rem;
    font-weight: 800;
    margin: 15px 0 0 0;
    letter-spacing: 1px;
  }

  .icon-pulse {
    width: 70px;
    height: 70px;
    margin: 0 auto;
    border-radius: 50%;
    display: flex;
    justify-content: center;
    align-items: center;
    font-size: 2rem;
    font-weight: bold;
    color: white;
    box-shadow: 0 0 30pxcurrentColor;
  }
  .icon-pulse.pass {
    background: var(--green);
    animation: pulseGreen 2s infinite;
  }
  .icon-pulse.fail {
    background: var(--red);
    animation: pulseRed 2s infinite;
  }
  @keyframes pulseGreen {
    0% {
      box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.5);
    }
    70% {
      box-shadow: 0 0 0 20px transparent;
    }
    100% {
      box-shadow: 0 0 0 0 transparent;
    }
  }
  @keyframes pulseRed {
    0% {
      box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.5);
    }
    70% {
      box-shadow: 0 0 0 20px transparent;
    }
    100% {
      box-shadow: 0 0 0 0 transparent;
    }
  }

  .metrics {
    width: 100%;
    background: rgba(0, 0, 0, 0.2);
    border-radius: 12px;
    padding: 20px;
  }
  .metric {
    display: flex;
    flex-direction: column;
    gap: 8px;
    text-align: left;
  }
  .metric-head {
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
  }
  .label {
    font-size: 0.85rem;
    color: #94a3b8;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .val {
    font-size: 1.2rem;
    font-weight: 700;
  }
  .text-red {
    color: #f87171;
  }
  .text-green {
    color: #34d399;
  }

  .bar-bg {
    width: 100%;
    height: 8px;
    background: rgba(255, 255, 255, 0.1);
    border-radius: 4px;
    overflow: hidden;
  }
  .bar-fill {
    height: 100%;
    border-radius: 4px;
    transition: width 1s cubic-bezier(0.4, 0, 0.2, 1);
  }
  .bg-red {
    background: var(--red);
  }
  .bg-green {
    background: var(--green);
  }

  .mt-2 {
    margin-top: 20px;
  }
  .highlight {
    background: rgba(255, 255, 255, 0.1);
    padding: 4px 10px;
    border-radius: 6px;
    font-family: monospace;
    display: inline-block;
    border: 1px solid rgba(255, 255, 255, 0.05);
  }
</style>
