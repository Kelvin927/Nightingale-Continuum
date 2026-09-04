-- Nightingale Continuum PostgreSQL tenant-isolation baseline.
-- Apply as a migration owner. The runtime role must not have SUPERUSER or BYPASSRLS.
-- After authenticating a principal, each transaction must execute:
--   SET LOCAL app.clinic_id = '<server-validated clinic UUID or opaque ID>';
-- A missing setting evaluates to NULL, so every policy below denies access by default.

BEGIN;

CREATE SCHEMA IF NOT EXISTS app_private;
REVOKE ALL ON SCHEMA app_private FROM PUBLIC;

CREATE OR REPLACE FUNCTION app_private.current_clinic_id()
RETURNS text
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
    SELECT NULLIF(current_setting('app.clinic_id', true), '')
$$;

REVOKE ALL ON FUNCTION app_private.current_clinic_id() FROM PUBLIC;

ALTER TABLE clinics ENABLE ROW LEVEL SECURITY;
ALTER TABLE clinics FORCE ROW LEVEL SECURITY;
CREATE POLICY clinic_isolation ON clinics
    USING (id = app_private.current_clinic_id())
    WITH CHECK (id = app_private.current_clinic_id());

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;
CREATE POLICY clinic_isolation ON users
    USING (clinic_id = app_private.current_clinic_id())
    WITH CHECK (clinic_id = app_private.current_clinic_id());

ALTER TABLE patients ENABLE ROW LEVEL SECURITY;
ALTER TABLE patients FORCE ROW LEVEL SECURITY;
CREATE POLICY clinic_isolation ON patients
    USING (clinic_id = app_private.current_clinic_id())
    WITH CHECK (clinic_id = app_private.current_clinic_id());

ALTER TABLE entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE entries FORCE ROW LEVEL SECURITY;
CREATE POLICY clinic_isolation ON entries
    USING (clinic_id = app_private.current_clinic_id())
    WITH CHECK (clinic_id = app_private.current_clinic_id());

ALTER TABLE entry_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE entry_versions FORCE ROW LEVEL SECURITY;
CREATE POLICY clinic_isolation ON entry_versions
    USING (
        EXISTS (
            SELECT 1 FROM entries
            WHERE entries.id = entry_versions.entry_id
              AND entries.clinic_id = app_private.current_clinic_id()
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM entries
            WHERE entries.id = entry_versions.entry_id
              AND entries.clinic_id = app_private.current_clinic_id()
        )
    );

ALTER TABLE comment_threads ENABLE ROW LEVEL SECURITY;
ALTER TABLE comment_threads FORCE ROW LEVEL SECURITY;
CREATE POLICY clinic_isolation ON comment_threads
    USING (clinic_id = app_private.current_clinic_id())
    WITH CHECK (clinic_id = app_private.current_clinic_id());

ALTER TABLE comments ENABLE ROW LEVEL SECURITY;
ALTER TABLE comments FORCE ROW LEVEL SECURITY;
CREATE POLICY clinic_isolation ON comments
    USING (
        EXISTS (
            SELECT 1 FROM comment_threads
            WHERE comment_threads.id = comments.thread_id
              AND comment_threads.clinic_id = app_private.current_clinic_id()
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM comment_threads
            WHERE comment_threads.id = comments.thread_id
              AND comment_threads.clinic_id = app_private.current_clinic_id()
        )
    );

ALTER TABLE care_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE care_tasks FORCE ROW LEVEL SECURITY;
CREATE POLICY clinic_isolation ON care_tasks
    USING (clinic_id = app_private.current_clinic_id())
    WITH CHECK (clinic_id = app_private.current_clinic_id());

ALTER TABLE provenance_spans ENABLE ROW LEVEL SECURITY;
ALTER TABLE provenance_spans FORCE ROW LEVEL SECURITY;
CREATE POLICY clinic_isolation ON provenance_spans
    USING (clinic_id = app_private.current_clinic_id())
    WITH CHECK (clinic_id = app_private.current_clinic_id());

ALTER TABLE highlights ENABLE ROW LEVEL SECURITY;
ALTER TABLE highlights FORCE ROW LEVEL SECURITY;
CREATE POLICY clinic_isolation ON highlights
    USING (clinic_id = app_private.current_clinic_id())
    WITH CHECK (clinic_id = app_private.current_clinic_id());

ALTER TABLE importance_feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE importance_feedback FORCE ROW LEVEL SECURITY;
CREATE POLICY clinic_isolation ON importance_feedback
    USING (clinic_id = app_private.current_clinic_id())
    WITH CHECK (clinic_id = app_private.current_clinic_id());

ALTER TABLE feature_posteriors ENABLE ROW LEVEL SECURITY;
ALTER TABLE feature_posteriors FORCE ROW LEVEL SECURITY;
CREATE POLICY clinic_isolation ON feature_posteriors
    USING (clinic_id = app_private.current_clinic_id())
    WITH CHECK (clinic_id = app_private.current_clinic_id());

ALTER TABLE conflicts ENABLE ROW LEVEL SECURITY;
ALTER TABLE conflicts FORCE ROW LEVEL SECURITY;
CREATE POLICY clinic_isolation ON conflicts
    USING (clinic_id = app_private.current_clinic_id())
    WITH CHECK (clinic_id = app_private.current_clinic_id());

ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events FORCE ROW LEVEL SECURITY;
CREATE POLICY clinic_isolation ON audit_events
    USING (clinic_id = app_private.current_clinic_id())
    WITH CHECK (clinic_id = app_private.current_clinic_id());

ALTER TABLE retention_manifests ENABLE ROW LEVEL SECURITY;
ALTER TABLE retention_manifests FORCE ROW LEVEL SECURITY;
CREATE POLICY clinic_isolation ON retention_manifests
    USING (clinic_id = app_private.current_clinic_id())
    WITH CHECK (clinic_id = app_private.current_clinic_id());

ALTER TABLE glance_projections ENABLE ROW LEVEL SECURITY;
ALTER TABLE glance_projections FORCE ROW LEVEL SECURITY;
CREATE POLICY clinic_isolation ON glance_projections
    USING (clinic_id = app_private.current_clinic_id())
    WITH CHECK (clinic_id = app_private.current_clinic_id());

COMMIT;
