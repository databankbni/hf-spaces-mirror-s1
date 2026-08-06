"""
VetInSilico Backend — FastAPI server for real bioinformatics computations.
Deployed on HuggingFace Spaces (free CPU tier, 16GB RAM).

Endpoints:
  POST /api/docking   — RDKit molecular descriptors + Lipinski + drug-likeness
  POST /api/admet     — RDKit ADMET properties from SMILES
  POST /api/alignment — BioPython pairwise alignment (Needleman-Wunsch / Smith-Waterman)
  POST /api/primer    — Primer3-py primer design
  GET  /api/health    — Health check
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import logging

from api.docking import run_docking_analysis
from api.admet import predict_admet_rdkit

# Optional imports (may not be available on all environments)
try:
    from api.alignment import align_sequences
    ALIGNMENT_AVAILABLE = True
except ImportError:
    ALIGNMENT_AVAILABLE = False

try:
    from api.primer import design_primers_primer3
    PRIMER_AVAILABLE = True
except ImportError:
    PRIMER_AVAILABLE = False

try:
    from api.vina_docking import run_vina_docking, VINA_AVAILABLE
    VINA_DOCKING_AVAILABLE = True
except ImportError:
    VINA_DOCKING_AVAILABLE = False
    VINA_AVAILABLE = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="VetInSilico Backend",
    description="Real bioinformatics backend for VetInSilico Hub",
    version="1.0.0",
)

# CORS: allow GitHub Pages and localhost
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://shray77.github.io",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "*",  # HF Spaces needs this for preview
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ─── Models ──────────────────────────────────────────────────────────

class DockingRequest(BaseModel):
    smiles: str
    drug_name: Optional[str] = ""
    target_name: Optional[str] = ""


class ADMETRequest(BaseModel):
    smiles: str
    drug_name: Optional[str] = ""


class AlignmentRequest(BaseModel):
    seq_a: str
    seq_b: str
    seq_type: str = "protein"  # "protein" or "dna"
    algorithm: str = "needleman-wunsch"  # or "smith-waterman"


class PrimerRequest(BaseModel):
    sequence: str
    target_tm: float = 58.0
    min_len: int = 18
    max_len: int = 22
    min_product: int = 150
    max_product: int = 600
    num_pairs: int = 10


class VinaDockingRequest(BaseModel):
    pdb_id: str
    smiles: str
    drug_name: Optional[str] = ""
    target_name: Optional[str] = ""
    box_center: Optional[List[float]] = None
    box_size: List[float] = [20.0, 20.0, 20.0]
    exhaustiveness: int = 8
    num_poses: int = 10


# ─── Endpoints ───────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    """Health check — used by HF Spaces to verify the container is running."""
    return {"status": "ok", "service": "vet-insilico-backend", "version": "1.0.0"}


@app.get("/")
async def root():
    """Landing page for browser visitors."""
    from fastapi.responses import HTMLResponse
    return HTMLResponse("""
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>VetInSilico Backend</title>
<style>
  body{font-family:system-ui,sans-serif;background:#09090b;color:#e4e4e7;margin:0;padding:40px 20px;text-align:center}
  h1{font-size:2em;background:linear-gradient(90deg,#0d9488,#0ea5e9,#a855f7);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:.3em}
  .sub{color:#71717a;font-size:.9em;margin-bottom:2em}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:1em;max-width:800px;margin:0 auto}
  .card{background:#18181b;border:1px solid #27272a;border-radius:12px;padding:1.5em;text-align:left}
  .card h3{color:#0d9488;margin:0 0 .5em;font-size:.95em}
  .card p{color:#a1a1aa;font-size:.8em;margin:0;line-height:1.5}
  .badge{display:inline-block;background:#052e2b;color:#0d9488;padding:.2em .6em;border-radius:6px;font-size:.7em;margin-bottom:1em}
  a{color:#0ea5e9;text-decoration:none}a:hover{text-decoration:underline}
  .endpoints{margin-top:2em;text-align:left;max-width:600px;margin:2em auto 0}
  .ep{display:flex;gap:.5em;align-items:center;padding:.4em .8em;background:#18181b;border-radius:6px;margin-bottom:.3em;font-family:monospace;font-size:.8em}
  .method{color:#0d9488;font-weight:bold;min-width:50px}
  .path{color:#a1a1aa}
  .desc{color:#52525b;font-size:.75em;margin-left:auto}
</style>
</head>
<body>
  <div class="badge">🚀 Backend Online</div>
  <h1>🧬 VetInSilico Backend</h1>
  <p class="sub">Real bioinformatics: AutoDock Vina + RDKit + Meeko + OpenBabel<br>HuggingFace Spaces • Free CPU tier • Python 3.11</p>
  <div class="grid">
    <div class="card"><h3>🔬 AutoDock Vina</h3><p>Real molecular docking: SMILES → 3D → PDBQT → Vina simulation → ΔG (kcal/mol), RMSD, poses</p></div>
    <div class="card"><h3>💊 RDKit Descriptors</h3><p>Real molecular properties from SMILES: MW, LogP, TPSA, Lipinski, Veber, PAINS alerts</p></div>
    <div class="card"><h3>📊 ADMET Prediction</h3><p>Oral bioavailability, BBB, Caco-2, hERG, AMES, hepatotoxicity, CYP3A4, bioaccumulation</p></div>
    <div class="card"><h3>🔗 Frontend</h3><p>GitHub Pages (Next.js static)<br><a href="https://shray77.github.io/vet-insilico/">shray77.github.io/vet-insilico</a></p></div>
  </div>
  <div class="endpoints">
    <div class="ep"><span class="method">GET</span><span class="path">/api/health</span><span class="desc">Health check</span></div>
    <div class="ep"><span class="method">POST</span><span class="path">/api/vina-docking</span><span class="desc">Real Vina docking</span></div>
    <div class="ep"><span class="method">POST</span><span class="path">/api/docking</span><span class="desc">RDKit descriptors</span></div>
    <div class="ep"><span class="method">POST</span><span class="path">/api/admet</span><span class="desc">ADMET prediction</span></div>
    <div class="ep"><span class="method">POST</span><span class="path">/api/alignment</span><span class="desc">BioPython alignment</span></div>
    <div class="ep"><span class="method">POST</span><span class="path">/api/primer</span><span class="desc">Primer3 design</span></div>
  </div>
</body>
</html>
    """)


@app.post("/api/docking")
async def docking(req: DockingRequest):
    """
    Real molecular analysis using RDKit.
    Computes descriptors from SMILES, Lipinski check, drug-likeness, structural alerts.
    """
    try:
        result = run_docking_analysis(req.smiles, req.drug_name or "", req.target_name or "")
        return result
    except Exception as e:
        logger.error(f"Docking error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/admet")
async def admet(req: ADMETRequest):
    """
    Real ADMET prediction using RDKit descriptors.
    Computes: MW, LogP, TPSA, HBD, HBA, rotatable bonds, rings, fractions,
    Lipinski, Veber, Egan rules, PAINS alerts.
    """
    try:
        result = predict_admet_rdkit(req.smiles, req.drug_name or "")
        return result
    except Exception as e:
        logger.error(f"ADMET error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/alignment")
async def alignment(req: AlignmentRequest):
    """Real sequence alignment using BioPython."""
    if not ALIGNMENT_AVAILABLE:
        raise HTTPException(status_code=503, detail="BioPython not available on this server")
    try:
        result = align_sequences(req.seq_a, req.seq_b, req.seq_type, req.algorithm)
        return result
    except Exception as e:
        logger.error(f"Alignment error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/primer")
async def primer(req: PrimerRequest):
    """Real primer design using Primer3-py."""
    if not PRIMER_AVAILABLE:
        raise HTTPException(status_code=503, detail="Primer3-py not available on this server")
    try:
        result = design_primers_primer3(
            req.sequence,
            target_tm=req.target_tm,
            min_len=req.min_len,
            max_len=req.max_len,
            min_product=req.min_product,
            max_product=req.max_product,
            num_pairs=req.num_pairs,
        )
        return result
    except Exception as e:
        logger.error(f"Primer error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/vina-docking")
async def vina_docking(req: VinaDockingRequest):
    """
    Real AutoDock Vina molecular docking.
    Downloads PDB, prepares receptor+ligand, runs Vina simulation.
    Returns ΔG, RMSD, poses.
    """
    if not VINA_DOCKING_AVAILABLE:
        raise HTTPException(status_code=503, detail="Vina not available on this server")
    try:
        result = run_vina_docking(
            req.pdb_id,
            req.smiles,
            req.drug_name or "",
            req.target_name or "",
            req.box_center,
            req.box_size,
            req.exhaustiveness,
            req.num_poses,
        )
        return result
    except Exception as e:
        logger.error(f"Vina docking error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
