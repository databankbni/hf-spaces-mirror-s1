# -*- coding: utf-8 -*-


# FINAL-Bench Quantum — benchmark suite (5 events) + manual Submit. VIDRAFT entries flagged; submissions -> private dataset.


import os, json, time, gradio as gr


# --- Fix gradio 4.44 + new pydantic api-schema bug: "argument of type 'bool' is not iterable" ---


import gradio_client.utils as _gcu


_o_json = _gcu._json_schema_to_python_type


def _safe_json(schema, defs=None):


    if isinstance(schema, bool):


        return "Any"


    return _o_json(schema, defs)


_gcu._json_schema_to_python_type = _safe_json


_o_type = _gcu.get_type


def _safe_type(schema):


    if not isinstance(schema, dict):


        return "Any"


    return _o_type(schema)


_gcu.get_type = _safe_type


# -------------------------------------------------------------------------------------------------


from huggingface_hub import HfApi





TOKEN = os.environ.get("HF_TOKEN")


SUB_DS = "FINAL-Bench/quantum-bench-submissions"


api = HfApi(token=TOKEN)





STYLE = """<style>


.qbody{font-family:Segoe UI,system-ui,sans-serif;color:#1b2436}


.qt{width:100%;border-collapse:collapse;font-size:13px;margin:6px 0 12px}


.qt th{background:#eef3fc;border:1px solid #dde5f2;padding:7px;text-align:left}


.qt td{border:1px solid #dde5f2;padding:7px;vertical-align:top}


.qt td.c,.qt th.c{text-align:center}


.ver{color:#15a34a;font-weight:600}


.rep{color:#b45309;font-weight:600}


.best{}


.ours{}


.muted{color:#5a6b88;font-size:12px;margin:2px 0}


.meth{background:#f6f8fc;border:1px solid #dde5f2;border-radius:6px;padding:8px 10px;font-size:12px;color:#33415c;margin:6px 0}


h3.qh{margin:18px 0 4px} h4.qh{margin:14px 0 4px}


.qt a{color:#2f6fed;text-decoration:none}


</style>"""





def table(headers, rows, center=(), ours_idx=()):


    th = "".join(('<th class="c">%s</th>' if i in center else '<th>%s</th>') % h for i, h in enumerate(headers))


    body = ""


    for ri, r in enumerate(rows):


        tr = ' class="ours"' if ri in ours_idx else ''


        body += "<tr%s>" % tr + "".join(('<td class="c">%s</td>' if i in center else '<td>%s</td>') % c


                                         for i, c in enumerate(r)) + "</tr>"


    return '<table class="qt"><tr>%s</tr>%s</table>' % (th, body)





def page(inner):


    return STYLE + '<div class="qbody">' + inner + '</div>'





VER = '<span class="ver">&#10003; VERIFIED</span>'





# ---------------- Event 1: QEC Decoder ----------------


QEC_A = table(


    ["Rank", "Flag", "Decoder", "By", "LER @ p=0.005", "LER @ p=0.01", "Decode speed", "Status"],


    [["1", "🇺🇸", "Tesseract (A* MLE)", "Google Quantum AI", "0.00915 &#177;0.0013", "0.06245 &#177;0.0034", "~79 ms/shot", VER],


     ["2", "🇰🇷", "VIDRAFT QEC-AI Decoder", "VIDRAFT", "0.00983 &#177;0.0010", "0.06468 &#177;0.0024", "~4 ms* (incl. bases)", VER],


     ["3", "🇬🇧", "BeliefMatching (BP+MWPM)", "O. Higgott", "0.01010 &#177;0.0010", "0.06615 &#177;0.0024", "~1.3 ms/shot", VER],


     ["4", "🇬🇧", "BP+OSD (stimbposd)", "Roffe (ldpc) / Higgott", "0.01020 &#177;0.0010", "0.06453 &#177;0.0024", "~4 ms/shot", VER],


     ["5", "🇬🇧", "PyMatching (MWPM)", "O. Higgott", "0.01388 &#177;0.0012", "0.08393 &#177;0.0027", "~1.7 µs/shot", VER],


     ["6", "🇬🇧", "BP-only (no OSD)", "Roffe (ldpc)", "0.07385 &#177;0.0036", "0.22695 &#177;0.0058", "~ms/shot", VER]],


    center=(0, 1, 4, 5, 6, 7), ours_idx=())


