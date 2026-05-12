#!/usr/bin/env python3
"""
Home Assistant REST API CLI
Self-contained script to read/control entities and manage automations.
Reads HOME_ASSISTANT_TOKEN (required) and HOME_ASSISTANT_URL (optional) from env.
"""

import argparse
import json
import os
import sys
import urllib.parse

import requests

DEFAULT_HA_URL = "http://homeassistant.local:8123"


def get_base_url():
    return os.environ.get("HOME_ASSISTANT_URL", DEFAULT_HA_URL).rstrip("/")


def get_headers():
    token = os.environ.get("HOME_ASSISTANT_TOKEN", "").strip()
    if not token:
        return None
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _request(method, endpoint, json_data=None, params=None):
    base = get_base_url()
    url = f"{base}{endpoint}"
    headers = get_headers()
    if headers is None:
        return {"ok": False, "error": "Missing HOME_ASSISTANT_TOKEN environment variable."}
    try:
        resp = requests.request(method, url, headers=headers, json=json_data, params=params, timeout=30)
        if resp.status_code in (200, 201):
            try:
                return {"ok": True, "data": resp.json()}
            except ValueError:
                return {"ok": True, "data": resp.text}
        else:
            try:
                detail = resp.json()
            except ValueError:
                detail = resp.text
            return {"ok": False, "status_code": resp.status_code, "error": detail}
    except requests.exceptions.ConnectionError as e:
        return {"ok": False, "error": f"Connection error: {e}"}
    except requests.exceptions.Timeout as e:
        return {"ok": False, "error": f"Timeout: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def cmd_health(_args):
    result = _request("GET", "/api/")
    print(json.dumps(result, indent=2))


def cmd_get_states(args):
    if args.entity_id:
        result = _request("GET", f"/api/states/{args.entity_id}")
    else:
        result = _request("GET", "/api/states")
    print(json.dumps(result, indent=2))


def cmd_set_state(args):
    payload = {"state": args.state}
    if args.attributes:
        try:
            payload["attributes"] = json.loads(args.attributes)
        except json.JSONDecodeError as e:
            print(json.dumps({"ok": False, "error": f"Invalid attributes JSON: {e}"}, indent=2))
            return
    result = _request("POST", f"/api/states/{args.entity_id}", json_data=payload)
    print(json.dumps(result, indent=2))


def cmd_call_service(args):
    payload = {}
    if args.entity_id:
        payload["entity_id"] = args.entity_id
    if args.service_data:
        try:
            extra = json.loads(args.service_data)
        except json.JSONDecodeError as e:
            print(json.dumps({"ok": False, "error": f"Invalid service_data JSON: {e}"}, indent=2))
            return
        payload.update(extra)
    result = _request("POST", f"/api/services/{args.domain}/{args.service}", json_data=payload)
    print(json.dumps(result, indent=2))


def cmd_get_config(_args):
    result = _request("GET", "/api/config")
    print(json.dumps(result, indent=2))


def cmd_get_services(_args):
    result = _request("GET", "/api/services")
    print(json.dumps(result, indent=2))


def cmd_list_automations(_args):
    result = _request("GET", "/api/states")
    if not result.get("ok"):
        print(json.dumps(result, indent=2))
        return
    automations = [e for e in result["data"] if e.get("entity_id", "").startswith("automation.")]
    print(json.dumps({"ok": True, "data": automations}, indent=2))


def cmd_get_automation(args):
    result = _request("GET", f"/api/config/automation/config/{args.automation_id}")
    print(json.dumps(result, indent=2))


def cmd_create_automation(args):
    if args.config_file:
        try:
            with open(args.config_file, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(json.dumps({"ok": False, "error": f"Failed to read config file: {e}"}, indent=2))
            return
    elif args.config_json:
        try:
            payload = json.loads(args.config_json)
        except json.JSONDecodeError as e:
            print(json.dumps({"ok": False, "error": f"Invalid config JSON: {e}"}, indent=2))
            return
    else:
        print(json.dumps({"ok": False, "error": "Either --config-file or --config-json is required."}, indent=2))
        return
    automation_id = args.automation_id or payload.get("id")
    if not automation_id:
        print(json.dumps({"ok": False, "error": "Automation ID is required. Pass --automation-id or include 'id' in the config."}, indent=2))
        return
    result = _request("POST", f"/api/config/automation/config/{automation_id}", json_data=payload)
    print(json.dumps(result, indent=2))


def cmd_update_automation(args):
    if args.config_file:
        try:
            with open(args.config_file, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(json.dumps({"ok": False, "error": f"Failed to read config file: {e}"}, indent=2))
            return
    elif args.config_json:
        try:
            payload = json.loads(args.config_json)
        except json.JSONDecodeError as e:
            print(json.dumps({"ok": False, "error": f"Invalid config JSON: {e}"}, indent=2))
            return
    else:
        print(json.dumps({"ok": False, "error": "Either --config-file or --config-json is required."}, indent=2))
        return
    result = _request("POST", f"/api/config/automation/config/{args.automation_id}", json_data=payload)
    print(json.dumps(result, indent=2))


def cmd_delete_automation(args):
    result = _request("DELETE", f"/api/config/automation/config/{args.automation_id}")
    print(json.dumps(result, indent=2))


def cmd_trigger_automation(args):
    payload = {"entity_id": f"automation.{args.automation_id}"}
    result = _request("POST", "/api/services/automation/trigger", json_data=payload)
    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Home Assistant REST API CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p = subparsers.add_parser("health", help="Check HA API health")
    p.set_defaults(func=cmd_health)

    p = subparsers.add_parser("get-states", help="Get all entity states or a single entity")
    p.add_argument("--entity-id", help="Entity ID (e.g., light.living_room)")
    p.set_defaults(func=cmd_get_states)

    p = subparsers.add_parser("set-state", help="Set the state of an entity")
    p.add_argument("--entity-id", required=True)
    p.add_argument("--state", required=True)
    p.add_argument("--attributes", help="JSON string of attributes")
    p.set_defaults(func=cmd_set_state)

    p = subparsers.add_parser("call-service", help="Call a Home Assistant service")
    p.add_argument("--domain", required=True, help="Service domain, e.g., light")
    p.add_argument("--service", required=True, help="Service name, e.g., turn_on")
    p.add_argument("--entity-id", help="Target entity_id")
    p.add_argument("--service-data", help="Additional JSON service data")
    p.set_defaults(func=cmd_call_service)

    p = subparsers.add_parser("get-config", help="Get HA configuration")
    p.set_defaults(func=cmd_get_config)

    p = subparsers.add_parser("get-services", help="List all available services")
    p.set_defaults(func=cmd_get_services)

    p = subparsers.add_parser("list-automations", help="List all automation entities")
    p.set_defaults(func=cmd_list_automations)

    p = subparsers.add_parser("get-automation", help="Get automation config by ID")
    p.add_argument("--automation-id", required=True, help="Automation ID (without automation. prefix)")
    p.set_defaults(func=cmd_get_automation)

    p = subparsers.add_parser("create-automation", help="Create a new automation")
    p.add_argument("--automation-id", help="Automation ID (if not in config JSON)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--config-file", help="Path to JSON config file")
    g.add_argument("--config-json", help="Raw JSON config string")
    p.set_defaults(func=cmd_create_automation)

    p = subparsers.add_parser("update-automation", help="Update an existing automation")
    p.add_argument("--automation-id", required=True)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--config-file", help="Path to JSON config file")
    g.add_argument("--config-json", help="Raw JSON config string")
    p.set_defaults(func=cmd_update_automation)

    p = subparsers.add_parser("delete-automation", help="Delete an automation")
    p.add_argument("--automation-id", required=True)
    p.set_defaults(func=cmd_delete_automation)

    p = subparsers.add_parser("trigger-automation", help="Trigger an automation")
    p.add_argument("--automation-id", required=True)
    p.set_defaults(func=cmd_trigger_automation)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
