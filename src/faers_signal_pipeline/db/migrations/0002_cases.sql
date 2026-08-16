-- Case versioning (Phase 2): full version history + current pointer.

CREATE TABLE IF NOT EXISTS case_versions (
    caseid       text   NOT NULL,
    caseversion  text   NOT NULL,
    version_int  bigint NOT NULL,
    quarter      text   NOT NULL,
    primaryid    text   NOT NULL,
    PRIMARY KEY (caseid, version_int, quarter)
);

CREATE TABLE IF NOT EXISTS current_cases (
    caseid      text PRIMARY KEY,
    caseversion text NOT NULL,
    quarter     text NOT NULL,
    primaryid   text NOT NULL
);
CREATE INDEX IF NOT EXISTS current_cases_quarter_primaryid_idx
    ON current_cases (quarter, primaryid);
