"""
Real molecular docking using Vina command-line binary.
Vina is compiled from source during Docker build.
Uses subprocess to run vina, parses output for ΔG and RMSD.
"""

import os
import tempfile
import subprocess
import time
import re
import logging
from typing import Dict, Any, Optional, List
import requests

logger = logging.getLogger(__name__)

# Check if vina binary is available
VINA_BIN = "/usr/local/bin/vina"
VINA_AVAILABLE = os.path.isfile(VINA_BIN) and os.access(VINA_BIN, os.X_OK)

if VINA_AVAILABLE:
    logger.info("Vina binary found at /usr/local/bin/vina")
else:
    logger.warning("Vina binary not found")

from rdkit import Chem
from rdkit.Chem import AllChem


def download_pdb(pdb_id: str) -> str:
    """Download PDB file from RCSB."""
    url = f"https://files.rcsb.org/download/{pdb_id.upper()}.pdb"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text


def prepare_receptor(pdb_text: str, output_path: str) -> str:
    """Prepare receptor PDBQT from PDB using OpenBabel."""
    temp_pdb = output_path.replace(".pdbqt", ".pdb")
    lines = pdb_text.split("\n")
    protein_lines = [l for l in lines if not l.startswith("HETATM")]
    with open(temp_pdb, "w") as f:
        f.write("\n".join(protein_lines))

    try:
        subprocess.run(
            ["obabel", temp_pdb, "-O", output_path, "-xr"],
            capture_output=True, text=True, timeout=30
        )
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return output_path
    except Exception as e:
        logger.warning(f"OpenBabel failed: {e}")

    # Fallback: PDB as PDBQT (vina can read PDB)
    with open(output_path, "w") as f:
        f.write("\n".join(protein_lines))
    return output_path


def prepare_ligand(smiles: str, output_path: str) -> str:
    """Prepare ligand PDBQT from SMILES using RDKit + Meeko."""
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid SMILES: {smiles}")

    mol = Chem.AddHs(mol)
    params = AllChem.ETKDGv3()
    params.randomSeed = 42
    AllChem.EmbedMolecule(mol, params)
    AllChem.MMFFOptimizeMolecule(mol, maxIters=500)

    try:
        from meeko import MoleculePreparation
        preparator = MoleculePreparation()
        pdbqt_string = preparator.prepare(mol)[0]
        with open(output_path, "w") as f:
            f.write(pdbqt_string)
        return output_path
    except Exception as e:
        logger.warning(f"Meeko failed: {e}, using OpenBabel")

    mol_path = output_path.replace(".pdbqt", ".mol")
    Chem.MolToMolFile(mol, mol_path)
    subprocess.run(["obabel", mol_path, "-O", output_path], capture_output=True, timeout=30)
    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
        return output_path

    pdb_path = output_path.replace(".pdbqt", ".pdb")
    Chem.MolToPDBFile(mol, pdb_path)
    with open(output_path, "w") as f:
        f.write(open(pdb_path).read())
    return output_path


def parse_vina_output(output: str) -> List[Dict]:
    """Parse vina output to extract poses and energies."""
    poses = []
    lines = output.split("\n")
    for line in lines:
        line = line.strip()
        # Vina output format: "   1     -7.3      0.000      0.000"
        if re.match(r'^\d+\s+[-\d.]+\s+[-\d.]+\s+[-\d.]+', line):
            parts = line.split()
            try:
                poses.append({
                    "rank": int(parts[0]),
                    "affinity_kcal_mol": round(float(parts[1]), 2),
                    "rmsd_lb": round(float(parts[2]), 2),
                    "rmsd_ub": round(float(parts[3]), 2),
                })
            except (ValueError, IndexError):
                pass
    return poses


