---
name: home-assistant
description: Read and control Home Assistant entities, call services, and manage automations via the Home Assistant REST API. Use when the user wants to interact with a Home Assistant instance, such as turning on lights, reading sensor states, listing or creating automations, or triggering devices.
compatibility: Self-contained skill. Requires Python 3, network access to Home Assistant, and a long-lived access token.
metadata:
  author: oliverruoff
  version: "1.0"
---

# Home Assistant

Use this skill to interact with a Home Assistant instance via its REST API.
It is standalone and does not depend on project code.

Supported capabilities:
- Read entity states (all or single)
- Set entity states (local state objects)
- Call services (e.g., turn on lights, open covers)
- List, read, create, update, delete, and trigger automations
- Get Home Assistant configuration and available services

## Configuration

Set the following environment variables before use.

### Required

```env
HOME_ASSISTANT_TOKEN=YOUR_LONG_LIVED_ACCESS_TOKEN
```

Create a long-lived access token in Home Assistant under your **User Profile > Long-Lived Access Tokens**.

### Optional

```env
HOME_ASSISTANT_URL=http://homeassistant.local:8123
```

If not set, the default is `http://homeassistant.local:8123`.

## First-time setup

From this skill directory (the directory containing `SKILL.md`), install local requirements if they are not already available:

```bash
python -m pip install -r requirements.txt
```

## CLI

All commands print JSON. From this skill directory (the directory containing `SKILL.md`):

```bash
python scripts/home_assistant.py <command> [options]
```

## Commands

### Health check

```bash
python scripts/home_assistant.py health
```

Returns a simple message if the API is reachable.

### Get entity states

All states:

```bash
python scripts/home_assistant.py get-states
```

Single state:

```bash
python scripts/home_assistant.py get-states --entity-id light.living_room
```

### Set entity state

```bash
python scripts/home_assistant.py set-state --entity-id sensor.my_sensor --state "42"
```

With attributes:

```bash
python scripts/home_assistant.py set-state --entity-id sensor.my_sensor --state "42" --attributes '{"unit_of_measurement": "°C"}'
```

**Note:** Setting a state only updates the local state object in Home Assistant and does not communicate with the actual device. To control devices, use `call-service`.

### Call a service

```bash
python scripts/home_assistant.py call-service --domain light --service turn_on --entity-id light.living_room
```

With extra service data:

```bash
python scripts/home_assistant.py call-service --domain light --service turn_on --entity-id light.living_room --service-data '{"brightness": 200}'
```

### Get configuration

```bash
python scripts/home_assistant.py get-config
```

### Get available services

```bash
python scripts/home_assistant.py get-services
```

### Automations

**List automations:**

```bash
python scripts/home_assistant.py list-automations
```

**Read automation config:**

```bash
python scripts/home_assistant.py get-automation --automation-id my_automation_id
```

**Create an automation:**

```bash
python scripts/home_assistant.py create-automation --config-file automation.json
```

Or inline:

```bash
python scripts/home_assistant.py create-automation --config-json '{"id":"new_auto","alias":"New Automation","trigger":[],"action":[]}'
```

**Update an automation:**

```bash
python scripts/home_assistant.py update-automation --automation-id my_automation_id --config-file automation.json
```

**Delete an automation:**

```bash
python scripts/home_assistant.py delete-automation --automation-id my_automation_id
```

**Trigger an automation:**

```bash
python scripts/home_assistant.py trigger-automation --automation-id my_automation_id
```

## Automation JSON format

When creating or updating automations, the payload follows the standard Home Assistant automation YAML schema expressed as JSON. Key fields include:

- `id`: Unique automation identifier
- `alias`: Human-readable name
- `description`: Optional description
- `trigger`: Array of trigger objects
- `condition`: Optional array of condition objects
- `action`: Array of action objects

Example minimal automation JSON:

```json
{
  "id": "morning_lights",
  "alias": "Morning Lights",
  "trigger": [
    {
      "platform": "time",
      "at": "07:00:00"
    }
  ],
  "action": [
    {
      "service": "light.turn_on",
      "target": {
        "entity_id": "light.bedroom"
      }
    }
  ],
  "mode": "single"
}
```

## Usage guidelines

- Use `get-states` when the user wants to know the current state of devices or sensors.
- Use `call-service` when the user wants to control a device (turn on/off, open/close, set temperature, etc.).
- Use automation commands when the user wants to list, create, modify, delete, or manually trigger automations.
- Prefer `call-service` over `set-state` for real device control.
- Always show the user the JSON result in a concise format. If the result is large, summarize key fields.
- If a command fails with a connection error, remind the user to check `HOME_ASSISTANT_URL` and network access.
- If authentication fails (401), remind the user to set a valid `HOME_ASSISTANT_TOKEN`.
