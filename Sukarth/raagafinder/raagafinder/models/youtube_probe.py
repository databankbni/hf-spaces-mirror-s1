"""The 67 fresh-YouTube recordings deliberately held out of training.

Batch 6 collected fresh YouTube recordings for the 37 CompMusic ragas that had
none -- two apiece where two could be verified, one for seven of them, 67 in
all -- in order to run a paired-by-raga source-gap control that could not
otherwise run. Saraga measured a gap of about zero against CMD and the
private solo-voice set measured -0.45, but YouTube and "the post-CMD raga set"
were very nearly the same variable, leaving the YouTube question unanswerable.
These recordings answer it: -0.272 +- 0.109 top-1 over 30 ragas.

The measurement holds only while no model has trained on them. Two scripts
depend on that -- compare_cmd_youtube.py, which uses corpus membership as its
exclusion test, and score_youtube_blend.py -- and there is no second
population of fresh YouTube audio for exactly these ragas, so training on them
ends the measurement permanently rather than temporarily.

They are listed here because nothing else marks them. They fall outside
splits_model_v2_7.json only because that file was frozen before they were
collected, and an invariant that holds because of the order two things
happened in is not enforced by anything: a routine extend_splits.py run would
absorb all 67 silently.

Absorbing them is a legitimate option, not a prohibition, but it should be a
decision rather than a side effect. The gain is small and aimed at the wrong
place -- all 37 ragas already carry 12 to 21 recordings, none is below quota,
and they are the highest-scoring CMD classes (87.7% on that slice), while
topping up already-healthy classes measured at +0.06 +- 0.10. The cost is the
only fresh-YouTube probe available for these ragas.

It happened anyway, once, by the side-effect route this file warns about.
The 2026-08-09 resplit for model_v2_8 went through make_splits, which did
not read this list, and all 67 recordings trained. The exception is bounded
rather than permanent: the probe remains valid against model_v2_4 and
model_v2_7, whose splits predate it; it is invalid against model_v2_8
specifically; and make_splits now refuses these recordings a fold, so the
next corpus build excludes them again and the probe resumes with the next
model generation. Retraining v2_8 clean was considered and declined -- the
measured gain of absorption is noise, but so is the cost to that one model,
and the rebuild would have spent a week of GPU quota to move a number by
less than its error bar. ABSORBED_SPLITS below is the record the guard
tests read.
"""

# splits files that assigned the probe folds before the guard existed, with
# the decision recorded. Nothing may be added here without a dated reason.
ABSORBED_SPLITS = {
    "splits_model_v2_8.json":
        "2026-08-09 resplit predates the make_splits guard; absorption "
        "accepted for this model generation only, see the docstring",
}

