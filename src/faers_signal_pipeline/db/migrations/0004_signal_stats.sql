-- Disproportionality statistics (Phase 4).

CREATE TABLE IF NOT EXISTS signal_stats (
    cutoff_quarter text NOT NULL,
    rxcui          text NOT NULL,
    pt             text NOT NULL,
    a              bigint NOT NULL,
    b              bigint NOT NULL,
    c              bigint NOT NULL,
    d              bigint NOT NULL,
    prr            double precision,
    prr_ci_low     double precision,
    prr_ci_high    double precision,
    ror            double precision,
    ror_ci_low     double precision,
    ror_ci_high    double precision,
    chi_square     double precision,
    PRIMARY KEY (cutoff_quarter, rxcui, pt)
);
CREATE INDEX IF NOT EXISTS signal_stats_rank_idx
    ON signal_stats (cutoff_quarter, chi_square DESC);
CREATE INDEX IF NOT EXISTS signal_stats_ror_rank_idx
    ON signal_stats (cutoff_quarter, ror_ci_low DESC);