QEC_B = table(


    ["Flag", "Group / Method", "Reported claim", "Source"],


    [["🇺🇸", "Google RL-QEC (Willow)", "surface 7.72e-4/cycle; RL calibration during compute (2026 record)", '<a href="https://www.nature.com/articles/s41586-026-10759-2">Nature 2026</a>'],


     ["🇺🇸", "Microsoft + Quantinuum", "800&times; physical&rarr;logical error reduction; 12 logical qubits (carbon + tesseract codes); peer-reviewed", '<a href="https://thequantuminsider.com/2026/06/13/microsoft-and-quantinuum-report-on-major-gains-in-quantum-error-correction/">Nature 2026</a>'],


     ["🇺🇸", "QuEra", "96 logical qubits, below-threshold (neutral-atom, 2026)", '<a href="https://quantumzeitgeist.com/what-is-quantum-error-correction/">2026</a>'],


     ["🇮🇳", "QpiAI", "ASIC decoder &mdash; 1.5 &micro;s/syndrome, active correction within one cycle", '<a href="https://quantumzeitgeist.com/what-is-quantum-error-correction/">2026</a>'],


     ["🇺🇸", "Google Willow", "d7 surface, 0.143%/cycle, &#923;=2.14", '<a href="https://www.nature.com/articles/s41586-024-08449-y">Nature 2024</a>'],


     ["🇺🇸", "Google AlphaQubit", "neural decoder, &minus;30% vs matching", '<a href="https://www.nature.com/articles/s41586-024-08148-8">Nature 2024</a>'],


     ["🇨🇳", "USTC Zuchongzhi 3.2", "d7 surface &#923;=1.40, below threshold", '<a href="https://link.aps.org/doi/10.1103/rqkg-dw31">PRL 2025</a>'],


     ["🇺🇸", "Quantinuum (trapped ion)", "94 logical qubits, ~1e-4 logical gate", '<a href="https://link.aps.org/doi/10.1103/PhysRevLett.133.180601">PRL 2024</a>'],


     ["🇺🇸", "IBM (BB qLDPC + Relay-BP)", "12 logical/144; Relay-BP &minus;10x vs BP+OSD", '<a href="https://arxiv.org/abs/2506.01779">arXiv 2506.01779</a>'],


     ["🇬🇧", "Riverlane (LCD)", "real-time FPGA decoder, &lt;1µs/round", '<a href="https://www.riverlane.com/news/riverlane-unveils-first-hardware-decoder-to-deliver-real-time-scalable-quantum-error-correction">Nat Commun 2025</a>'],


     ["🇳🇱", "QuTech / Delft", "neural-network decoder &gt; MWPM", '<a href="https://doi.org/10.1103/physrevresearch.7.013029">PRR 2025</a>'],


     ["🇯🇵", "Fujitsu", "Ising-machine (Digital Annealer) decoder", '<a href="https://journals.aps.org/prresearch/abstract/10.1103/PhysRevResearch.4.043086">PRR</a>'],


     ["🇨🇦", "Xanadu (photonic GKP)", "12 logical GKP qubits, real-time QEC", '<a href="https://betakit.com/xanadu-touts-another-advancement-toward-scalable-quantum-computing/">2025</a>'],


     ["🇫🇷", "Alice &amp; Bob (cat qubits)", "bias-tailored bit-flip suppression", '<a href="https://en.wikipedia.org/wiki/Alice_%26_Bob_(company)">ref</a>'],


     ["🇺🇸", "AWS Ocelot (cat qubits)", "d5 logical error ~1.65% (2025)", '<a href="https://www.constellationr.com/insights/news/aws-launches-ocelot-quantum-chip-claims-error-correction-breakthrough">2025</a>'],


     ["🇺🇸", "QuEra / Atom Computing (neutral atom)", "logical qubits at scale; 100-logical target", '<a href="https://www.permutations.app/research/quantum-computing-2026.html">2025&ndash;26</a>'],


     ["🇬🇧", "Riverlane &mdash; Ambiguity Clustering", "qLDPC decoder, &minus;27&times; time vs BP+OSD (matched acc.)", '<a href="https://arxiv.org/abs/2406.14527">arXiv 2406.14527</a>'],


     ["🇺🇸", "Fusion Blossom (Y. Wu)", "parallel MWPM, 1M rounds/s; 0.7 ms latency @d21", '<a href="https://arxiv.org/abs/2305.08307">arXiv 2305.08307</a>'],


     ["🌐", "Union-Find (Delfosse-Nickerson)", "near-linear-time decoder; hardware-friendly", '<a href="https://quantum-journal.org/papers/q-2021-12-02-595/">Quantum 2021</a>'],


     ["🇮🇳", "QpiAI", "real-time decoder, ~1.5 µs/cycle", '<a href="https://www.technerdo.com/blog/quantum-computing-milestones-2026">2026</a>'],


     ["🇩🇪", "Munich MQT QECC", "color-code decoder toolkit", '<a href="https://github.com/munich-quantum-toolkit/qecc">repo</a>'],


     ["🇺🇸", "Infleqtion", "open-source QEC research library", '<a href="https://infleqtion.com/infleqtion-unveils-open-source-library-for-quantum-error-correction-research/">2025</a>'],


     ["🇺🇸", "NVIDIA Ising AI predecoder + MWPM", "learned predecoder; cuts MWPM ~14&ndash;19% (measured here, d9) &mdash; stays in/below the BP-class (BeliefMatching/BP+OSD)", '<a href="https://developer.nvidia.com/cuquantum-sdk">NVIDIA</a>']],


    center=(0,))


QEC_HW = table(


    ["Backend (IBM Heron r2)", "d=3 MV LER (2-err)", "d=5 MV LER (2-err)", "d3&rarr;d5 reduction", "Status"],


    [["ibm_kingston", "0.972 (fails)", "0.0145 (corrects)", "67&times;", VER],


     ["ibm_fez", "0.973 (fails)", "0.0330 (corrects)", "29&times;", VER],


     ["ibm_marrakesh", "0.966 (fails)", "0.0055 (corrects)", "175&times;", VER]],


    center=(1, 2, 3, 4))


QEC_SOFT = table(


    ["Readout noise &sigma;", "Hard-decision LER", "VIDRAFT v2 (soft NN) LER", "Reduction"],


    [["0.8", "0.01497", "0.00834", "44%"],


     ["1.0", "0.03874", "0.02105", "46%"],


     ["1.2", "0.06908", "0.04171", "40%"]],


    center=(0, 1, 2, 3))


QEC_HTML = page(


    '<h3 class="qh">&#9312; QEC Decoder &mdash; Surface Code</h3>'


    '<p class="muted">Rotated surface code (memory Z), d=5, 5 rounds, circuit-level depolarizing noise (Stim). '


    'Logical Error Rate (LER) &mdash; lower is better. &#10003; VERIFIED = measured on this benchmark.</p>'


    '<div class="meth"><b>Protocol &amp; methodology.</b> The four practical decoders (rows 2&ndash;5) are co-measured on one shared '


    '<b>40,000-shot</b> test set; intervals are 95% CIs (normal approx.). Tesseract and BP-only on 20,000 shots. '


    'The VIDRAFT QEC-AI Decoder is a neural ensemble layered on top of classical base decoders &mdash; it is not an '
    'end-to-end network. Its architecture, hyperparameters and training protocol are <b>withheld pending a patent filing</b> '
    'and will be disclosed in the forthcoming methods paper. Every row, including this one, is measured on the same shared '
    'frozen test set under the protocol above.</div>'


    '<h4 class="qh">A. Head-to-head (verified)</h4>' + QEC_A +


    '<div class="meth"><b>Reading the numbers.</b> At p=0.005 the lowest LER among practical (non-MLE) decoders is the neural-ensemble entry '


    '(0.00983), within the overlapping 95% CIs of BeliefMatching and BP+OSD &mdash; a statistical three-way tie &mdash; while all three beat '


    'PyMatching/MWPM with non-overlapping CIs. The maximum-likelihood Tesseract is lower still, but runs at ~79 ms/shot, impractical for '


    'real-time decoding. At p=0.01 the leading practical decoders (BP+OSD and the neural ensemble) sit within each other&#39;s CIs. '


    'Decode <b>latency</b> is a key axis for fault-tolerant operation.</div>'


    '<h4 class="qh">B. Real hardware &mdash; IBM Heron r2 (repetition code, distance-scaling) &nbsp;🇰🇷 VIDRAFT</h4>' + QEC_HW +


    '<div class="meth"><b>Real-hardware result (honest scope).</b> On real IBM Heron r2 QPUs, a distance-d <b>repetition code</b> with a '


    '2-error injection shows the error-correcting <b>distance boundary</b>: d=3 fails to correct two errors (~97% logical error) while d=5 '


    'corrects them (0.5&ndash;3%) &mdash; a <b>29&ndash;175&times;</b> reduction across 3 backends (z = 7&ndash;552&sigma;). A 24k-shot holdout '


    'confirms d5&lt;d3 on 4/4 backend&times;injection pairs. Cumulative ~2.4M QPU shots over 4 IBM Cloud accounts. '


    '<b>Boundaries:</b> repetition code (not surface), single round, <i>offline</i> majority-vote &mdash; <b>not</b> surface-code below-threshold, '


    'not FT-QEC, not a real-time decoder, not quantum advantage. Synthetic threshold study (simulation): qLDPC BB(12,12) p_th&asymp;0.057 vs '


    'surface p_th&asymp;0.021 (&times;2.7).</div>'


    '<h4 class="qh">C. Soft-readout decoding &mdash; where neural decoders win (VIDRAFT v2) &nbsp;🇰🇷</h4>' + QEC_SOFT +


    '<div class="meth"><b>Where the neural decoder genuinely wins.</b> On <i>binary</i> idealized syndromes a neural decoder (v2 transformer) '


    'matches but does not beat BP+OSD &mdash; the classical decoders already sit at the information floor (section A, head-to-head). '


    'But with <b>soft (analog) readout</b> &mdash; the regime where neural decoders help (cf. Google AlphaQubit) &mdash; VIDRAFT v2 exploits the analog '


    'measurement to cut logical error <b>~40&ndash;46%</b> vs hard-decision decoding (d=5 repetition memory, readout-noise dominated), matching the '


    'soft-optimal decoder. The lesson: the gain is in the <i>information</i> (soft / real-hardware data), not the architecture alone.</div>'


    '<h4 class="qh">D. Published references <span class="rep">REPORTED &mdash; setups differ, not verified here</span></h4>' + QEC_B)