def run_vina_docking(
    pdb_id: str,
    smiles: str,
    drug_name: str = "",
    target_name: str = "",
    box_center: Optional[List[float]] = None,
    box_size: List[float] = [20.0, 20.0, 20.0],
    exhaustiveness: int = 8,
    num_poses: int = 10,
) -> Dict[str, Any]:
    """
    Run real AutoDock Vina molecular docking via command-line binary.
    """
    start_time = time.time()

    if not VINA_AVAILABLE:
        from api.docking import run_docking_analysis
        logger.warning("Vina not available, using RDKit fallback")
        result = run_docking_analysis(smiles, drug_name, target_name)
        result["engine"] = "rdkit-fallback"
        result["vina_available"] = False
        return result

    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. Download PDB
        logger.info(f"Downloading PDB {pdb_id}...")
        pdb_text = download_pdb(pdb_id)

        # 2. Prepare receptor
        receptor_path = os.path.join(tmpdir, "receptor.pdbqt")
        logger.info("Preparing receptor...")
        prepare_receptor(pdb_text, receptor_path)

        # 3. Prepare ligand
        ligand_path = os.path.join(tmpdir, "ligand.pdbqt")
        logger.info(f"Preparing ligand from SMILES: {smiles[:50]}...")
        prepare_ligand(smiles, ligand_path)

        # 4. Determine box center (center of mass)
        if box_center is None:
            box_center = [0.0, 0.0, 0.0]
            atom_count = 0
            for line in pdb_text.split("\n"):
                if line.startswith("ATOM"):
                    try:
                        x = float(line[30:38])
                        y = float(line[38:46])
                        z = float(line[46:54])
                        box_center[0] += x
                        box_center[1] += y
                        box_center[2] += z
                        atom_count += 1
                    except (ValueError, IndexError):
                        pass
            if atom_count > 0:
                box_center = [c / atom_count for c in box_center]

        logger.info(f"Box center: {box_center}, size: {box_size}")

        # 5. Run vina via subprocess
        output_pdbqt = os.path.join(tmpdir, "out.pdbqt")

        cmd = [
            VINA_BIN,
            "--receptor", receptor_path,
            "--ligand", ligand_path,
            "--center_x", str(round(box_center[0], 3)),
            "--center_y", str(round(box_center[1], 3)),
            "--center_z", str(round(box_center[2], 3)),
            "--size_x", str(box_size[0]),
            "--size_y", str(box_size[1]),
            "--size_z", str(box_size[2]),
            "--exhaustiveness", str(exhaustiveness),
            "--num_modes", str(num_poses),
            "--out", output_pdbqt,
        ]

        logger.info(f"Running vina...")
        vina_stderr = ""
        vina_returncode = 0
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120
            )
            vina_output = result.stdout + "\n" + result.stderr
            vina_stderr = result.stderr
            vina_returncode = result.returncode
        except subprocess.TimeoutExpired:
            raise RuntimeError("Vina timed out (120s)")
        except Exception as e:
            raise RuntimeError(f"Vina failed: {e}")

        # 6. Parse results from stdout
        poses = parse_vina_output(vina_output)

        elapsed = time.time() - start_time
        best_affinity = poses[0]["affinity_kcal_mol"] if poses else 0.0

        # Get RDKit descriptors too
        from api.docking import run_docking_analysis
        rdkit_result = run_docking_analysis(smiles, drug_name, target_name)

        logger.info(f"Vina done: best ΔG={best_affinity}, {len(poses)} poses, {elapsed:.1f}s")

        return {
            "engine": "autodock-vina",
            "vina_available": True,
            "drug": rdkit_result["drug"],
            "target": target_name,
            "pdb_id": pdb_id,
            "descriptors": rdkit_result["descriptors"],
            "vina_results": {
                "best_affinity_kcal_mol": best_affinity,
                "num_poses": len(poses),
                "poses": poses,
                "box_center": [round(c, 2) for c in box_center],
                "box_size": box_size,
                "exhaustiveness": exhaustiveness,
                "elapsed_seconds": round(elapsed, 1),
            },
            "drug_likeness": rdkit_result["drug_likeness"],
            "lipinski": rdkit_result["lipinski"],
            "alerts": rdkit_result["alerts"],
        }
