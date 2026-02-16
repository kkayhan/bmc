# SRLinux Event Handler: Prevent Traffic Blackholing
#
# Purpose:
#   Ties a local interface's admin-state to the health of a BGP session.
#   If BGP goes down, the interface is disabled so the node stops attracting
#   traffic it cannot forward (i.e. prevents a routing blackhole).
#   When BGP re-establishes, a configurable grace period is applied before
#   re-enabling the interface, ensuring the session is stable and routes
#   have been exchanged before traffic is accepted again.
#
# How it works:
#   This script is registered as an SRLinux event-handler that monitors a
#   BGP neighbor session-state path. SRLinux invokes event_handler_main()
#   whenever the monitored path changes, passing the current state, user-
#   defined options, and any persistent data from prior invocations.
#
# State machine:
#   1. BGP NOT established  -> disable interface immediately
#   2. BGP becomes established -> start a grace-period timer (keep interface down)
#   3. Grace period expires & BGP still established -> enable interface
#   If BGP drops again during the grace period, step 1 cancels the timer.
#
# SRLinux configuration:
#   The Python script must be placed in /etc/opt/srlinux/eventmgr/ on the
#   SRLinux node. This is the default directory where the event-handler
#   framework looks for upython scripts.
#
#   Apply the following configuration to enable the event handler:
#
#   set / system event-handler instance prevent-blackhole admin-state enable
#   set / system event-handler instance prevent-blackhole upython-script prevent_blackhole.py
#   set / system event-handler instance prevent-blackhole paths [ "network-instance cust-vrf-1 protocols bgp neighbor 10.0.0.1 session-state" ]
#   set / system event-handler instance prevent-blackhole options object interface value irb0.10
#   set / system event-handler instance prevent-blackhole options object grace-period value 10
#
#   Configuration breakdown:
#     - admin-state enable        : activates the event-handler instance.
#     - upython-script            : references this file by name (looked up
#                                   in /etc/opt/srlinux/eventmgr/).
#     - paths                     : the YANG state path(s) to monitor. Here it
#                                   watches the BGP session-state of neighbor
#                                   10.0.0.1 inside network-instance cust-vrf-1.
#                                   Adjust the network-instance name and neighbor
#                                   IP to match your topology.
#     - options object interface  : the interface/subinterface to control,
#                                   written as "name.subif-index" (e.g. irb0.10).
#     - options object grace-period : time in seconds to wait after BGP comes
#                                   up before re-enabling the interface (here 10s).
#                                   Defaults to 30s if omitted.

import json


def event_handler_main(in_json_str):
    in_json = json.loads(in_json_str)

    # paths: list of monitored YANG paths and their current values.
    #        paths[0] carries the BGP neighbor session-state.
    paths = in_json["paths"]

    # options: user-defined key/value pairs configured on the event-handler.
    #   - "interface": the interface to control, in "name.subif" form (e.g. "irb0.10")
    #   - "grace-period": seconds to wait after BGP comes up before enabling
    #                     the interface (default 30s)
    options = in_json["options"]

    # persistent-data: dictionary that survives across invocations, used here
    # to track whether we are inside a grace-period wait.
    persistent_data = in_json.get("persistent-data", {})

    iface = options["interface"]
    # Convert grace period from seconds to milliseconds for the reinvoke-with-delay action
    grace_period = int(options.get("grace-period", "30")) * 1000

    # Split "irb0.10" into "irb0" and "10" to build the SRLinux schema path
    # for interface/<name>/subinterface/<index>/admin-state
    parts = iface.split(".")
    iface_name = parts[0]
    subif_index = parts[1]

    # Read the current BGP session state from the first monitored path
    state = paths[0].get("value", "") if paths else ""

    response = {"actions": []}

    if state != "established":
        # --- BGP is DOWN (or in any non-established state) ---
        # Immediately disable the interface so this node stops attracting
        # traffic it can no longer forward. Also clear any pending grace-period
        # flag, because if we were waiting to enable the interface, that wait
        # is now moot — BGP dropped again.
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
        # --- Grace period has elapsed and BGP is STILL established ---
        # This branch runs when the script is reinvoked after the delay timer
        # and the session has remained up, confirming stability. Now it is
        # safe to re-enable the interface and resume accepting traffic.
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
        # --- BGP just transitioned to ESTABLISHED ---
        # Don't enable the interface right away — the peer may flap, or routes
        # may not have converged yet. Instead, mark that we are waiting and
        # ask SRLinux to reinvoke this script after the grace period.
        # The interface stays disabled during this wait.
        persistent_data["waiting-for-grace"] = True
        response["actions"].append({"reinvoke-with-delay": grace_period})

    # Persist state for the next invocation
    response["persistent-data"] = persistent_data
    return json.dumps(response)
