"""Phase 2 Validation Script — runs all six validation queries."""
import json

import psycopg2


def main():
    conn = psycopg2.connect(
        host="localhost",
        port=5599,
        dbname="leaksight_dev",
        user="leaksight",
        password="testpass123",
    )
    cur = conn.cursor()

    # 1. RLS status
    print("=== RLS STATUS ===")
    cur.execute(
        "SELECT tablename, rowsecurity FROM pg_tables "
        "WHERE schemaname = 'public' ORDER BY tablename"
    )
    for row in cur.fetchall():
        print(f"  {row[0]}: rowsecurity={row[1]}")

    # 2. Invoices indexes
    print("\n=== INVOICES INDEXES ===")
    cur.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'invoices'")
    for row in cur.fetchall():
        print(f"  {row[0]}")

    # 3. Canonical units count
    print("\n=== CANONICAL UNITS ===")
    cur.execute("SELECT count(*) FROM canonical_units")
    count = cur.fetchone()[0]
    print(f"  Count: {count}")
    assert count == 11, f"Expected 11, got {count}"

    # 4. Immutability trigger
    print("\n=== LEAKAGE TRIGGER ===")
    cur.execute(
        "SELECT tgname FROM pg_trigger "
        "WHERE tgrelid = 'leakage_records'::regclass"
    )
    triggers = [row[0] for row in cur.fetchall()]
    print(f"  Triggers: {triggers}")
    assert "trg_leakage_immutability" in triggers

    # 5. Abbreviation dictionary
    print("\n=== ABBREVIATION DICTIONARY ===")
    cur.execute("SELECT abbreviation_dictionary FROM tenant_settings LIMIT 1")
    row = cur.fetchone()
    d = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    print(f"  Entries: {len(d)}")
    assert len(d) >= 11, f"Expected >= 11 entries, got {len(d)}"

    # 6. Roles
    print("\n=== ROLES ===")
    cur.execute(
        "SELECT rolname FROM pg_roles "
        "WHERE rolname IN ('app_admin', 'app_tenant_user')"
    )
    roles = [row[0] for row in cur.fetchall()]
    print(f"  Roles: {roles}")
    assert len(roles) == 2, f"Expected 2 roles, got {len(roles)}"

    # 7. Unit conversion factors count
    print("\n=== UNIT CONVERSION FACTORS ===")
    cur.execute("SELECT count(*) FROM unit_conversion_factors")
    count = cur.fetchone()[0]
    print(f"  Count: {count}")
    assert count == 10, f"Expected 10, got {count}"

    # 8. Tenant settings count
    print("\n=== TENANT SETTINGS ===")
    cur.execute("SELECT count(*) FROM tenant_settings")
    count = cur.fetchone()[0]
    print(f"  Count: {count}")
    assert count >= 1, f"Expected >= 1, got {count}"

    conn.close()
    print("\n=== ALL VALIDATION CHECKS PASSED ===")


if __name__ == "__main__":
    main()
