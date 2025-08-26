#!/usr/bin/env python3
"""
Smart Exact Online API endpoint scraper that tries multiple naming patterns
and tracks success/failure in the endpoints file.
"""

import subprocess
import sys
import time
import os
from pathlib import Path


def check_existing_scrape(endpoint_name):
    """Check if endpoint already has a successful scrape (>10 lines)."""
    safe_name = endpoint_name.replace("/", "_").replace("\\", "_")
    safe_name = safe_name.replace(" ", "_").replace("(", "").replace(")", "")
    file_path = Path(f"exact_specs/api_specs/{safe_name}.json")

    if file_path.exists():
        try:
            line_count = len(file_path.read_text().splitlines())
            return line_count > 10  # Consider >10 lines as successful
        except:
            return False
    return False


def scrape_endpoint_with_patterns(base_name):
    """Try scraping an endpoint with multiple naming patterns."""

    # Skip if already successfully scraped
    patterns_to_try = [
        base_name,  # Original name
        f"CRM{base_name}",
        f"Sales{base_name}",
        f"Purchase{base_name}",
        f"Financial{base_name}",
        f"Cashflow{base_name}",
        f"Logistics{base_name}",
        f"Payroll{base_name}",
        f"HRM{base_name}",
        f"Assets{base_name}",
        f"Project{base_name}",
        f"System{base_name}",
        f"Inventory{base_name}",
        f"Manufacturing{base_name}",
        # Double patterns (common for main entities)
        f"SalesInvoice{base_name}",
        f"SalesOrder{base_name}",
        f"PurchaseInvoice{base_name}",
        f"PurchaseOrder{base_name}",
        f"PurchaseEntry{base_name}",
        f"SalesEntry{base_name}",
        f"FinancialTransaction{base_name}",
        f"GeneralJournalEntry{base_name}",
    ]

    for pattern in patterns_to_try:
        # Skip if already exists and successful
        if check_existing_scrape(pattern):
            print(f"  ⏭️  {pattern} - Already scraped successfully")
            return pattern, "already_scraped"

        try:
            print(f"  🔄 Trying {pattern}...")
            result = subprocess.run(
                ["uv", "run", "python", "manage.py", "scrape_single_endpoint", pattern],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                # Check if fields were discovered
                if "Fields discovered: 0" in result.stdout:
                    print(f"    ❌ {pattern} - No fields")
                    continue
                else:
                    # Extract field count
                    lines = result.stdout.split("\n")
                    field_line = [
                        line for line in lines if "Fields discovered:" in line
                    ]
                    if field_line:
                        field_count = field_line[0].split("Fields discovered: ")[1]
                        print(f"    ✅ {pattern} - {field_count} fields")
                        return pattern, f"success_{field_count}_fields"
                    else:
                        print(f"    ✅ {pattern} - Success (unknown field count)")
                        return pattern, "success_unknown_fields"
            else:
                print(f"    💥 {pattern} - Error: {result.stderr.strip()[:50]}")

        except subprocess.TimeoutExpired:
            print(f"    ⏰ {pattern} - Timeout")
        except Exception as e:
            print(f"    💥 {pattern} - Exception: {str(e)[:50]}")

        # Small delay between pattern attempts
        time.sleep(0.5)

    return None, "all_patterns_failed"


def update_endpoints_file(endpoints_file, results):
    """Update the endpoints file with results."""
    backup_file = endpoints_file.with_suffix(".txt.backup")

    # Create backup
    if endpoints_file.exists():
        backup_file.write_text(endpoints_file.read_text())

    with open(endpoints_file, "w") as f:
        f.write("# Exact Online API Endpoints - Status Tracking\n")
        f.write("# Format: ENDPOINT_NAME | STATUS | WORKING_PATTERN\n")
        f.write("# STATUS: success_X_fields, already_scraped, all_patterns_failed\n\n")

        for base_name, (working_pattern, status) in results.items():
            if working_pattern:
                f.write(f"{working_pattern} | {status} | {base_name}\n")
            else:
                f.write(f"{base_name} | {status} | none\n")


def main():
    """Main function to process endpoints intelligently."""
    endpoints_file = Path("exact_online_endpoints.txt")

    if not endpoints_file.exists():
        print("❌ endpoints file not found: exact_online_endpoints.txt")
        sys.exit(1)

    # Read base endpoint names (clean list without prefixes)
    base_endpoints = [
        "Accounts",
        "BankAccounts",
        "Contacts",
        "Items",
        "Employees",
        "Assets",
        "SalesInvoices",
        "SalesOrders",
        "PurchaseInvoices",
        "PurchaseOrders",
        "GLAccounts",
        "TransactionLines",
        "Receivables",
        "PaymentConditions",
        "Suppliers",
        "Quotations",
        "Budgets",
        "Projects",
        "Currencies",
        "Users",
    ]

    print(f"🚀 Smart scraping {len(base_endpoints)} key endpoints...")
    print("=" * 70)

    results = {}
    success_count = 0

    for i, base_name in enumerate(base_endpoints, 1):
        print(f"[{i}/{len(base_endpoints)}] Processing {base_name}")

        working_pattern, status = scrape_endpoint_with_patterns(base_name)
        results[base_name] = (working_pattern, status)

        if "success" in status or "already_scraped" in status:
            success_count += 1

        print()  # Empty line between endpoints
        time.sleep(1)  # Respectful delay

    print("=" * 70)
    print(f"✅ Smart scraping completed!")
    print(f"📊 Results: {success_count}/{len(base_endpoints)} successful")

    # Update endpoints file with results
    update_endpoints_file(endpoints_file, results)
    print(f"📁 Updated {endpoints_file} with results")
    print(f"📁 Backup saved as {endpoints_file.with_suffix('.txt.backup')}")
    print(f"📁 Check exact_specs/api_specs/ for generated files")


if __name__ == "__main__":
    main()