# ---------------- Event 2: Optimization (Max-Cut) ----------------


OPT_A = table(


    ["Rank", "Flag", "Method", "By", "Cut", "% of best", "Time (s)", "Status"],


    [["1", "🌐", "Tabu search", "classical (Glover)", "2748", "100.00", "0.24", VER],


     ["2", "🇰🇷", "VIDRAFT QuantumOS (parallel tempering)", "VIDRAFT", "2744", "99.85", "0.43", VER],


     ["3", "🌐", "Simulated annealing", "classical (Kirkpatrick)", "2741", "99.75", "0.30", VER],


     ["4", "🌐", "Random search (20k)", "baseline", "2538", "92.36", "0.33", VER],


     ["5", "🌐", "Greedy (one-pass)", "baseline", "2505", "91.16", "0.01", VER]],


    center=(0, 1, 4, 5, 6, 7), ours_idx=(1,))


OPT_B = table(


    ["Flag", "Method / Platform", "Reported claim", "Source"],


    [["🌐", "QEMC (Qubit-Efficient MaxCut) 2026", "O(log N) qubits: 11 qubits &rarr; 2048-node graph; exponential qubit reduction vs QAOA", '<a href="https://www.nature.com/articles/s41534-026-01186-2">npj Quantum Inf. 2026</a>'],


     ["🇺🇸", "QAOA (Farhi et al.)", "gate-based; &gt;8 layers beats Goemans-Williamson", '<a href="https://arxiv.org/abs/1411.4028">arXiv 1411.4028</a>'],


     ["🇺🇸", "Goemans-Williamson (SDP)", "0.878 approximation guarantee (classical)", '<a href="https://dl.acm.org/doi/10.1145/227683.227684">JACM 1995</a>'],


     ["🇨🇦", "D-Wave Advantage2", "4400+ qubit annealer, Zephyr degree-20", '<a href="https://www.dwavesys.com/">D-Wave</a>'],


     ["🇺🇸", "QuEra Aquila (neutral atom)", "MaxCut/MIS on Rydberg arrays (Ebadi 2022)", '<a href="https://www.science.org/doi/10.1126/science.abo6587">Science 2022</a>']],


    center=(0,))


OPT_QAOA = table(


    ["Flag", "Quantum algorithm", "By", "Layers", "Approx. ratio (&#10216;C&#10217;/opt)", "Status"],


    [["🇰🇷", "QAOA (statevector)", "VIDRAFT (run)", "p=1", "0.811", VER],


     ["🇰🇷", "QAOA (statevector)", "VIDRAFT (run)", "p=2", "0.814", VER],


     ["🇰🇷", "QAOA (statevector)", "VIDRAFT (run)", "p=3", "0.875", VER]],


    center=(0, 3, 4, 5))


OPT_HTML = page(


    '<h3 class="qh">&#9313; Quantum Optimization &mdash; Max-Cut</h3>'


    '<p class="muted">Weighted Max-Cut on a fixed instance G(N=140, p=0.5, seed 7), 4860 edges. Largest cut found (higher is better) + wall time. '


    '% is relative to the best cut found among tested solvers. &#10003; VERIFIED = run on this benchmark&#39;s identical instance.</p>'


    '<h4 class="qh">A. Solvers evaluated (verified, 140-node instance)</h4>' + OPT_A +


    '<h4 class="qh">B. Quantum algorithm &mdash; QAOA (14-node instance, statevector)</h4>' + OPT_QAOA +


    '<p class="muted">QAOA on a 14-node random Max-Cut (44 edges; exact optimum = 32 by brute force). Approximation ratio = expected cut / optimum; '


    'it rises with circuit depth p (0.81 &rarr; 0.88 at p=3, approaching the classical Goemans-Williamson 0.878 guarantee). '


    'Small instance because 140-qubit QAOA is not classically simulable.</p>'


    '<h4 class="qh">C. Published references <span class="rep">REPORTED &mdash; different instances/hardware</span></h4>' + OPT_B)





# ---------------- Event 3: VQE ----------------


VQE_A = table(


    ["Flag", "Method", "By", "System", "Result", "Status"],


    [["🇰🇷", "VIDRAFT VQE (HEA, COBYLA)", "VIDRAFT", "H&#8322; / STO-3G, 4-qubit, eq. (simulation)",


      "energy err 0.22 mHa vs FCI (chemical accuracy)", VER],


     ["🇰🇷", "VIDRAFT VQE (VDR-001, 27-Pauli)", "VIDRAFT", "4-qubit, IBM Heron r2 (real HW)",


      "&minus;0.6763 &#177;0.0022 Ha", VER]],


    center=(0, 5), ours_idx=())


VQE_CURVE = table(


    ["Bond length R (&#8491;)", "FCI energy (Ha)", "VQE energy (Ha)", "Error (mHa)", "Chem. accuracy"],


    [["0.50", "&minus;1.05516", "&minus;1.05158", "3.58", "&mdash;"],


     ["0.735 (eq.)", "&minus;1.13731", "&minus;1.13709", "0.22", "&#10003;"],


     ["1.00", "&minus;1.10115", "&minus;1.10055", "0.60", "&#10003;"],


     ["1.50", "&minus;0.99815", "&minus;0.99724", "0.91", "&#10003;"],


     ["2.00", "&minus;0.94864", "&minus;0.93956", "9.08", "&mdash;"]],


    center=(0, 1, 2, 3, 4))


