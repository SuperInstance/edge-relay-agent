#!/usr/bin/env python3
"""
Edge Relay Agent — CLI Interface.

Standalone CLI for the edge research relay agent with subcommands for:
- serve: start the relay server
- register-cloud: register a cloud source
- register-edge: register an edge node
- route: route a message between sources
- discover: discover agents on the network
- bandwidth: show bandwidth statistics
- onboard: set up the agent
- status: show agent status

No external dependencies — uses only stdlib.
"""

import argparse
import json
import sys
import os
import time
import socket
from typing import Optional, List, Dict, Any


def _load_state(state_dir: str) -> Optional[dict]:
    """Load agent state from disk."""
    state_path = os.path.join(state_dir, "state.json")
    if os.path.exists(state_path):
        try:
            with open(state_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _save_state(state_dir: str, state: dict) -> None:
    """Save agent state to disk."""
    os.makedirs(state_dir, exist_ok=True)
    state_path = os.path.join(state_dir, "state.json")
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2, default=str)


def _get_state_dir() -> str:
    """Get the default state directory."""
    xdg = os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state"))
    return os.path.join(xdg, "edge-relay-agent")


def _print_json(data: Any, indent: int = 2) -> None:
    """Pretty-print JSON to stdout."""
    print(json.dumps(data, indent=indent, default=str))


# ─── Command Handlers ─────────────────────────────────────────────────────────

def cmd_serve(args: argparse.Namespace) -> int:
    """Start the relay server (foreground mode)."""
    # Lazy imports to keep startup fast
    from relay import ResearchRelay, MessageDirection, MessagePriority, RelayMessage
    from bandwidth import BandwidthBudget
    from discovery import DiscoveryService

    state_dir = args.state_dir or _get_state_dir()
    agent_id = args.agent_id or f"relay-{socket.gethostname()}"
    port = args.port

    print(f"[edge-relay-agent] Starting relay server...")
    print(f"  Agent ID: {agent_id}")
    print(f"  Host:     {socket.gethostname()}")
    print(f"  Port:     {port}")
    print(f"  State:    {state_dir}")

    # Initialize components
    relay = ResearchRelay()
    budget = BandwidthBudget(total_bps=args.bandwidth)
    discovery = DiscoveryService(
        agent_id=agent_id,
        capabilities=["relay", "research", "routing"],
        port=port,
    )

    # Register self in discovery
    discovery.register_self()

    # Load previous state if available
    state = _load_state(state_dir)
    if state:
        if "relay" in state:
            loaded = ResearchRelay.from_dict(state["relay"])
            for sid, src in loaded.cloud_sources.items():
                relay.cloud_sources[sid] = src
            for nid, node in loaded.edge_nodes.items():
                relay.edge_nodes[nid] = node
            print(f"  Restored {len(loaded.cloud_sources)} cloud sources, "
                  f"{len(loaded.edge_nodes)} edge nodes")
        if "discovery" in state:
            for aid, ad in state["discovery"].get("agents", {}).items():
                discovery.discover_agent(
                    agent_id=ad.get("agent_id", aid),
                    hostname=ad.get("hostname", ""),
                    capabilities=ad.get("capabilities", []),
                    port=ad.get("port", 0),
                )

    # Save initial state
    _save_state(state_dir, {
        "relay": relay.to_dict(),
        "discovery": discovery.to_dict(),
        "bandwidth": budget.to_dict(),
        "started_at": time.time(),
    })

    # In a real implementation, this would start a network server loop.
    # For the standalone CLI agent, we print status and wait.
    print(f"\n[edge-relay-agent] Relay server running (PID {os.getpid()})")
    print(f"[edge-relay-agent] Press Ctrl+C to stop.\n")

    try:
        # Periodic status output
        while True:
            time.sleep(10)
            health = discovery.health_report()
            active = health.get("healthy", 0)
            total = health.get("total_agents", 0)
            print(f"[heartbeat] agents={total} healthy={active} "
                  f"sources={len(relay.cloud_sources)} "
                  f"edges={len(relay.edge_nodes)} "
                  f"msgs={len(relay.message_log)}")
    except KeyboardInterrupt:
        pass

    # Save final state
    _save_state(state_dir, {
        "relay": relay.to_dict(),
        "discovery": discovery.to_dict(),
        "bandwidth": budget.to_dict(),
        "stopped_at": time.time(),
    })
    print(f"\n[edge-relay-agent] Server stopped. State saved to {state_dir}")
    return 0


