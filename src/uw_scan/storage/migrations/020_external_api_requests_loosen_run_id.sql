SET search_path TO uw_scan, public;

ALTER TABLE uw_scan.external_api_requests
    DROP CONSTRAINT IF EXISTS external_api_requests_run_id_fkey;