VQE_B = table(


    ["Flag", "Group / Work", "Reported result", "Source"],


    [["🇯🇵", "RIKEN + IBM (Fugaku) 2026", "iron-sulfur clusters (2Fe-2S, 4Fe-4S): 72 Heron qubits, 36 orbitals; beats CCSD, +278 mHa vs 2024 &mdash; largest/most-accurate quantum chemistry to date", '<a href="https://www.ibm.com/quantum/blog/riken-fugaku-qcsc">IBM &amp; RIKEN 2026</a>'],


     ["🇬🇧", "Peruzzo et al. 2014", "first VQE; photonic chip; HeH&#8314;", '<a href="https://www.nature.com/articles/ncomms5213">Nat Commun 2014</a>'],


     ["🇺🇸", "O'Malley et al. 2016", "H&#8322; dissociation on superconducting qubits", '<a href="https://journals.aps.org/prx/abstract/10.1103/PhysRevX.6.031007">PRX 2016</a>'],


     ["🇨🇭", "Kandala et al. 2017", "hardware-efficient VQE: H&#8322;, LiH, BeH&#8322;", '<a href="https://www.nature.com/articles/nature23879">Nature 2017</a>'],


     ["🇺🇸", "Google AI 2020", "Hartree-Fock on Sycamore: H&#8321;&#8322; (12 qubits)", '<a href="https://www.science.org/doi/10.1126/science.abb9811">Science 2020</a>']],


    center=(0,))


VQE_HTML = page(


    '<h3 class="qh">&#9314; Variational Quantum Eigensolver (VQE)</h3>'


    '<p class="muted">Ground-state energy by VQE. Metric: energy error vs exact diagonalization (FCI); chemical accuracy = &lt; 1.6 mHa. '


    'Reference min-eigenvalue for this operator: &minus;1.857275 Ha. &#10003; VERIFIED = simulated on this benchmark.</p>'


    '<h4 class="qh">A. Verified runs</h4>' + VQE_A +


    '<h4 class="qh">B. H&#8322; dissociation curve (4-qubit, VQE vs FCI)</h4>' + VQE_CURVE +


    '<p class="muted">VQE (hardware-efficient ansatz) reproduces the H&#8322; potential-energy curve, reaching chemical accuracy (&lt;1.6 mHa) at and near equilibrium '


    '(R=0.735&ndash;1.5 &#8491;); the compressed (0.5) and stretched (2.0) geometries miss it &mdash; the known limitation of shallow hardware-efficient ans&auml;tze '


    '(UCCSD/ADAPT close this gap; Phase 2). Larger molecules (LiH, BeH&#8322;) under hardware noise remain the open challenge (Track B).</p>'


    '<h4 class="qh">C. Published references <span class="rep">REPORTED &mdash; real-hardware experiments</span></h4>' + VQE_B)





# ---------------- Event 4: QRAM ----------------


QRAM_QEC = table(


    ["Flag", "Storage noise p", "Unprotected (d1)", "d3", "d7", "d11", "d15", "Status"],


    [["🇰🇷", "10%", "90.0%", "97.2%", "99.7%", "99.97%", '<span class="best">100.0%</span>', VER],


     ["🇰🇷", "20%", "80.0%", "89.6%", "96.7%", "98.8%", '<span class="best">99.6%</span>', VER]],


    center=(0, 1, 2, 3, 4, 5, 6, 7), ours_idx=(0, 1))


QRAM_HW = table(


    ["Flag", "Address", "Expected bit", "Query accuracy", "Shots", "Status"],


    [["🇰🇷", "00", "1", "0.922", "256", VER],


     ["🇰🇷", "01", "0", "0.902", "256", VER],


     ["🇰🇷", "10", "1", "0.906", "256", VER],


     ["🇰🇷", "11", "1", "0.949", "256", VER]],


    center=(0, 1, 2, 3, 4, 5))


QRAM_BB = table(


    ["n (addr)", "cells N", "qubits (BB)", "T-count (BB)", "query fid. BB", "query fid. fanout"],


    [["4", "16", "31", "112", "0.984", "0.984"],


     ["8", "256", "511", "1792", "0.968", "0.774"],


     ["12", "4096", "8191", "28672", '<span class="best">0.953</span>', "0.017"]],


    center=(0, 1, 2, 3, 4, 5))


QRAM_B = table(


    ["Flag", "Work", "Reported result", "Source"],


    [["🇨🇳", "Zhejiang Univ 2026 (experimental BB-QRAM)", "hardware query fidelity: 2-layer 0.80, 3-layer 0.60", '<a href="https://arxiv.org/abs/2506.16682">arXiv 2506.16682</a> / <a href="https://www.nature.com/articles/s41567-026-03218-2">Nat. Phys.</a>'],


     ["🇺🇸", "Giovannetti-Lloyd-Maccone 2008", "bucket-brigade QRAM architecture", '<a href="https://journals.aps.org/prl/abstract/10.1103/PhysRevLett.100.160501">PRL 2008</a>'],


     ["🇺🇸", "Hann et al. 2021", "QRAM noise resilience; infidelity ~ O(polylog N)", '<a href="https://link.aps.org/doi/10.1103/PRXQuantum.2.020311">PRX Quantum 2021</a>']],


    center=(0,))


QRAM_HTML = page(


    '<h3 class="qh">&#9315; QRAM &mdash; Accuracy via QEC protection</h3>'


    '<p class="muted">(A) VIDRAFT QEC-protected QRAM (simulation): a repetition code + majority decode protects the retrieved bit '


    'against storage noise. (B) Bucket-brigade resource/noise model. &#10003; VERIFIED = computed/simulated on this benchmark (exact binomial).</p>'


    '<h4 class="qh">A. VIDRAFT QEC-protected QRAM reliability vs code distance &nbsp;🇰🇷</h4>' + QRAM_QEC +


    '<div class="meth">At 20% storage noise a repetition-code QEC layer raises retrieval reliability from 80% (unprotected) to '


    '<b>99.6% at d=15</b>; at 10% it reaches 100%. The reported hardware QRAM (Zhejiang, Track B) plateaus near 60&ndash;80% <i>without</i> QEC. '


    '<b>Honest scope:</b> the VIDRAFT figures are a small-scale <i>simulation</i> on the accuracy axis; the Zhejiang figures are <i>real hardware</i> &mdash; '


    'different methodologies, not a head-to-head. Full fault-tolerant QRAM (logical query gates) remains future work.</div>'


    '<h4 class="qh">B. Real hardware &mdash; IBM Heron r2 (select-QRAM) &nbsp;🇰🇷 VIDRAFT</h4>' + QRAM_HW +


    '<div class="meth"><b>Real-hardware QRAM measurement.</b> A 4-cell select-QRAM (2 address + 1 data qubit, word [1,0,1,1]) on IBM '


    'Heron r2 (ibm_marrakesh, job d8n0nb3nn5bs738tv4hg): <b>mean query fidelity 0.920</b> over the four addresses (256 shots each, transpiled depth ~128). '


    '<b>Honest scope:</b> this is a <i>select</i>-QRAM with <i>computational-address</i> queries (1-bit words) &mdash; simpler than the Zhejiang '


    '<i>bucket-brigade</i> with superposition queries and multiple layers, so 0.92 is <b>not</b> directly comparable to their 0.60&ndash;0.80. '


    'It is a genuine real-hardware QRAM datapoint; combined with the QEC-protection layer (section A, simulation) it covers both axes.</div>'


    '<h4 class="qh">C. Bucket-brigade vs fanout resource/noise model (analytic)</h4>' + QRAM_BB +


    '<h4 class="qh">D. Published references <span class="rep">REPORTED &mdash; hardware/theory</span></h4>' + QRAM_B)