def cmd_register_cloud(args: argparse.Namespace) -> int:
    """Register a cloud source."""
    from relay import ResearchRelay

    state_dir = args.state_dir or _get_state_dir()
    name = args.name
    url = args.url
    capabilities = [c.strip() for c in args.capabilities.split(",") if c.strip()]

    state = _load_state(state_dir) or {}
    relay_data = state.get("relay", {})
    relay = ResearchRelay.from_dict(relay_data)
    for sid, sd in relay_data.get("cloud_sources", {}).items():
        relay.cloud_sources[sid] = relay.cloud_sources.get(sid) or __import__(
            "relay", fromlist=["CloudSource"]).CloudSource.from_dict(sd)

    source = relay.register_cloud_source(name, capabilities)

    # Save updated state
    state["relay"] = relay.to_dict()
    _save_state(state_dir, state)

    result = {
        "status": "registered",
        "source_id": name,
        "url": url,
        "capabilities": capabilities,
        "registered_at": source.registered_at,
    }
    _print_json(result)
    return 0


def cmd_register_edge(args: argparse.Namespace) -> int:
    """Register an edge node."""
    from relay import ResearchRelay, EdgeNode

    state_dir = args.state_dir or _get_state_dir()
    node_id = args.id
    capabilities = [c.strip() for c in args.capabilities.split(",") if c.strip()]

    state = _load_state(state_dir) or {}
    relay = ResearchRelay.from_dict(state.get("relay", {}))

    constraints = {}
    if args.constraints:
        for pair in args.constraints.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                try:
                    constraints[k.strip()] = int(v.strip())
                except ValueError:
                    try:
                        constraints[k.strip()] = float(v.strip())
                    except ValueError:
                        constraints[k.strip()] = v.strip()

    node = relay.register_edge_node(node_id, capabilities, constraints)

    state["relay"] = relay.to_dict()
    _save_state(state_dir, state)

    result = {
        "status": "registered",
        "node_id": node_id,
        "capabilities": capabilities,
        "constraints": constraints,
        "registered_at": node.registered_at,
    }
    _print_json(result)
    return 0


def cmd_route(args: argparse.Namespace) -> int:
    """Route a message between sources."""
    from relay import ResearchRelay, RelayMessage, MessageDirection, MessagePriority

    state_dir = args.state_dir or _get_state_dir()

    state = _load_state(state_dir) or {}
    relay = ResearchRelay.from_dict(state.get("relay", {}))

    # Parse direction
    dir_map = {
        "c2e": MessageDirection.CLOUD_TO_EDGE,
        "cloud-to-edge": MessageDirection.CLOUD_TO_EDGE,
        "e2c": MessageDirection.EDGE_TO_CLOUD,
        "edge-to-cloud": MessageDirection.EDGE_TO_CLOUD,
        "e2e": MessageDirection.EDGE_TO_EDGE,
        "edge-to-edge": MessageDirection.EDGE_TO_EDGE,
        "internal": MessageDirection.INTERNAL,
    }
    direction = dir_map.get(args.direction.lower(), MessageDirection.INTERNAL)

    # Parse priority
    pri_map = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    priority = MessagePriority(pri_map.get(args.priority.lower(), 2))

    message = RelayMessage(
        message_id=f"msg-{int(time.time() * 1000)}",
        payload=args.message,
        direction=direction,
        source=args.source,
        destination=args.target,
        priority=priority,
    )

    routing = relay.route_message(message)

    state["relay"] = relay.to_dict()
    _save_state(state_dir, state)

    _print_json(routing)
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    """Discover agents on the network."""
    from discovery import DiscoveryService

    state_dir = args.state_dir or _get_state_dir()
    agent_id = args.agent_id or f"relay-{socket.gethostname()}"

    state = _load_state(state_dir) or {}
    discovery = DiscoveryService.from_dict(state.get("discovery", {"agent_id": agent_id}))

    # Register self
    discovery.register_self()

    if args.health:
        report = discovery.health_report()
        _print_json(report)
    elif args.capabilities:
        caps = discovery.registry.all_capabilities()
        for cap in caps:
            agents = discovery.find_capable(cap)
            print(f"  {cap}: {[a.agent_id for a in agents]}")
        _print_json({"total_capabilities": len(caps)})
    else:
        agents = discovery.registry.all_agents()
        _print_json({
            "total_agents": len(agents),
            "agents": [a.to_dict() for a in agents],
        })

    state["discovery"] = discovery.to_dict()
    _save_state(state_dir, state)
    return 0


