import json


def event_handler_main(in_json_str):
    in_json = json.loads(in_json_str)
    paths = in_json["paths"]
    options = in_json["options"]
    persistent_data = in_json.get("persistent-data", {})

    iface = options["interface"]
    grace_period = int(options.get("grace-period", "30"))

    # Split "irb0.10" into "irb0" and "10" for the SRLinux schema path
    parts = iface.split(".")
    iface_name = parts[0]
    subif_index = parts[1]

    # Check current BGP session state
    state = paths[0].get("value", "") if paths else ""

    response = {"actions": []}

    if state != "established":
        # BGP is down: immediately disable the interface and clear any pending grace timer
        persistent_data.pop("waiting-for-grace", None)
        response["actions"].append(
            {
                "set-cfg-path": {
                    "path": "interface {} subinterface {} admin-state".format(iface_name, subif_index),
                    "value": "disable",
                }
            }
        )
    elif persistent_data.get("waiting-for-grace"):
        # Reinvoked after grace period: BGP is still established, enable the interface
        persistent_data.pop("waiting-for-grace", None)
        response["actions"].append(
            {
                "set-cfg-path": {
                    "path": "interface {} subinterface {} admin-state".format(iface_name, subif_index),
                    "value": "enable",
                }
            }
        )
    else:
        # BGP just became established: start grace timer, keep interface down
        persistent_data["waiting-for-grace"] = True
        response["actions"].append({"reinvoke-with-delay": grace_period})

    response["persistent-data"] = persistent_data
    return json.dumps(response)