# ---------------- Event 5: Simulation ----------------


SIM_A = table(


    ["Flag", "Method", "By", "Qubits", "Depth", "Time (s)", "Notes", "Status"],


    [["🇰🇷", "VIDRAFT stabilizer (stim, Clifford)", "VIDRAFT / stim", "100,000", "1e5", "54.7", "Clifford-only (Gottesman&ndash;Knill: poly-time, trivially classical)", VER],


     ["🇰🇷", "VIDRAFT MPS (tensor-network)", "VIDRAFT (quimb-style)", "100", "10", "0.11", "low-entanglement 1D; &#967;&le;32", VER],


     ["🇰🇷", "VIDRAFT GPU statevector (torch, in-place)", "VIDRAFT / H100 (Zen)", "33", "33", "2.3", "exact, no QPU; in-place gates raised 30&rarr;33q on one 100&nbsp;GB H100 (86&nbsp;GB peak); live demo", VER],


     ["🇰🇷", "VIDRAFT GPU statevector (4&times;H100 sharded)", "VIDRAFT / 4&times;H100 (Zen)", "34", "34", "5.3", "GHZ-class; sharded statevector, 1.7&times;10&#8310; amps; impossible on one GPU; not a record (HPC&nbsp;~48q)", VER],


     ["🇰🇷", "VIDRAFT dense statevector", "VIDRAFT (numpy, CPU)", "20", "10", "4.93", "exact; memory-bound (2&#8319;)", VER]],


    center=(0, 3, 4, 5, 7), ours_idx=())


SIM_B = table(


    ["Flag", "Work", "Reported result", "Source"],


    [["🇺🇸", "IBM + Algorithmiq 2026", "heterogeneous quantum matter (Heron); 8-mo classical-unbeaten &mdash; 'quantum advantage' claim (preprint, not peer-reviewed)", '<a href="https://newsroom.ibm.com/2026-07-30-ibm-and-algorithmiq-demonstrate-quantum-advantage">IBM 2026</a>'],


     ["🇬🇧", "Tindall et al. 2024", "TN sim of IBM Eagle kicked-Ising (127 qubits)", '<a href="https://journals.aps.org/prxquantum/abstract/10.1103/PRXQuantum.5.010308">PRX Quantum 2024</a>'],


     ["🇨🇳", "Pan &amp; Zhang 2022", "classical TN spoofing of Sycamore supremacy", '<a href="https://journals.aps.org/prl/abstract/10.1103/PhysRevLett.129.090502">PRL 2022</a>'],


     ["🇺🇸", "Google Sycamore 2019", "quantum supremacy claim (53 qubits)", '<a href="https://www.nature.com/articles/s41586-019-1666-5">Nature 2019</a>']],


    center=(0,))


SIM_HTML = page(


    '<h3 class="qh">&#9316; Quantum-Inspired / Classical Simulation</h3>'


    '<p class="muted">How large a quantum circuit a classical method can handle. Qubits simulated + wall time. '


    'Dense statevector is exact but memory-bound (~2&#8319;); tensor networks reach far more qubits on low-entanglement circuits. '


    '&#10003; VERIFIED = run on this benchmark.</p>'


    '<h4 class="qh">A. Verified runs</h4>' + SIM_A +


    '<h4 class="qh">B. Published references <span class="rep">REPORTED &mdash; larger-scale records</span></h4>' + SIM_B)





# ---------------- Event 6: Quantum Cryptanalysis ----------------


CRYPTO_A = table(


    ["Flag", "Cipher structure", "Quantum attack", "Speedup", "Verified (simulation)", "Status"],


    [["🇰🇷", "Even-Mansour block cipher", "Simon (period finding)", "exp &rarr; poly", "key recovery up to n=8 (24 qubits)", VER],


     ["🇰🇷", "SPN block cipher (key recovery)", "Grover (amplitude amp.)", "quadratic &#8730;", "key up to n=8 (&#8730;256 = 13 iters)", VER],


     ["🇰🇷", "CBC-MAC (tag forgery)", "Simon (period finding)", "exp &rarr; poly", "forgery period up to n=6", VER],


     ["🇰🇷", "Linear encoding / keystream mask", "Bernstein-Vazirani", "n queries &rarr; 1", "secret extract up to n=16", VER],


     ["🇰🇷", "Feistel (DES structure) &mdash; 3 / 4 / 5 / 6-round", "Simon &middot; Grover-meets-Simon", "exp &rarr; poly", "3R full &middot; 4&ndash;6R key-recovery", VER]],


    center=(0, 3, 4, 5), ours_idx=(0, 1, 2, 3, 4))


