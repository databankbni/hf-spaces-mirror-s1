import importlib.util
import sqlite3
import sys
import zipfile
from pathlib import Path


def load_builder():
    path = Path(__file__).parents[1] / ".github" / "tools" / "build_gbif_names_media_v1_7.py"
    spec = importlib.util.spec_from_file_location("gbif_builder", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_base(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE plant_index(
              taxon_id TEXT PRIMARY KEY, scientific_name TEXT NOT NULL, common_name TEXT,
              functions_json TEXT, regulatory_veto INTEGER, regulatory_reason TEXT,
              confidence TEXT, powo_id TEXT, scientific_name_id TEXT, references_url TEXT
            );
            CREATE TABLE climate_envelope(taxon_id TEXT);
            CREATE TABLE soil_envelope(taxon_id TEXT);
            CREATE TABLE soil_categorical_preference(taxon_id TEXT);
            CREATE TABLE soil_indicator_preference(taxon_id TEXT);
            CREATE TABLE soil_geographic_prior(taxon_id TEXT);
            CREATE TABLE evidence(taxon_id TEXT);
            CREATE TABLE climaflora_catalog_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE build_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            """
        )
        conn.executemany(
            "INSERT INTO plant_index VALUES(?,?,?,?,?,?,?,?,?,?)",
            [
                ("A", "Alpha plantus", None, "[]", 0, None, "C", None, None, None),
                ("B", "Beta plantus", None, "[]", 0, None, "C", None, None, None),
                ("C", "Ambigua plantus", None, "[]", 0, None, "C", None, None, None),
            ],
        )
        conn.executemany(
            "INSERT INTO climaflora_catalog_metadata VALUES(?,?)",
            [("catalog_version", "1.6.0"), ("scientific_ready", "true")],
        )
        conn.executemany(
            "INSERT INTO build_metadata VALUES(?,?)",
            [("catalog_version", "1.6.0"), ("scientific_ready", "true")],
        )


def make_dwca(path: Path) -> None:
    meta = """<?xml version="1.0" encoding="UTF-8"?>
    <archive xmlns="http://rs.tdwg.org/dwc/text/">
      <core encoding="UTF-8" fieldsTerminatedBy="\\t" fieldsEnclosedBy="&quot;" ignoreHeaderLines="1" rowType="http://rs.tdwg.org/dwc/terms/Taxon">
        <files><location>taxon.txt</location></files><id index="0"/>
        <field index="1" term="http://rs.tdwg.org/dwc/terms/canonicalName"/>
        <field index="2" term="http://rs.tdwg.org/dwc/terms/scientificName"/>
        <field index="3" term="http://rs.tdwg.org/dwc/terms/kingdom"/>
        <field index="4" term="http://rs.tdwg.org/dwc/terms/taxonomicStatus"/>
        <field index="5" term="http://rs.tdwg.org/dwc/terms/datasetID"/>
      </core>
      <extension encoding="UTF-8" fieldsTerminatedBy="\\t" fieldsEnclosedBy="&quot;" ignoreHeaderLines="1" rowType="http://rs.gbif.org/terms/1.0/VernacularName">
        <files><location>vernacular.txt</location></files><coreid index="0"/>
        <field index="1" term="http://rs.tdwg.org/dwc/terms/vernacularName"/>
        <field index="2" term="http://purl.org/dc/terms/language"/>
        <field index="3" term="http://rs.gbif.org/terms/1.0/isPreferredName"/>
        <field index="4" term="http://purl.org/dc/terms/source"/>
      </extension>
      <extension encoding="UTF-8" fieldsTerminatedBy="\\t" fieldsEnclosedBy="&quot;" ignoreHeaderLines="1" rowType="http://rs.gbif.org/terms/1.0/Multimedia">
        <files><location>media.txt</location></files><coreid index="0"/>
        <field index="1" term="http://purl.org/dc/terms/identifier"/>
        <field index="2" term="http://purl.org/dc/terms/type"/>
        <field index="3" term="http://purl.org/dc/terms/format"/>
        <field index="4" term="http://purl.org/dc/terms/license"/>
        <field index="5" term="http://purl.org/dc/terms/creator"/>
        <field index="6" term="http://purl.org/dc/terms/references"/>
        <field index="7" term="http://purl.org/dc/terms/title"/>
      </extension>
    </archive>"""
    taxon = "id\tcanonical\tscientific\tkingdom\tstatus\tdataset\n" + "\n".join(
        [
            "1\tAlpha plantus\tAlpha plantus Author\tPlantae\taccepted\tds1",
            "2\tBeta plantus\tBeta plantus Author\tPlantae\taccepted\tds1",
            "3\tAmbigua plantus\tAmbigua plantus A\tPlantae\taccepted\tds1",
            "4\tAmbigua plantus\tAmbigua plantus B\tPlantae\taccepted\tds2",
            "5\tAlpha plantus\tAlpha plantus synonym\tPlantae\tsynonym\tds3",
            "6\tAlpha plantus\tAlpha animal\tAnimalia\taccepted\tds4",
        ]
    ) + "\n"
    vernacular = (
        "coreid\tname\tlanguage\tpreferred\tsource\n"
        "1\tAlpha français\tfr\ttrue\tGBIF source A\n"
        "1\tAlpha plant\ten\tfalse\tGBIF source A\n"
        "2\tBeta plant\tEnglish\ttrue\tGBIF source B\n"
        "3\tAmbiguous common\ten\ttrue\tGBIF source C\n"
    )
    media = (
        "coreid\tidentifier\ttype\tformat\tlicense\tcreator\treferences\ttitle\n"
        "1\thttps://example.org/a.jpg\tStillImage\timage/jpeg\thttps://creativecommons.org/licenses/by/4.0/\tAlice\thttps://example.org/a-credit\tAlpha image\n"
        "1\thttps://example.org/a-nc.jpg\tStillImage\timage/jpeg\thttps://creativecommons.org/licenses/by-nc/4.0/\tBob\thttps://example.org/nc\tNC image\n"
        "2\thttps://example.org/b.jpg\tStillImage\timage/jpeg\tCC0 1.0\tCarol\thttps://example.org/b-credit\tBeta image\n"
        "3\thttps://example.org/c.jpg\tStillImage\timage/jpeg\tCC0 1.0\tDan\thttps://example.org/c-credit\tAmbiguous image\n"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("meta.xml", meta)
        zf.writestr("taxon.txt", taxon)
        zf.writestr("vernacular.txt", vernacular)
        zf.writestr("media.txt", media)


def test_license_whitelist_rejects_nc_nd() -> None:
    b = load_builder()
    assert b.canonical_open_license("https://creativecommons.org/licenses/by/4.0/")[0] == "CC BY 4.0"
    assert b.canonical_open_license("https://creativecommons.org/licenses/by-sa/4.0/")[0] == "CC BY-SA 4.0"
    assert b.canonical_open_license("CC0 1.0")[0] == "CC0 1.0"
    assert b.canonical_open_license("https://creativecommons.org/licenses/by-nc/4.0/")[0] is None
    assert b.canonical_open_license("https://creativecommons.org/licenses/by-nd/4.0/")[0] is None


def test_exact_dwca_enrichment_and_ambiguous_name_guardrail(tmp_path: Path) -> None:
    b = load_builder()
    base = tmp_path / "v16.sqlite"
    archive = tmp_path / "backbone.zip"
    out = tmp_path / "v17.sqlite"
    report = tmp_path / "report.json"
    make_base(base)
    make_dwca(archive)
    result = b.build(base, archive, out, report)

    assert result["catalog_version"] == "1.7.0"
    assert result["stats"]["exact_matched_taxa"] == 2
    assert result["stats"]["ambiguous_exact_names"] == 1
    assert result["stats"]["vernacular_taxa"] == 2
    assert result["stats"]["eligible_media_taxa"] == 2
    assert result["stats"]["media_rejected_license"] == 1

    with sqlite3.connect(out) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT common_name FROM plant_index WHERE taxon_id='A'").fetchone()[0] == "Alpha français"
        assert conn.execute("SELECT common_name FROM plant_index WHERE taxon_id='B'").fetchone()[0] == "Beta plant"
        assert conn.execute("SELECT common_name FROM plant_index WHERE taxon_id='C'").fetchone()[0] is None
        assert conn.execute("SELECT COUNT(*) FROM plant_image_asset WHERE taxon_id='C'").fetchone()[0] == 0
        license_name, materialized = conn.execute(
            "SELECT license,materialized FROM plant_image_asset WHERE taxon_id='A' AND is_primary=1"
        ).fetchone()
        assert license_name == "CC BY 4.0"
        assert materialized == 0
        assert conn.execute("SELECT value FROM climaflora_catalog_metadata WHERE key='image_identification_evidence'").fetchone()[0] == "false"
