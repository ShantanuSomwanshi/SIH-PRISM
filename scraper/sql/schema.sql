-- SQLite schema is initialized automatically by the application.
-- This file documents the tables. Running the application creates them.

-- baseline_standards is immutable source evidence from selected_standards/*.pdf.
-- standard_changes contains deduplicated field-level BIS observations.
-- standard_versions is append-only history of baseline and BIS revised-list observations.
-- current_standards is a replaceable pointer to the latest version; it is not history.
-- standard_subscriptions and notifications prepare future user notification delivery.
