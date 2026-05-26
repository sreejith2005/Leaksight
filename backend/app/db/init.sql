-- =============================================================================
-- LeakSight V1 — Database Initialization Script
-- =============================================================================
-- Source: docs/DATABASE_SCHEMA.md (Extensions, Roles, RLS section)
--
-- This script establishes the database foundation that Phase 2 will build on.
-- It does exactly four things:
--   1. Enable uuid-ossp extension (UUID generation)
--   2. Enable pg_trgm extension (trigram similarity for future fuzzy search)
--   3. Create app_admin role (cross-tenant operations, bypasses RLS)
--   4. Create app_tenant_user role (application runtime, subject to RLS)
--
-- No application tables are created here. Tables are Phase 2.
-- =============================================================================

-- Extension 1: UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Extension 2: Trigram similarity for fuzzy search
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Role 1: app_admin — for cross-tenant administrative operations
-- (migrations, seeding, backup). Bypasses RLS.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_admin') THEN
        CREATE ROLE app_admin WITH LOGIN NOINHERIT;
    END IF;
END
$$;

-- Role 2: app_tenant_user — for application runtime queries.
-- Subject to RLS — can only see rows where tenant_id matches
-- current_setting('app.current_tenant_id').
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_tenant_user') THEN
        CREATE ROLE app_tenant_user WITH LOGIN NOINHERIT;
    END IF;
END
$$;
