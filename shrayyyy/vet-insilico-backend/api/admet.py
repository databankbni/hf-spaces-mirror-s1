"""
ADMET prediction using RDKit — real physicochemical properties from SMILES.
"""

from rdkit import Chem
from rdkit.Chem import Descriptors, Crippen, rdMolDescriptors
from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)


def predict_admet_rdkit(smiles: str, drug_name: str = "") -> Dict[str, Any]:
    """
    Real ADMET prediction using RDKit descriptors.
    Computes physicochemical properties and rule-based ADMET estimates.
    """
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid SMILES: {smiles}")

    # Real descriptors
    mw = Descriptors.MolWt(mol)
    logp = Crippen.MolLogP(mol)
    tpsa = Descriptors.TPSA(mol)
    hbd = Descriptors.NumHDonors(mol)
    hba = Descriptors.NumHAcceptors(mol)
    rotatable_bonds = Descriptors.NumRotatableBonds(mol)
    aromatic_rings = rdMolDescriptors.CalcNumAromaticRings(mol)
    num_rings = rdMolDescriptors.CalcNumRings(mol)
    fraction_csp3 = rdMolDescriptors.CalcFractionCSP3(mol)
    formal_charge = sum(a.GetFormalCharge() for a in mol.GetAtoms())

    # LogS estimation (Crippen)
    try:
        from rdkit.Chem.Crippen import MolLogS
        logs = MolLogS(mol)
    except Exception:
        # Approximation: logS ≈ 0.5 - logP - 0.01*(MW-20)
        logs = 0.5 - logp - 0.01 * (mw - 20)

    # Rule-based ADMET estimates (from real descriptors)
    # Oral bioavailability (Lipinski + Veber)
    lipinski_violations = sum([
        mw > 500, logp > 5, hbd > 5, hba > 10
    ])
    oral_bioavailability = max(5, 95 - lipinski_violations * 15 - (10 if rotatable_bonds > 10 else 0) - (10 if abs(formal_charge) >= 2 else 0))

    # BBB permeability (Egan & Lauri 2002)
    bbb_score = 0
    if mw < 400:
        bbb_score += 1
    else:
        bbb_score -= (mw - 400) / 200
    if 1 <= logp <= 3:
        bbb_score += 1
    elif logp > 5:
        bbb_score -= 1
    if formal_charge != 0:
        bbb_score -= 1.5
    bbb_level = "high" if bbb_score > 0.5 else "low" if bbb_score < -0.5 else "moderate"

    # Caco-2 permeability (approximation)
    caco2 = 8 - 0.04 * tpsa + 0.5 * logp
    if formal_charge != 0:
        caco2 -= 2
    caco2 = max(0.1, caco2)

    # Plasma protein binding (correlates with LogP)
    ppb = min(99, max(5, 30 + logp * 12 + (10 if formal_charge < 0 else 0)))

    # hERG risk (basic amines + high LogP)
    herg_risk = 0
    if formal_charge > 0:
        herg_risk += 0.3
    if logp > 3:
        herg_risk += 0.25
    if logp > 5:
        herg_risk += 0.15
    herg_risk = min(0.95, herg_risk)

    # AMES risk (simplified)
    ames_risk = 0.1
    if "nitro" in smiles.lower() or "[N+](=O)[O-]" in smiles:
        ames_risk += 0.4
    if logp > 4:
        ames_risk += 0.1

    # Hepatotoxicity
    hepato_risk = 0.15
    if logp > 3:
        hepato_risk += 0.2
    if aromatic_rings > 3:
        hepato_risk += 0.15

    # CYP3A4
    cyp_substrate = 0.2 + (0.4 if logp > 2 and mw > 300 else 0) + (0.15 if formal_charge > 0 else 0)
    cyp_inhibitor = 0.1 + (0.3 if logp > 4 else 0) + (0.3 if aromatic_rings > 2 else 0)

    # Bioaccumulation
    bioaccum = 0.05 + logp * 0.15
    if logp > 5:
        bioaccum += 0.2
    bioaccum = min(0.95, bioaccum)

    # Drug-likeness
    drug_likeness = 100
    if mw > 500:
        drug_likeness -= (mw - 500) / 10
    if logp > 5:
        drug_likeness -= (logp - 5) * 8
    if logp < -1:
        drug_likeness -= (-1 - logp) * 8
    if tpsa > 140:
        drug_likeness -= (tpsa - 140) / 5
    drug_likeness = max(0, min(100, round(drug_likeness)))

    # Alerts
    alerts: List[str] = []
    if logp > 5:
        alerts.append("High LogP (>5) — poor solubility")
    if tpsa > 140:
        alerts.append("High TPSA (>140) — poor bioavailability")
    if rotatable_bonds > 10:
        alerts.append("Too many rotatable bonds — Veber violation")
    if herg_risk > 0.5:
        alerts.append("High hERG blockade risk")
    if bioaccum > 0.6:
        alerts.append("High bioaccumulation — environmental risk")

    return {
        "drug_name": drug_name,
        "smiles": smiles,
        "descriptors": {
            "mw": round(mw, 2),
            "logp": round(logp, 2),
            "tpsa": round(tpsa, 2),
            "hbd": hbd,
            "hba": hba,
            "rotatable_bonds": rotatable_bonds,
            "aromatic_rings": aromatic_rings,
            "num_rings": num_rings,
            "fraction_csp3": round(fraction_csp3, 3),
            "formal_charge": formal_charge,
            "log_s": round(float(logs), 2),
        },
        "admet": {
            "oral_bioavailability": oral_bioavailability,
            "bbb_permeability": {"score": round(float(bbb_score), 2), "level": bbb_level},
            "caco2": round(float(caco2), 2),
            "ppb": round(float(ppb), 1),
            "herg_risk": round(float(herg_risk), 2),
            "ames_risk": round(float(ames_risk), 2),
            "hepatotoxicity_risk": round(float(hepato_risk), 2),
            "cyp3a4_substrate": round(float(min(0.95, cyp_substrate)), 2),
            "cyp3a4_inhibitor": round(float(min(0.95, cyp_inhibitor)), 2),
            "bioaccumulation": round(float(bioaccum), 2),
        },
        "drug_likeness": drug_likeness,
        "alerts": alerts,
    }