YOUTUBE_PROBE = (
    "yt_anandabhairavi_anandabhairavi_ragam_alapana_carnatic_vocal_conc",
    "yt_anandabhairavi_anandabhairavi_ragam_veena_instrumental_carnatic",
    "yt_atana_atana_ragam_alapana_carnatic_vocal_concert",
    "yt_atana_atana_ragam_violin_instrumental_carnatic",
    "yt_begada_begada_ragam_veena_instrumental_carnatic",
    "yt_behag_behag_ragam_thillana_carnatic_vocal_concert",
    "yt_behag_behag_ragam_veena_instrumental_carnatic",
    "yt_bhairavi_bhairavi_ragam_alapana_carnatic_vocal_concert",
    "yt_bhairavi_bhairavi_ragam_tanam_pallavi_carnatic",
    "yt_bilahari_bilahari_ragam_alapana_carnatic_vocal_concert",
    "yt_bilahari_bilahari_ragam_veena_instrumental_carnatic",
    "yt_devagandhari_devagandhari_ragam_carnatic_vocal_concert",
    "yt_devagandhari_devagandhari_ragam_veena_instrumental_carnatic",
    "yt_dhanyasi_dhanyasi_ragam_alapana_carnatic_vocal_concert",
    "yt_dhanyasi_dhanyasi_ragam_violin_instrumental_carnatic",
    "yt_gaula_dudukugala_gaula_tyagaraja_pancharatna_vocal",
    "yt_harikambhoji_harikambhoji_ragam_alapana_carnatic_vocal_concer",
    "yt_harikambhoji_harikambhoji_ragam_veena_instrumental_carnatic",
    "yt_husseni_huseni_ragam_carnatic_vocal_concert",
    "yt_husseni_huseni_ragam_violin_instrumental_carnatic",
    "yt_kalyani_kalyani_ragam_alapana_carnatic_vocal_concert",
    "yt_kalyani_kalyani_ragam_tanam_pallavi_carnatic",
    "yt_kamas_khamas_ragam_carnatic_vocal_concert",
    "yt_kamas_khamas_ragam_veena_instrumental_carnatic",
    "yt_kamavardani_kamavardhani_ragam_veena_instrumental_carnatic",
    "yt_kamavardani_pantuvarali_ragam_alapana_carnatic_vocal_concert",
    "yt_kambhoji_kambhoji_ragam_alapana_carnatic_vocal_concert",
    "yt_kambhoji_kambhoji_ragam_tanam_pallavi_carnatic",
    "yt_kapi_kapi_ragam_carnatic_vocal_concert",
    "yt_kapi_kapi_ragam_veena_instrumental_carnatic",
    "yt_karaharapriya_kharaharapriya_ragam_alapana_carnatic_vocal_conc",
    "yt_karaharapriya_kharaharapriya_ragam_veena_instrumental_carnatic",
    "yt_kedaragaula_kedaragoula_ragam_veena_instrumental_carnatic",
    "yt_kedaragaula_kedaragowla_ragam_carnatic_vocal_concert",
    "yt_madhyamavati_madhyamavathi_ragam_veena_instrumental_carnatic",
    "yt_madhyamavati_madhyamavati_ragam_carnatic_vocal_concert",
    "yt_mayamalavagaula_mayamalavagoula_ragam_veena_instrumental_carnati",
    "yt_mayamalavagaula_mayamalavagowla_ragam_alapana_carnatic_vocal",
    "yt_mohanam_mohanam_ragam_alapana_carnatic_vocal_concert",
    "yt_mukhari_mukhari_ragam_alapana_carnatic_vocal_concert",
    "yt_mukhari_mukhari_ragam_violin_instrumental_carnatic",
    "yt_nata_nattai_ragam_veena_instrumental_carnatic",
    "yt_natakurinji_natakurinji_ragam_alapana_carnatic_vocal_concert",
    "yt_natakurinji_nattaikurinji_ragam_veena_instrumental_carnatic",
    "yt_purvikalyani_poorvikalyani_ragam_veena_instrumental_carnatic",
    "yt_purvikalyani_purvikalyani_ragam_alapana_carnatic_vocal_concer",
    "yt_ritigaula_reetigowla_ragam_alapana_carnatic_vocal_concert",
    "yt_ritigaula_ritigaula_ragam_veena_instrumental_carnatic",
    "yt_sahana_sahana_ragam_carnatic_vocal_concert",
    "yt_sahana_sahana_ragam_veena_instrumental_carnatic",
    "yt_sama_sama_ragam_carnatic_vocal_concert_kriti",
    "yt_sama_shama_ragam_veena_instrumental_carnatic",
    "yt_sankarabharanam_shankarabharanam_ragam_tanam_pallavi_carnatic",
    "yt_saveri_saveri_ragam_alapana_carnatic_vocal_concert",
    "yt_saveri_saveri_ragam_veena_instrumental_carnatic",
    "yt_sencurutti_chenchurutti_ragam_veena_instrumental_carnatic",
    "yt_sencurutti_senchurutti_ragam_carnatic_vocal_concert",
    "yt_sri_endaro_mahanubhavulu_sri_ragam_tyagaraja_panchar",
    "yt_sri_sri_ragam_alapana_carnatic_vocal_concert",
    "yt_sriranjani_sriranjani_ragam_alapana_carnatic_vocal_concert",
    "yt_surati_surati_ragam_veena_instrumental_carnatic",
    "yt_surati_surutti_ragam_carnatic_vocal_concert",
    "yt_todi_todi_ragam_alapana_carnatic_vocal_concert",
    "yt_todi_todi_ragam_tanam_pallavi_carnatic",
    "yt_varali_kanakanaruchira_varali_tyagaraja_pancharatna_voc",
    "yt_yadukula_kamboji_yadukula_kambhoji_ragam_veena_instrumental_carna",
    "yt_yadukula_kamboji_yadukulakambhoji_ragam_carnatic_vocal_concert",
)

assert len(YOUTUBE_PROBE) == 67, len(YOUTUBE_PROBE)
assert len(set(YOUTUBE_PROBE)) == 67, "duplicate id"
