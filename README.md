# EVPN Data Center with WAN Peering - Containerlab

This [Containerlab](https://containerlab.dev/) project deploys a fully functional **EVPN/VXLAN data center fabric** interconnected to a **WAN/peering domain** via border-leaf switches. The entire lab runs on **Nokia SR Linux** (release 25.10.2) and demonstrates a realistic DC + WAN integration scenario with dual-homed servers, OSPF unnumbered underlay, iBGP EVPN overlay, and traffic blackhole prevention using event-handler automation.

## Quick Start

### Prerequisites

A Linux machine with [Containerlab](https://containerlab.dev/install/) installed. All required container images are pulled automatically during deployment.

### Clone and Deploy

```bash
git clone https://github.com/kkayhan/bmc.git
cd bmc
sudo containerlab deploy
```

### Destroy

```bash
sudo containerlab destroy
```

### Verify Connectivity

```bash
# Check server1 can reach server2 via external service
ssh admin@server1 ping 100.99.98.2

# Check server1 can reach server2 via internal service
ssh admin@server1 ping 10.10.10.2

# Check server1 can reach the anycast IRB gateway
ssh admin@server1 ping 100.99.98.254

# Check server1 can reach the remote "internet" IP on wan-core
ssh admin@server1 ping 123.123.123.123
```

### Accessing the Nodes

**SR Linux nodes** -- SSH directly using the node name. Containerlab handles credentials automatically:

```bash
ssh spine1
ssh b-leaf1
ssh leaf1
```

**Linux servers** (server1, server2) -- SSH using user `admin` with password `multit00l`:

```bash
ssh admin@server1
ssh admin@server2
```

### Useful SR Linux Commands

Once connected to an SR Linux node (e.g. `ssh spine1`), the following commands help inspect the running state of the fabric.

#### OSPF

**Show the full OSPF configuration in flat set-based format:**
```
info flat network-instance default protocols ospf
```
Displays the complete OSPF instance configuration including area assignments, interface types, and ECMP settings as flat `set` commands.

**Show OSPF neighbor adjacencies:**
```
show network-instance default protocols ospf neighbor
```
Lists all OSPF neighbors with their router-id, adjacency state, priority, and dead timer -- useful for verifying that all fabric links have formed full adjacencies.

#### BGP / EVPN

**Show the full BGP configuration in flat set-based format:**
```
info flat network-instance default protocols bgp
```
Displays the complete BGP configuration including AS number, address families, peer groups, route-reflector settings, and dynamic neighbor acceptance policies.

**Show BGP neighbor sessions:**
```
show network-instance default protocols bgp neighbor
```
Lists all BGP peers with their state, uptime, address-family, and route counts (Rx/Active/Tx) -- useful for confirming that all EVPN sessions are established and routes are being exchanged.

#### EVPN Bridge Table

**Show the MAC address table for the external access service:**
```
show network-instance l2_evpn_bond0 bridge-table mac-table all
```
Displays all MAC addresses learned in the `l2_evpn_bond0` mac-vrf, including locally learned MACs, EVPN-learned remote MACs, and EVPN-static entries (such as the anycast-gw MAC) -- useful for troubleshooting L2 forwarding and verifying EVPN Type-2 route distribution.

**Show the proxy ARP table:**
```
show network-instance l2_evpn_bond0 bridge-table proxy-arp all
```
Displays all IP-to-MAC bindings cached by the proxy ARP function -- useful for confirming that the leaf switch can answer ARP requests locally without flooding them across the VXLAN fabric.

#### WAN Peering (on border-leaves)

**Show eBGP neighbor sessions in the customer VRF:**
```
show network-instance cust-vrf-1 protocols bgp neighbor
```
Displays the eBGP peering status between the border-leaf and its PIC router inside `cust-vrf-1`, including session state, uptime, and IPv4-unicast route counts -- the session monitored by the blackhole prevention event handler.

**Show the IP route table for the customer VRF:**
```
show network-instance cust-vrf-1 route-table
```
Displays all IPv4 routes in `cust-vrf-1`, including locally connected subnets (IRB, peering links), BGP-learned remote prefixes from the WAN (such as `123.123.123.123/32`), and their next-hops -- useful for verifying end-to-end reachability between the DC and WAN.



## Topology

![Lab Topology](topology.png)

### Node Inventory

| Node | Role | Type | Loopback | AS |
|------|------|------|----------|----|
| **spine1** | Spine / Route Reflector | ixr-d3l | 192.168.100.100/32 | 65000 |
| **spine2** | Spine / Route Reflector | ixr-d3l | 192.168.100.200/32 | 65000 |
| **b-leaf1** | Border Leaf | ixr-d2l | 192.168.100.11/32 | 65000 |
| **b-leaf2** | Border Leaf | ixr-d2l | 192.168.100.12/32 | 65000 |
| **leaf1** | Leaf (server1 bond0/bond1 leg A) | ixr-d2l | 192.168.100.1/32 | 65000 |
| **leaf2** | Leaf (server1 bond0/bond1 leg B) | ixr-d2l | 192.168.100.2/32 | 65000 |
| **leaf3** | Leaf (server2 bond0/bond1 leg A) | ixr-d2l | 192.168.100.3/32 | 65000 |
| **leaf4** | Leaf (server2 bond0/bond1 leg B) | ixr-d2l | 192.168.100.4/32 | 65000 |
| **dic1** | DIC Peering Router | ixr-d2l | 100.1.1.101/32 | 1 |
| **dic2** | DIC Peering Router | ixr-d2l | 100.1.1.102/32 | 1 |
| **pic1** | PIC Peering Router | ixr-d2l | 100.1.1.201/32 | 1 |
| **pic2** | PIC Peering Router | ixr-d2l | 100.1.1.202/32 | 1 |
| **wan-core** | WAN Core / Route Reflector | ixr-d3l | 100.1.1.100/32 | 1 |
| **server1** | Linux server (multitool) | linux | - | - |
| **server2** | Linux server (multitool) | linux | - | - |

## Architecture Details

### Underlay: OSPF Unnumbered

The DC fabric underlay uses **OSPFv2 with IPv4 unnumbered point-to-point interfaces**. Every fabric-facing link borrows its IPv4 address from the node's `system0.0` loopback instead of having a dedicated /31 subnet assigned.

#### What is OSPF Unnumbered on SR Linux?

As described in the [Nokia SR Linux documentation](https://documentation.nokia.com/srlinux/25-10/books/interfaces/subinterfaces.html#configuring-ipv4-unnumbered-interface):

> An IPv4 unnumbered subinterface does not have an explicitly configured IPv4 address. Instead, it **borrows the IPv4 address from another numbered interface** (typically a loopback or system interface) to use as the source address for packets sent on that link.

This approach offers significant operational advantages:

- **No per-link IP addressing** -- eliminates the need to plan and allocate unique /31 subnets for every point-to-point link in the fabric, drastically simplifying IP address management.
- **Plug-and-play provisioning** -- new leaf or spine nodes can be cabled and brought up without coordinating link-level IP addressing with neighbors.
- **Reduced CPM-filter maintenance** -- since all fabric interfaces share the loopback address, control plane protection rules do not need updating when new links are added.
- **Full routing protocol support** -- SR Linux supports unnumbered interfaces with OSPFv2/v3 and IS-IS for point-to-point adjacencies, as well as iBGP and multi-hop eBGP sessions over them.

In this lab, all spine-to-leaf and spine-to-border-leaf links are configured as:

```
set / interface ethernet-1/49 subinterface 1 ipv4 unnumbered admin-state enable
set / interface ethernet-1/49 subinterface 1 ipv4 unnumbered interface system0.0
```

OSPF runs in **area 0.0.0.0** across the DC fabric (spines, leaves, border-leaves) and in **area 1.1.1.1** across the WAN domain (wan-core, DICs, PICs). All OSPF interfaces are configured as `point-to-point` with `max-ecmp-paths 64` for maximum load balancing. BFD is enabled on all system0.0 loopbacks for fast failure detection.

### Overlay: iBGP EVPN with VXLAN

The overlay control plane uses **iBGP EVPN** (address-family `evpn`) within AS 65000 across the entire DC fabric. The two **spine routers act as route reflectors** (cluster-id `192.168.100.0`) with dynamic neighbor acceptance -- any peer from AS 65000 is automatically accepted into the `fabric` peer group:

```
set / network-instance default protocols bgp group fabric route-reflector client true
set / network-instance default protocols bgp group fabric route-reflector cluster-id 192.168.100.0
set / network-instance default protocols bgp dynamic-neighbors accept match 0.0.0.0/0 peer-group fabric
set / network-instance default protocols bgp dynamic-neighbors accept match 0.0.0.0/0 allowed-peer-as [ 65000 ]
```

All leaves and border-leaves peer explicitly with spine1 (`192.168.100.100`) and spine2 (`192.168.100.200`). BGP add-paths (send-max 16) is enabled for optimal multi-path forwarding.

Similarly, in the WAN domain, **wan-core** serves as the route reflector for AS 1 with dynamic neighbor acceptance, and all DIC/PIC routers peer with it (`100.1.1.100`).

### EVPN Services

#### External Access Service -- `cust-vrf-1` (ip-vrf) + `l2_evpn_bond0` (mac-vrf)

This is the primary service providing **WAN/internet connectivity** for the servers:

- **`l2_evpn_bond0`** -- A Layer 2 mac-vrf (VNI 1, EVI 1) that bridges server traffic arriving on `bond0` (VLAN 10) across the VXLAN fabric. Present on all leaf and border-leaf switches.
- **`cust-vrf-1`** -- A Layer 3 ip-vrf (VNI 100, EVI 100) on the border-leaves that provides the **anycast IRB gateway** for the servers and peers with the WAN via eBGP.

The **IRB gateway** is centrally configured on both border-leaves as an EVPN anycast-gw interface:

```
set / interface irb0 subinterface 10 ipv4 address 100.99.98.254/24 anycast-gw true
set / interface irb0 subinterface 10 anycast-gw virtual-router-id 10
set / interface irb0 subinterface 10 anycast-gw anycast-gw-mac 00:00:00:10:10:10
```

Both border-leaves advertise the same gateway IP (`100.99.98.254`) and MAC (`00:00:00:10:10:10`), ensuring consistent first-hop behavior regardless of which border-leaf the traffic reaches.

#### Internal Service -- `internal_evpn_bond1` (mac-vrf)

- A pure **Layer 2 mac-vrf** (VNI 2, EVI 2) for intra-server communication via `bond1` (VLAN 10).
- Subnet: `10.10.10.0/24` -- server1 is `10.10.10.1`, server2 is `10.10.10.2`.
- **No external gateway or WAN access** -- this service is isolated for east-west server traffic only.

### DC-to-WAN Interconnection

The border-leaves connect to the WAN via **LAG interfaces with VLAN (dot1q) encapsulation**:

| Border Leaf | WAN Router | LAG | VLAN | Peering IPs |
|-------------|-----------|-----|------|-------------|
| b-leaf1 | dic1 | lag1 (e1-1, e1-2) | - | - |
| b-leaf1 | pic1 | lag2 (e1-3, e1-4) | VLAN 1 | 10.0.0.0/31 (b-leaf1: .0, pic1: .1) |
| b-leaf2 | dic2 | lag1 (e1-1, e1-2) | - | - |
| b-leaf2 | pic2 | lag2 (e1-3, e1-4) | VLAN 1 | 10.0.0.2/31 (b-leaf2: .2, pic2: .3) |

Over these VLAN dot1q interfaces, **eBGP peering** runs inside `cust-vrf-1` between the border-leaves (AS 65111) and the PIC routers (AS 111), with BFD enabled for fast convergence:

- **b-leaf1** `cust-vrf-1` peers with **pic1** at `10.0.0.1` (peer-as 111)
- **b-leaf2** `cust-vrf-1` peers with **pic2** at `10.0.0.3` (peer-as 111)

The PIC routers in turn extend the `cust-vrf-1` service into the WAN via EVPN/VXLAN (VNI 111, EVI 111), making WAN-originated routes (including `123.123.123.123/32`) reachable from the DC fabric.

### Server Connectivity

Each server is dual-homed to a pair of leaf switches using **two LACP bonds (802.3ad)**:

| Bond | Interfaces | Leaf Pair | VLAN | IP Address | Purpose |
|------|-----------|-----------|------|------------|---------|
| **bond0** | eth1, eth2 | leaf1/leaf2 (server1), leaf3/leaf4 (server2) | 10 | 100.99.98.1/24 (s1), 100.99.98.2/24 (s2) | External access via WAN |
| **bond1** | eth3, eth4 | leaf1/leaf2 (server1), leaf3/leaf4 (server2) | 10 | 10.10.10.1/24 (s1), 10.10.10.2/24 (s2) | Internal server-to-server |

Default route on both servers: `100.99.98.254` (the anycast IRB gateway on border-leaves).

#### EVPN Multi-Homing (All-Active)

Each bond is backed by an **EVPN Ethernet Segment (ES)** with all-active multi-homing, ensuring both leaf switches forward traffic simultaneously:

| Server | Bond | ESI | Leaf Pair |
|--------|------|-----|-----------|
| server1 | bond0 | 00:00:10:10:10:10:10:10:10:10 | leaf1, leaf2 |
| server1 | bond1 | 00:00:11:11:11:11:11:11:11:11 | leaf1, leaf2 |
| server2 | bond0 | 00:00:20:20:20:20:20:20:20:20 | leaf3, leaf4 |
| server2 | bond1 | 00:00:21:21:21:21:21:21:21:21 | leaf3, leaf4 |

The LACP system-id MACs are synchronized across leaf pairs (`00:11:11:11:11:11` for bond0/lag1, `00:22:22:22:22:22` for bond1/lag2) so the server sees a single logical link-aggregation partner.

### Proxy ARP

**Proxy ARP with dynamic learning** is enabled on all leaf switches for both `l2_evpn_bond0` and `internal_evpn_bond1` mac-vrf instances:

```
set / network-instance l2_evpn_bond0 bridge-table proxy-arp admin-state enable
set / network-instance l2_evpn_bond0 bridge-table proxy-arp dynamic-learning admin-state enable
```

This avoids ARP flooding across the VXLAN fabric -- ARP requests from the servers are answered locally by the leaf switch using information learned via EVPN, significantly reducing broadcast traffic.

### Traffic Blackhole Prevention (Event Handler)

A critical automation piece on the border-leaves: the **`prevent_blackhole.py` event handler script** monitors the BGP session between each border-leaf and its PIC router. If the eBGP session inside `cust-vrf-1` goes down, the script **immediately disables the `irb0.10` interface** on that border-leaf. This prevents the border-leaf from continuing to attract traffic (via the anycast gateway) that it can no longer forward to the WAN, which would result in a **routing blackhole**.

The state machine works as follows:

1. **BGP session goes down** -- `irb0.10` is immediately disabled, stopping the node from attracting traffic it cannot forward.
2. **BGP session comes back up** -- a configurable **grace period** (10 seconds) starts; the interface stays down during this time to ensure session stability and route convergence.
3. **Grace period expires with BGP still established** -- `irb0.10` is re-enabled, and the border-leaf resumes its gateway role.
4. **BGP drops again during the grace period** -- the timer is cancelled and the interface remains disabled.

Configuration on b-leaf1:
```
set / system event-handler instance prevent-blackhole admin-state enable
set / system event-handler instance prevent-blackhole upython-script prevent_blackhole.py
set / system event-handler instance prevent-blackhole paths [ "network-instance cust-vrf-1 protocols bgp neighbor 10.0.0.1 session-state" ]
set / system event-handler instance prevent-blackhole options object interface value irb0.10
set / system event-handler instance prevent-blackhole options object grace-period value 10
```

The script is bind-mounted into each border-leaf container at `/etc/opt/srlinux/eventmgr/prevent_blackhole.py`.

### Remote Reachability Test

A loopback address **`123.123.123.123/32`** is configured on `wan-core` inside `cust-vrf-1` and serves as a remote "internet" destination. Both servers can reach this address via their default route through the anycast IRB gateway on the border-leaves, through the eBGP peering with the PICs, and across the WAN EVPN fabric to wan-core.

**Expected reachability from both servers:**

| From | To | Expected |
|------|----|----------|
| server1 / server2 | server2 / server1 (`100.99.98.x` via bond0) | Reachable |
| server1 / server2 | server2 / server1 (`10.10.10.x` via bond1) | Reachable |
| server1 / server2 | IRB anycast GW `100.99.98.254` | Reachable |
| server1 / server2 | Remote IP `123.123.123.123` | Reachable |
