"""Check this project's Supabase and OpenAI credentials without printing them.

Run from the repository root with: python check_keys.py
Uses only the Python standard library and makes read-only HTTP requests.
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PLACEHOLDER_MARKERS = ("your_", "replace_me", "placeholder", "example", "...")


def read_config(filename):
    path = ROOT / filename
    try:
        with path.open(encoding="utf-8") as config_file:
            data = json.load(config_file)
    except FileNotFoundError:
        print(f"[FAIL] {filename} not found")
        return None
    except json.JSONDecodeError as exc:
        print(f"[FAIL] {filename} is not valid JSON (line {exc.lineno})")
        return None
    except OSError as exc:
        print(f"[FAIL] Could not read {filename} ({type(exc).__name__})")
        return None

    if not isinstance(data, dict):
        print(f"[FAIL] {filename} must contain a JSON object")
        return None
    print(f"[PASS] {filename} is valid JSON")
    return data


def configured(config, name, filename):
    value = config.get(name) if config else None
    if not isinstance(value, str) or not value.strip():
        print(f"[FAIL] {filename}: {name} is missing or empty")
        return None
    if any(marker in value.lower() for marker in PLACEHOLDER_MARKERS):
        print(f"[FAIL] {filename}: {name} still looks like a placeholder")
        return None
    return value.strip()


def request_status(label, url, headers):
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            status = response.status
            body = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = b""
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"[FAIL] {label}: network/SSL error ({type(exc).__name__})")
        return None, None

    if 200 <= status < 300:
        print(f"[PASS] {label}: HTTP {status}")
        return status, body
    print(f"[FAIL] {label}: HTTP {status} (credentials or project settings may be wrong)")
    return status, body


def main():
    public = read_config("config.public.json")
    secret = read_config("config.secret.json")
    if public is None or secret is None:
        return 1

    project_url = configured(public, "SUPABASE_URL", "config.public.json")
    anon_key = configured(public, "SUPABASE_ANON_KEY", "config.public.json")
    openai_key = configured(secret, "OPENAI_API_KEY", "config.secret.json")
    access_token = configured(secret, "SUPABASE_ACCESS_TOKEN", "config.secret.json")
    project_ref = configured(secret, "SUPABASE_PROJECT_REF", "config.secret.json")
    service_key = configured(secret, "SUPABASE_SERVICE_KEY", "config.secret.json")

    failures = sum(
        value is None
        for value in (project_url, anon_key, openai_key, access_token, project_ref, service_key)
    )
    if project_url and anon_key:
        base_url = project_url.rstrip("/")
        if not base_url.startswith("https://"):
            print("[FAIL] SUPABASE_URL should start with https://")
            failures += 1
        else:
            status, _ = request_status(
                "Supabase URL + anon key (Auth settings)",
                f"{base_url}/auth/v1/settings",
                {"apikey": anon_key},
            )
            failures += status is None or not 200 <= status < 300

            if service_key:
                status, _ = request_status(
                    "Supabase service key (REST API)",
                    f"{base_url}/rest/v1/",
                    {
                        "apikey": service_key,
                        "Authorization": f"Bearer {service_key}",
                    },
                )
                failures += status is None or not 200 <= status < 300

    if openai_key:
        status, _ = request_status(
            "OpenAI API key (models endpoint)",
            "https://api.openai.com/v1/models",
            {"Authorization": f"Bearer {openai_key}"},
        )
        failures += status is None or not 200 <= status < 300

    if access_token:
        status, body = request_status(
            "Supabase access token (Management API)",
            "https://api.supabase.com/v1/projects",
            {"Authorization": f"Bearer {access_token}"},
        )
        failures += status is None or not 200 <= status < 300
        if status is not None and 200 <= status < 300 and project_ref:
            try:
                projects = json.loads(body.decode("utf-8"))
                refs = {
                    str(item.get("ref") or item.get("project_ref") or item.get("id"))
                    for item in projects
                    if isinstance(item, dict)
                }
                if project_ref in refs:
                    print("[PASS] Project ref matches a project accessible to this access token")
                else:
                    print("[FAIL] Project ref was not found among projects accessible to this token")
                    failures += 1
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
                print("[WARN] Token is valid, but the project list could not be checked")

    print("\nNo credential values or response bodies were displayed.")
    if failures:
        print(f"Finished with {failures} failed check(s).")
        return 1
    print("All credential checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