def cmd_bandwidth(args: argparse.Namespace) -> int:
    """Show bandwidth statistics."""
    from bandwidth import BandwidthBudget, CompressionEngine, CompressionStrategy

    state_dir = args.state_dir or _get_state_dir()

    state = _load_state(state_dir) or {}
    budget = BandwidthBudget.from_dict(state.get("bandwidth", {}))

    if args.verbose:
        bw_info = budget.available_bandwidth()
        engine = CompressionEngine()
        # Demonstrate compression stats
        _print_json({
            "bandwidth_budget": bw_info,
            "compression_strategies": [s.value for s in CompressionStrategy],
            "tip": "Use the CompressionEngine for optimizing edge-bound payloads",
        })
    else:
        _print_json(budget.available_bandwidth())
    return 0


def cmd_onboard(args: argparse.Namespace) -> int:
    """Set up the agent for the first time."""
    from relay import ResearchRelay
    from bandwidth import BandwidthBudget
    from discovery import DiscoveryService

    state_dir = args.state_dir or _get_state_dir()
    agent_id = args.agent_id or f"relay-{socket.gethostname()}"

    if os.path.exists(os.path.join(state_dir, "state.json")) and not args.force:
        print(f"[edge-relay-agent] State already exists at {state_dir}")
        print(f"  Use --force to re-onboard and overwrite existing state.")
        return 1

    capabilities = ["relay", "research", "routing"]
    if args.extra_capabilities:
        capabilities.extend(
            [c.strip() for c in args.extra_capabilities.split(",") if c.strip()]
        )

    relay = ResearchRelay()
    budget = BandwidthBudget(total_bps=args.bandwidth)
    discovery = DiscoveryService(
        agent_id=agent_id,
        capabilities=capabilities,
        port=args.port,
    )
    discovery.register_self()

    # Save state
    _save_state(state_dir, {
        "relay": relay.to_dict(),
        "discovery": discovery.to_dict(),
        "bandwidth": budget.to_dict(),
        "onboarded_at": time.time(),
        "version": "1.0.0",
    })

    result = {
        "status": "onboarded",
        "agent_id": agent_id,
        "hostname": socket.gethostname(),
        "capabilities": capabilities,
        "state_dir": state_dir,
        "bandwidth_bps": args.bandwidth,
        "port": args.port,
    }
    _print_json(result)

    print(f"\n[edge-relay-agent] Agent onboarded successfully!")
    print(f"  Run 'edge-relay-agent serve' to start the relay server.")
    print(f"  Run 'edge-relay-agent status' to check agent status.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show agent status."""
    state_dir = args.state_dir or _get_state_dir()

    state = _load_state(state_dir)
    if not state:
        _print_json({
            "status": "not_onboarded",
            "message": f"No state found at {state_dir}. Run 'onboard' first.",
        })
        return 1

    from discovery import DiscoveryService
    discovery = DiscoveryService.from_dict(state.get("discovery", {}))

    result = {
        "status": "active",
        "agent_id": state.get("discovery", {}).get("agent_id", "unknown"),
        "state_dir": state_dir,
        "onboarded_at": state.get("onboarded_at"),
        "version": state.get("version", "unknown"),
        "cloud_sources": state.get("relay", {}).get("cloud_sources", {}),
        "edge_nodes": state.get("relay", {}).get("edge_nodes", {}),
        "messages_routed": state.get("relay", {}).get("messages_routed", 0),
        "discovery": {
            "total_agents": discovery.registry.size,
            "capabilities": discovery.registry.all_capabilities(),
        },
    }

    # Add file info
    state_path = os.path.join(state_dir, "state.json")
    if os.path.exists(state_path):
        stat = os.stat(state_path)
        result["state_file"] = {
            "size_bytes": stat.st_size,
            "modified": stat.st_mtime,
        }

    _print_json(result)
    return 0


# ─── Argument Parser ───────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="edge-relay-agent",
        description="Edge Relay Agent — standalone research relay for cloud-edge communication",
    )
    parser.add_argument(
        "--state-dir",
        default=None,
        help="Directory for agent state storage (default: ~/.local/state/edge-relay-agent)",
    )

    sub = parser.add_subparsers(dest="command", help="Available commands")

    # serve
    p_serve = sub.add_parser("serve", help="Start the relay server")
    p_serve.add_argument("--agent-id", default=None, help="Agent identifier")
    p_serve.add_argument("--port", type=int, default=8090, help="Listen port")
    p_serve.add_argument("--bandwidth", type=int, default=1024, help="Bandwidth budget (bytes/sec)")
    p_serve.set_defaults(func=cmd_serve)

    # register-cloud
    p_rc = sub.add_parser("register-cloud", help="Register a cloud source")
    p_rc.add_argument("url", help="Cloud source URL")
    p_rc.add_argument("--name", required=True, help="Source name/ID")
    p_rc.add_argument("--capabilities", required=True, help="Comma-separated capabilities")
    p_rc.set_defaults(func=cmd_register_cloud)

    # register-edge
    p_re = sub.add_parser("register-edge", help="Register an edge node")
    p_re.add_argument("id", help="Edge node ID")
    p_re.add_argument("--capabilities", required=True, help="Comma-separated capabilities")
    p_re.add_argument("--constraints", default="", help="Comma-separated key=value constraints")
    p_re.set_defaults(func=cmd_register_edge)

    # route
    p_route = sub.add_parser("route", help="Route a message between sources")
    p_route.add_argument("message", help="Message payload (text)")
    p_route.add_argument("--from", dest="source", required=True, help="Source ID")
    p_route.add_argument("--to", dest="target", required=True, help="Target ID")
    p_route.add_argument("--direction", default="c2e",
                         help="Direction: c2e, e2c, e2e, internal")
    p_route.add_argument("--priority", default="medium",
                         help="Priority: critical, high, medium, low, info")
    p_route.set_defaults(func=cmd_route)

    # discover
    p_disc = sub.add_parser("discover", help="Discover agents on the network")
    p_disc.add_argument("--agent-id", default=None, help="Local agent ID")
    p_disc.add_argument("--health", action="store_true", help="Show health report")
    p_disc.add_argument("--capabilities", action="store_true", help="List by capability")
    p_disc.set_defaults(func=cmd_discover)

    # bandwidth
    p_bw = sub.add_parser("bandwidth", help="Show bandwidth statistics")
    p_bw.add_argument("--verbose", "-v", action="store_true", help="Show detailed info")
    p_bw.set_defaults(func=cmd_bandwidth)

    # onboard
    p_onb = sub.add_parser("onboard", help="Set up the agent for the first time")
    p_onb.add_argument("--agent-id", default=None, help="Agent identifier")
    p_onb.add_argument("--port", type=int, default=8090, help="Listen port")
    p_onb.add_argument("--bandwidth", type=int, default=1024, help="Bandwidth budget (bytes/sec)")
    p_onb.add_argument("--extra-capabilities", default="",
                       help="Additional comma-separated capabilities")
    p_onb.add_argument("--force", action="store_true", help="Overwrite existing state")
    p_onb.set_defaults(func=cmd_onboard)

    # status
    p_stat = sub.add_parser("status", help="Show agent status")
    p_stat.set_defaults(func=cmd_status)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point for the CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    # Ensure state_dir is available on all commands
    if not hasattr(args, "state_dir"):
        args.state_dir = None

    try:
        return args.func(args)
    except Exception as e:
        print(f"[edge-relay-agent] Error: {e}", file=sys.stderr)
        if os.environ.get("EDGE_RELAY_DEBUG"):
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
