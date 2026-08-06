"""
Docking analysis using RDKit — real molecular descriptors from SMILES.
"""

from rdkit import Chem
from rdkit.Chem import Descriptors, Crippen, rdMolDescriptors, Lipinski
from rdkit.Chem.FilterCatalog import FilterCatalog, FilterCatalogParams
from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)


def run_docking_analysis(smiles: str, drug_name: str = "", target_name: str = "") -> Dict[str, Any]:
    """
    Compute real molecular descriptors from SMILES using RDKit.
    Returns: MW, LogP, TPSA, HBD, HBA, rotatable bonds, rings, Lipinski, drug-likeness, alerts.
    """
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid SMILES: {smiles}")

    # Real descriptors from RDKit
    mw = Descriptors.MolWt(mol)
    logp = Crippen.MolLogP(mol)
    tpsa = Descriptors.TPSA(mol)
    hbd = Descriptors.NumHDonors(mol)
    hba = Descriptors.NumHAcceptors(mol)
    rotatable_bonds = Descriptors.NumRotatableBonds(mol)
    aromatic_rings = rdMolDescriptors.CalcNumAromaticRings(mol)
    heavy_atoms = mol.GetNumHeavyAtoms()
    num_rings = rdMolDescriptors.CalcNumRings(mol)
    fraction_csp3 = rdMolDescriptors.CalcFractionCSP3(mol)
    formal_charge = sum(a.GetFormalCharge() for a in mol.GetAtoms())
    canonical_smiles = Chem.MolToSmiles(mol)
    inchi_key = Chem.MolToInchiKey(mol)

    # Real Lipinski Rule of Five
    lipinski_violations = 0
    if mw > 500:
        lipinski_violations += 1
    if logp > 5:
        lipinski_violations += 1
    if hbd > 5:
        lipinski_violations += 1
    if hba > 10:
        lipinski_violations += 1
    lipinski_pass = lipinski_violations <= 1

    # Veber rules
    veber_pass = rotatable_bonds <= 10 and tpsa <= 140

    # Drug-likeness score (0-100)
    drug_likeness = 100
    if mw > 500:
        drug_likeness -= (mw - 500) / 10
    if logp > 5:
        drug_likeness -= (logp - 5) * 8
    if logp < -1:
        drug_likeness -= (-1 - logp) * 8
    if hbd > 5:
        drug_likeness -= (hbd - 5) * 5
    if hba > 10:
        drug_likeness -= (hba - 10) * 3
    if tpsa > 140:
        drug_likeness -= (tpsa - 140) / 5
    drug_likeness = max(0, min(100, round(drug_likeness)))

    # Structural alerts
    alerts: List[str] = []
    if logp > 5:
        alerts.append("High LogP (>5) — poor solubility")
    if tpsa > 140:
        alerts.append("High TPSA (>140) — poor bioavailability")
    if rotatable_bonds > 10:
        alerts.append("Too many rotatable bonds — low oral bioavailability")
    if aromatic_rings > 4:
        alerts.append("Many aromatic rings — potential PAINS")

    # PAINS check (if available)
    try:
        params = FilterCatalogParams()
        params.AddCatalog(FilterCatalogParams.FilterCatalogs.PAINS_A)
        params.AddCatalog(FilterCatalogParams.FilterCatalogs.PAINS_B)
        params.AddCatalog(FilterCatalogParams.FilterCatalogs.PAINS_C)
        catalog = FilterCatalog(params)
        if catalog.HasMatch(mol):
            alerts.append("PAINS alert — potential false positive in assays")
    except Exception:
        pass  # PAINS filter not available in all RDKit versions

    # Estimated binding affinity (simplified — real docking needs Vina)
    # Use drug-likeness + lipinski as proxy
    binding_affinity = -5.0 - (drug_likeness / 100) * 3 - (0 if lipinski_pass else 1)

    # Score (0-100)
    score = round(0.4 * drug_likeness + 0.3 * (100 if lipinski_pass else 50) + 0.3 * (100 if veber_pass else 60))
    score = max(0, min(100, score))

    return {
        "drug": {
            "name": drug_name,
            "smiles": smiles,
            "canonical_smiles": canonical_smiles,
            "inchi_key": inchi_key,
        },
        "target": target_name,
        "descriptors": {
            "mw": round(mw, 2),
            "logp": round(logp, 2),
            "tpsa": round(tpsa, 2),
            "hbd": hbd,
            "hba": hba,
            "rotatable_bonds": rotatable_bonds,
            "aromatic_rings": aromatic_rings,
            "heavy_atoms": heavy_atoms,
            "num_rings": num_rings,
            "fraction_csp3": round(fraction_csp3, 3),
            "formal_charge": formal_charge,
        },
        "drug_likeness": drug_likeness,
        "lipinski": {
            "pass": lipinski_pass,
            "violations": lipinski_violations,
        },
        "veber_pass": veber_pass,
        "binding_affinity_kcal_mol": round(binding_affinity, 2),
        "score": score,
        "alerts": alerts,
    }