CRYPTO_B = table(


    ["Flag", "Work", "Reported result", "Source"],


    [["🌐", "Simon 1994", "quantum period-finding &mdash; exponential speedup (the engine of these attacks)", '<a href="https://epubs.siam.org/doi/10.1137/S0097539796298637">SIAM J. Comput.</a>'],


     ["🌐", "Grover 1996", "quantum unstructured search &mdash; quadratic speedup (symmetric key search)", '<a href="https://arxiv.org/abs/quant-ph/9605043">STOC 1996</a>'],


     ["🇯🇵", "Kuwakado &amp; Morii 2010 / 2012", "Simon distinguishes 3-round Feistel; key recovery on Even-Mansour", '<a href="https://ieeexplore.ieee.org/document/6400943">IEEE ISIT</a>'],


     ["🇫🇷", "Kaplan, Leurent, Leverrier, Naya-Plasencia, Schrottenloher 2016", "Simon breaks CBC-MAC, PMAC, GMAC, GCM, OCB; quantum slide attacks", '<a href="https://arxiv.org/abs/1602.05973">CRYPTO 2016</a>'],


     ["🇳🇱", "Santoli &amp; Schaffner 2017", "Simon-based existential forgery of MACs (CBC-MAC and more)", '<a href="https://arxiv.org/abs/1602.07211">QIC 2017</a>'],


     ["🇩🇪", "Leander &amp; May 2017", "&ldquo;Grover meets Simon&rdquo; &mdash; key recovery on the FX / whitened-key construction", '<a href="https://eprint.iacr.org/2017/427">ASIACRYPT 2017</a>'],


     ["🇫🇷", "Bonnetain, Naya-Plasencia, Schrottenloher 2019", "offline Simon &mdash; quantum attacks <i>without</i> superposition queries (Q1 model)", '<a href="https://arxiv.org/abs/2002.12439">ASIACRYPT 2019</a>'],


     ["🇫🇷", "Bonnetain, Schrottenloher, Sibleyras 2022", "beyond quadratic speedups in quantum attacks on symmetric schemes", '<a href="https://eprint.iacr.org/2021/1348">EUROCRYPT 2022</a>'],


     ["🇨🇭", "Grassl, Langenberg, Roetteler, Steinwandt 2016", "Grover key search for AES: ~6681 logical qubits (AES-256)", '<a href="https://arxiv.org/abs/1512.04965">PQCrypto 2016</a>'],


     ["🇺🇸", "Jaques, Naehrig, Roetteler, Virdia 2020", "Grover oracles for AES / LowMC; lower NIST cost estimates + Q# code", '<a href="https://eprint.iacr.org/2019/1146">EUROCRYPT 2020</a>'],


     ["🌐", "Simon &mdash; Even-Mansour on quantum hardware 2026", "genuine break on IBM at block N=3,4 (N=5 = circuit-synthesis wall)", '<a href="https://arxiv.org/abs/2604.25509">arXiv 2604.25509</a>'],


     ["🇮🇳", "Quantum cryptanalysis of symmetric ciphers &mdash; review 2022", "survey of Simon / Grover / offline-Simon attacks across primitives", '<a href="https://doi.org/10.1016/j.compeleceng.2022.108122">Comput. Electr. Eng.</a>']],


    center=(0,))


CRYPTO_HTML = page(


    '<h3 class="qh">&#9318; Quantum Cryptanalysis &mdash; Symmetric Ciphers &nbsp;🇰🇷 VIDRAFT QuantumOS</h3>'


    '<p class="muted">Genuine (un-compiled) quantum algorithms breaking symmetric-cipher <b>constructions</b>, run as high-performance simulation. '


    'While real quantum hardware for these attacks is stuck at n=4 (Track B, 2026), QuantumOS covers all five symmetric-crypto structures &mdash; '


    'Even-Mansour, SPN, MAC, and Feistel. &#10003; VERIFIED = the genuine attack recovers the secret on this engine.</p>'


    '<h4 class="qh">A. Cipher structures broken (verified in simulation) &nbsp;🇰🇷</h4>' + CRYPTO_A +


    '<div class="meth"><b>Feistel round-depth (DES family).</b> The Feistel entry deepens genuinely: <b>3-round</b> is a direct Simon period-recovery; '


    '<b>4-, 5- and 6-round</b> use <b>Grover-meets-Simon</b> &mdash; guess the last one/two/three round keys, peel them off, and the reduced 3-round '


    'Simon period survives <i>only</i> for the correct guess (verified: the true key is uniquely selected; wrong keys destroy the period). Verified genuine '


    'at block 6&ndash;8 (21&ndash;29 qubits). Scope: the quantum Simon test is fully simulated; the outer key search&#39;s &radic; speedup is Grover (coherent '


    'nesting needs parallel Simon copies, beyond statevector), so it is stated as the theoretical outer loop. Still 3&ndash;6 rounds, <b>not</b> 16-round DES.</div>'


    '<div class="meth"><b>Real hardware &mdash; IBM Heron &nbsp;🇰🇷.</b> The Even-Mansour Simon attack was also run on a <b>real IBM quantum processor</b> '


    '(ibm_fez, Heron 156-qubit; n=3; 8192 shots; job d94i5rkql68s73c9imp0). The genuine circuit <b>recovers the secret key</b> (period argmax = k&#8321;), '


    'with a k&#8321;&perp; signal fraction of <b>0.553</b> vs the 0.50 noise floor &mdash; a bias of <b>&asymp;9.6&sigma;</b> (statistically real, not luck). '


    'This matches the 2026 real-hardware SOTA scale (Even-Mansour at n=3,4). Adding <b>error mitigation</b> (dynamical decoupling XY4 + Pauli/measurement '


    'twirling; job d94jcb5gc6cc73ff6e80) sharpens the signal to <b>0.657</b> (bias &asymp;<b>28&sigma;</b>) &mdash; a clean, genuine improvement. '


    'At <b>n=4</b>, the naive single-period metric is below threshold, but that is the wrong post-processing: <b>standard Simon linear-algebra recovery</b> '


    '(GF(2) null-space of the highest-count independent measured outcomes) recovers the exact key in <b>two independent jobs</b> '


    '(8192 &amp; 16384 shots; d94ju2fu&hellip;, d94k0pkq&hellip;) &mdash; <b>matching the 2026 real-hardware SOTA scale (n=3,4)</b>. '


    '<b>Scope:</b> this is <b>error mitigation, not error correction (QEC)</b> &mdash; the attack runs on <i>physical</i> qubits '


    'with no logical encoding (application-circuit QEC is not feasible on today&#39;s NISQ hardware). A genuine cryptanalysis-attack key recovery on a real QPU.</div>'


    '<div class="meth"><b>N=5 through N=10 &mdash; extending the hardware frontier &nbsp;🚩🇰🇷.</b> The published hardware record stops at <b>N=4</b> '


    '(arXiv:2604.25509; its N=5 was blocked by a classical circuit-synthesis limit). Using proprietary QuantumOS methods (full details reserved for a '


    '<b>forthcoming paper</b>), VIDRAFT recovered the Even-Mansour secret key on a real IBM QPU at block sizes <b>N=5 through N=10</b> &mdash; to our '


    'knowledge the largest genuine Even-Mansour key recovery on real quantum hardware. Results are <b>reproducibly verified</b> &mdash; measured true-key ranks (ibm_kingston): n5=1, n6=6, n7=3, n8=9, n9=15, n10=63/1023, each recovered via a small quantum-ranked shortlist + classical verification, with an independent control key at every size. <b>Honest scope:</b> '


    'this is a <b>proof-of-concept at reduced sizes</b> (not a break of real AES-256 or RSA-2048); it uses error mitigation (<b>not</b> QEC); and '


    '&mdash; importantly &mdash; on today&#39;s noisy hardware the effective search reduction tracks the <b>classical birthday bound (~2^(n/2))</b>, so '


    'this is an <b>experimental frontier demonstration, not a quantum speedup</b> over classical cryptanalysis. Formal record status pending peer review.</div>'


    '<div class="meth"><b>Feistel (DES family) &mdash; real hardware &nbsp;🇰🇷.</b> Beyond Even-Mansour, the 3-round Feistel construction was also recovered on a real IBM QPU (ibm_kingston) at block sizes <b>6 and 8</b> &mdash; both a target key and an independent control key, clean rank-1 recovery at both sizes. A second genuine quantum-hard structure demonstrated on real hardware (still 3-round, <b>not</b> 16-round DES).</div>'


    '<p style="margin:12px 0 4px">'


    '<a href="https://vidraft-quantumos.hf.space/crypto"><img src="https://img.shields.io/badge/%E2%9A%9B%EF%B8%8F%20Live%20Demo-QuantumOS-22d3ee" alt="Live Demo"></a>&nbsp;'


    '<a href="https://vidraft-quantumos.hf.space"><img src="https://img.shields.io/badge/%F0%9F%96%A5%EF%B8%8F%20QuantumOS-Console-7c6cff" alt="QuantumOS Console"></a></p>'


    '<div class="meth"><b>Honest scope.</b> These are genuine quantum algorithms (Simon / Grover / Bernstein-Vazirani), verified in GPU/CPU '


    'simulation (qiskit + an independent JavaScript engine, Node-checked). Simon-based attacks assume the quantum-query (Q2) oracle model. '


    'The Feistel entry is a <b>3-round</b> Feistel &mdash; the design family DES belongs to &mdash; <b>not</b> 16-round DES, and this is <b>not</b> a break of '


    'real AES-256 or RSA-2048. Sizes are reduced (browser-live to block 8; S4-verified to block 12); classical projections to real sizes are estimates. '


    'No claim of quantum advantage over deployed cryptography is made.</div>'


    '<p style="margin:16px 0 4px;text-align:center"><img src="vidraft.png" alt="VIDRAFT written with 156 qubits" style="max-width:100%;border-radius:10px"></p>'


    '<p class="muted" style="text-align:center;font-size:12px">A 156-qubit state-preparation circuit (X + measure) on ibm_kingston, arranged to spell <b>VIDRAFT</b> &mdash; each dot is one real qubit. Logical banner layout, not physical chip geometry.</p>'


    '<h4 class="qh">B. The quantum-cryptanalysis landscape <span class="rep">REPORTED &mdash; theory / hardware</span></h4>'


    '<p class="muted">The field is largely <b>theory</b> (attacks proven on paper) plus a single 2026 <b>hardware</b> demonstration at block n=4. VIDRAFT&#39;s '


    'contribution here is a genuine, <b>multi-structure simulation platform</b> spanning all five symmetric-crypto structures &mdash; broader in breadth, verified and '


    'interactive, at sizes real hardware cannot yet reach.</p>' + CRYPTO_B)





