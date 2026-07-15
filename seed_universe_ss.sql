-- Universe_SS -- real component registration (replaces the placeholder seed
-- from ICU_Cowork_Seed_v1.0.md, which assumed two generic enrichment/coverage
-- rows on ports 8001/8002 -- that didn't match the actual layout).
--
-- Actual layout (confirmed 2026-07-15):
--   eod            -- cron, 11:30pm daily
--   intraday       -- cron, every 4h from 7am-11pm
--   weekly         -- cron, Friday nights 11:30pm
--   sync_engine_tv -- manual/on-demand, roughly every 2-3 weeks
-- derive_engine.log is shared logic invoked by eod/intraday/weekly -- not
-- independently schedulable, so it has no registry row of its own.
--
-- No component here exposes an HTTP endpoint (all cron or manually run), so
-- endpoint_url is NULL throughout -- Run Now and the staleness poll-on-wake
-- are both inert for these rows; ICU only tracks whatever they push to
-- /ingest/status plus passive log tailing via log_path.
--
-- sync_engine_tv is registered as '1MO' rather than 'ON_DEMAND' because
-- ON_DEMAND requires a non-NULL endpoint_url (Basket C v1.2, enforced by the
-- on_demand_requires_endpoint constraint in schema.sql) and this script has
-- no endpoint. '1MO' gives it a ~90-day staleness threshold -- comfortably
-- above its real ~2-3 week cadence, so it won't false-alarm, but a multi-month
-- gap also won't be caught quickly. Revisit if that turns out to matter.

INSERT INTO process_registry
  (component_id, display_name, endpoint_url, log_path, github_repo_tag, schedule_string, expected_interval)
VALUES
  ('universe_ss_eod', 'Universe SS -- EOD',
   NULL, '/var/log/portfolio/eod.log',
   NULL, '1D', INTERVAL '1 day'),
  ('universe_ss_intraday', 'Universe SS -- Intraday',
   NULL, '/var/log/portfolio/intraday.log',
   NULL, '4H', INTERVAL '4 hours'),
  ('universe_ss_weekly', 'Universe SS -- Weekly',
   NULL, '/var/log/portfolio/weekly.log',
   NULL, '1W', INTERVAL '1 week'),
  ('universe_ss_sync_tv', 'Universe SS -- Sync (TV)',
   NULL, '/var/log/portfolio/sync_engine_tv.log',
   NULL, '1MO', INTERVAL '30 days')
ON CONFLICT (component_id) DO NOTHING;
