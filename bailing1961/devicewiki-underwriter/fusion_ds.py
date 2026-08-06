"""fusion_ds.py -- Dempster-Shafer fraud-belief fusion for DeviceWiki-Underwriter.

Replaces the Stage-2 deterministic fraud_band placeholder. Frame of
discernment: {genuine, fraud}. Each evidence channel contributes a mass
function over {G}, {F}, and Theta (ignorance); channels are combined with
Dempster's rule; the combined belief/plausibility of fraud maps to the
three-band contract the decision engine already consumes:

    Bel(F) >= T_REJECT  -> "reject"    (refer: fraud_review)
    Pl(F)  <= T_ACCEPT  -> "accept"
    otherwise           -> "uncertain" (refer: fraud_uncertain)

Channels in this version (deliberately few, honestly weak):
    challenge : pass / fail / skipped (skipped contributes pure ignorance)
    views     : how many of the three views survived the quality gate

The module exposes the same combine() core planned for CogStratum so code
can flow between the two projects. Mass priors are hand-set and marked for
gold-set calibration; report the operating curve, not just the bands.

PUBLIC-SAFE MODULE (ships in the Space): contains fusion arithmetic only.
ASCII only.
"""

T_REJECT = 0.55
T_ACCEPT = 0.35

G, F, THETA = "G", "F", "T"


def mass_challenge(status):
    if status == "pass":
        return {G: 0.60, F: 0.00, THETA: 0.40}
    if status == "fail":
        return {G: 0.00, F: 0.55, THETA: 0.45}
    return {G: 0.00, F: 0.00, THETA: 1.00}  # skipped / unknown


def mass_views(n_valid_views):
    if n_valid_views >= 3:
        return {G: 0.30, F: 0.00, THETA: 0.70}
    if n_valid_views == 2:
        return {G: 0.00, F: 0.15, THETA: 0.85}
    return {G: 0.00, F: 0.35, THETA: 0.65}


def combine(m1, m2):
    """Dempster's rule for the 2-hypothesis frame {G, F} + Theta."""
    k = m1[G] * m2[F] + m1[F] * m2[G]
    if k >= 1.0:
        return {G: 0.0, F: 0.0, THETA: 1.0}
    n = 1.0 - k
    return {
        G: (m1[G] * m2[G] + m1[G] * m2[THETA] + m1[THETA] * m2[G]) / n,
        F: (m1[F] * m2[F] + m1[F] * m2[THETA] + m1[THETA] * m2[F]) / n,
        THETA: (m1[THETA] * m2[THETA]) / n,
    }


def fuse(channel_masses):
    m = {G: 0.0, F: 0.0, THETA: 1.0}
    for cm in channel_masses:
        m = combine(m, cm)
    return m


def band(m):
    bel_f = m[F]
    pl_f = m[F] + m[THETA]
    if bel_f >= T_REJECT:
        return "reject"
    if pl_f <= T_ACCEPT:
        return "accept"
    return "uncertain"


def fraud_band(challenge_status, n_valid_views):
    """challenge_status: 'pass' | 'fail' | 'skipped'.
    Returns (band, detail dict for the audit log / UI)."""
    channels = {
        "challenge": mass_challenge(challenge_status),
        "views": mass_views(n_valid_views),
    }
    m = fuse(channels.values())
    b = band(m)
    detail = {
        "bel_fraud": round(m[F], 3),
        "pl_fraud": round(m[F] + m[THETA], 3),
        "band": b,
        "channels": {k: {h: round(v, 2) for h, v in cm.items()}
                     for k, cm in channels.items()},
        "thresholds": {"reject_bel": T_REJECT, "accept_pl": T_ACCEPT},
        "calibration": "hand-set priors, pre-calibration",
    }
    return b, detail