FOOTER = ('<p class="muted">FINAL-Bench hosts this benchmark; all methods &mdash; including those submitted by VIDRAFT (🇰🇷) &mdash; '


          'are evaluated under identical public protocols and shown with the same confidence intervals as every other entry. '


          'Track B numbers are quoted from their sources (codes, noise models, and hardware differ) and are not directly comparable. '


          'No quantum-advantage claims are made. Real-hardware QEC (① section B) uses a repetition code with offline majority-vote &mdash; '


          'not surface-code below-threshold, not fault-tolerant QEC. Cumulative ~2.4M IBM QPU shots; a methods paper is in preparation. '


          'VIDRAFT entry reference: vidraft-quantumos.hf.space.</p>')





MEDALS_HTML = page(


    '<h3 class="qh">&#127941; Participating groups by country</h3>'


    '<p class="muted">Who appears across the five events (Track A measured here + Track B published). A neutral participation map &mdash; not a ranking of nations.</p>' +


    table(["Flag", "Country", "Groups / methods featured"],


          [["🇺🇸", "United States", "Google (Willow, AlphaQubit, Tesseract, stim, Sycamore), IBM, AWS (Ocelot), QuEra, Quantinuum, Fusion Blossom, Infleqtion"],


           ["🇬🇧", "United Kingdom", "O. Higgott (PyMatching, BeliefMatching), Roffe (ldpc / BP+OSD), Riverlane (LCD, Ambiguity Clustering)"],


           ["🇨🇳", "China", "USTC (Zuchongzhi 3.2), Zhejiang Univ (experimental QRAM), Pan &amp; Zhang (TN spoofing)"],


           ["🇰🇷", "Korea", "VIDRAFT (QEC-AI decoder, IBM-hardware repetition QEC, QEC-protected QRAM, VQE, simulation)"],


           ["🇳🇱", "Netherlands", "QuTech / Delft (NN decoder)"],


           ["🇯🇵", "Japan", "Fujitsu (Ising-machine decoder, Digital Annealer)"],


           ["🇫🇷", "France", "Alice &amp; Bob (cat qubits)"],


           ["🇨🇦", "Canada", "Xanadu (photonic GKP), D-Wave (annealer)"],


           ["🇨🇭", "Switzerland", "IBM Zurich (Kandala VQE)"],


           ["🇮🇳", "India", "QpiAI (real-time decoder)"],


           ["🇩🇪", "Germany", "Munich Quantum Toolkit (MQT QECC)"]],


          center=(0,)))





ABOUT_HTML = page(


    '<h3 class="qh">&#8505; About &amp; Cite</h3>'


    '<p class="muted">FINAL-Bench Quantum is an open, neutral benchmark suite for quantum-computing methods. '


    'Track A = methods measured here under one fixed public protocol (with 95% confidence intervals); Track B = published results quoted from their sources.</p>'


    '<h4 class="qh">Reproducibility</h4>'


    '<p class="muted">Each event states its exact configuration (code, distance, rounds, noise model, shot count, seed). '


    'The frozen QEC test set (rotated surface code d=5, p=0.005, 20k shots) is published for independent evaluation. Submit your own method via the Submit tab.</p>'


    '<h4 class="qh">Honesty boundaries</h4>'


    '<p class="muted">No quantum-advantage claims. Real-hardware QEC uses a repetition code with offline majority-vote (not surface-code below-threshold, not fault-tolerant). '


    'QRAM accuracy figures are simulation. Track B numbers are not directly comparable (different codes, noise models, hardware).</p>'


    '<h4 class="qh">Citation</h4>'


    '<div class="meth">A methods paper is in preparation. Provisional BibTeX:<br>'


    '<code>@misc{finalbench_quantum_2026, title={FINAL-Bench Quantum: an open benchmark suite for quantum-computing methods}, '


    'author={FINAL-Bench}, year={2026}, note={huggingface.co/spaces/FINAL-Bench/quantum-bench-leaderboard}}</code></div>')





# ---------------- Submit handler ----------------


_PLACEHOLDER = ("example.com", "example.org", "test@", "testuser", "test-user",

                "your-", "yourname", "username", "foo@", "bar@", "asdf")



def _is_placeholder(*vals):

    joined = " ".join((v or "").lower() for v in vals)

    return any(p in joined for p in _PLACEHOLDER)



def submit(event, team, country, name, github, hf, email, notes, results, repro, file):

    if not (results and results.strip()):

        return ("Required: self-reported results - metric values plus the protocol used. "

                "Example (QEC): LER 0.0089 @ p=0.005 / 0.0621 @ p=0.01 / d=5 / 40k shots / rotated surface code (Stim)")

    if not (repro and repro.strip()):

        return ("Required: how to reproduce - a public code URL or the exact command to run your method. "

                "Every entry is re-run on the frozen test set before listing, so we need something runnable. "

                "Example: https://github.com/you/decoder then python run.py --d 5 --p 0.01 --shots 40000")

    if _is_placeholder(email, github, hf, team, name):

        return ("Placeholder/test values detected (example.com, testuser, ...). "

                "Please submit real contact details and a real repository.")


    if not (name and name.strip()) or not (email and email.strip()) or not ((github and github.strip()) or (hf and hf.strip())):


        return "❌ Required: method/decoder name, email, and at least one link (GitHub or Hugging Face)."


    rec = {"event": event, "team": team, "country": country, "name": name, "github": github,


           "hf": hf, "email": email, "notes": notes, "results": results, "repro": repro,

           "schema_version": 2, "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S")}


    stamp = time.strftime("%Y%m%d_%H%M%S")


    safe = "".join(c for c in (name or "entry") if c.isalnum() or c in "-_")[:30]


    base = "submissions/%s_%s" % (stamp, safe)


    try:


        api.upload_file(path_or_fileobj=json.dumps(rec, ensure_ascii=False, indent=1).encode(),


                        path_in_repo=base + ".json", repo_id=SUB_DS, repo_type="dataset")


        if file is not None:


            fp = file if isinstance(file, str) else getattr(file, "name", None)


            if fp:


                api.upload_file(path_or_fileobj=fp, path_in_repo=base + "_" + os.path.basename(fp),


                                repo_id=SUB_DS, repo_type="dataset")


        return ("✅ Submission received and stored privately for manual review. It will be reproduced under the "


                "event's fixed protocol; you will be emailed about leaderboard inclusion. Thank you!")


    except Exception as e:


        return "⚠️ Could not store submission: " + str(e)[:200]





with gr.Blocks(title="FINAL-Bench Quantum", theme=gr.themes.Soft()) as demo:


    gr.Markdown("# FINAL-Bench Quantum &nbsp;<span style='font-size:14px;color:#2f6fed'>Quantum Olympics</span>\n"


                "An open benchmark suite for quantum-computing methods — five events, one fair yardstick. "


                "Each entry is labeled by origin (country flag + author/group); add your own via the Submit tab.\n\n"


                "[![Read the article](https://img.shields.io/badge/%F0%9F%93%96%20Read%20the%20Article-Hugging%20Face%20Blog-FFD21E?logoColor=black)]"


                "(https://huggingface.co/blog/FINAL-Bench/quantum-leaderboard)")


    with gr.Tab("① QEC Decoder"):


        gr.HTML(QEC_HTML)


    with gr.Tab("② Optimization"):


        gr.HTML(OPT_HTML)


    with gr.Tab("③ VQE"):


        gr.HTML(VQE_HTML)


    with gr.Tab("④ QRAM"):


        gr.HTML(QRAM_HTML)


    with gr.Tab("⑤ Simulation"):


        gr.HTML(SIM_HTML)


    with gr.Tab("⑥ Quantum Cryptanalysis"):


        gr.HTML(CRYPTO_HTML)


    with gr.Tab("📈 Charts"):


        gr.Markdown("Measured on this benchmark (rotated surface code, d=5, Stim, 20k shots). "


                    "\\*The neural-ensemble entry's latency includes computing its base-decoder features (≈ BP+OSD time); "


                    "its NN forward pass itself adds only ~µs.")


        with gr.Row():


            gr.Image(value="chart_threshold.png", label="LER vs physical error rate", show_label=True, height=300)


            gr.Image(value="chart_distance.png", label="LER vs code distance", show_label=True, height=300)


        gr.Image(value="chart_latency.png", label="Latency vs accuracy (log x)", show_label=True, height=320)


    with gr.Tab("🏅 Medals"):


        gr.HTML(MEDALS_HTML)


    with gr.Tab("ℹ️ About"):


        gr.HTML(ABOUT_HTML)


    with gr.Tab("📤 Submit"):


        gr.Markdown("Submit a method for **manual review**. Submissions are stored privately, reproduced under the "


                    "event's fixed protocol, and the submitter is emailed about leaderboard inclusion. Fields marked * are required.")


        event = gr.Dropdown(["① QEC Decoder", "② Optimization", "③ VQE", "④ QRAM", "⑤ Simulation", "⑥ Quantum Cryptanalysis", "Other"],


                            label="Event", value="① QEC Decoder")


        with gr.Row():


            team = gr.Textbox(label="Team / Author")


            country = gr.Textbox(label="Country (for flag)")


        name = gr.Textbox(label="Method / decoder name *")


        with gr.Row():


            github = gr.Textbox(label="GitHub URL")


            hf = gr.Textbox(label="Hugging Face URL")


        email = gr.Textbox(label="Email *")


        notes = gr.Textbox(label="Method / notes", lines=3)


        results = gr.Textbox(label="Self-reported results * (metrics + protocol)", lines=2,

                             placeholder="QEC example: LER 0.0089 @ p=0.005 / 0.0621 @ p=0.01 / d=5 / 40k shots / rotated surface code (Stim)")

        repro = gr.Textbox(label="How to reproduce * (public code URL or exact command)", lines=2,

                           placeholder="https://github.com/you/decoder  then  python run.py --d 5 --p 0.01 --shots 40000")

        file = gr.File(label="Results or code file (recommended)")


        btn = gr.Button("Submit", variant="primary")


        out = gr.Markdown()


        btn.click(submit, [event, team, country, name, github, hf, email, notes, results, repro, file], out)


    gr.HTML(page(FOOTER))





if __name__ == "__main__":


    demo.launch()





