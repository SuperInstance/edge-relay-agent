"""
Edge Research Relay — Core Research Relay Engine.

Bridges cloud ecosystems and edge ecosystems with asymmetric information flow.

Design principles:
1. Information asymmetry is fundamental — cloud and edge cannot fully approximate each other
2. Cloud -> Edge: curated, compressed, actionable (edge can't drink from the firehose)
3. Edge -> Cloud: raw, detailed, everything (cloud has capacity to process it all)
4. The relay sides with reality when theory and reality disagree

Standalone extraction from the edge-research-relay fleet module.
No external dependencies — uses only stdlib.
"""

import time
import json
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum


class MessageDirection(Enum):
    """Direction a message travels in the relay."""
    CLOUD_TO_EDGE = "cloud_to_edge"
    EDGE_TO_CLOUD = "edge_to_cloud"
    EDGE_TO_EDGE = "edge_to_edge"
    INTERNAL = "internal"


class MessagePriority(Enum):
    """Priority levels for relay messages."""
    CRITICAL = 0
    HIGH = 1
    MEDIUM = 2
    LOW = 3
    INFORMATIONAL = 4


# ─── CloudEdgeAsymmetry ────────────────────────────────────────────────────────

class CloudEdgeAsymmetry:
    """Encodes the fundamental information asymmetry between cloud and edge.

    Cloud has: full context, compute resources, fleet-wide data, model access
    Edge has: real-time sensor data, local environment, latency constraints, limited compute
    Neither can fully approximate the other — but the edge's blind spot is larger.
    """

    CLOUD_STRENGTHS: List[str] = [
        "architecture", "coordination", "fleet_wide_synthesis",
        "big_picture", "long_term_memory", "model_access",
    ]
    EDGE_STRENGTHS: List[str] = [
        "validation", "benchmarks", "real_world_timing",
        "sensor_fusion", "hardware_intuition", "failure_modes",
    ]
    CLOUD_BLIND_SPOTS: List[str] = [
        "raw_sensor_fidelity", "hardware_warmth", "serial_cable_length",
        "VRAM_pressure", "real_latency_jitter",
    ]
    EDGE_BLIND_SPOTS: List[str] = [
        "fleet_wide_context", "long_term_architecture",
        "coordination_across_vessels", "full_history",
    ]

    def __init__(self) -> None:
        self.divergence_log: List[dict] = []
        self.assumption_failures: List[dict] = []

    def cloud_can_approximate(self, aspect: str) -> bool:
        """Can the cloud approximate this edge aspect through benchmarks/specs?"""
        return aspect in self.EDGE_STRENGTHS or aspect in self.CLOUD_STRENGTHS

    def edge_can_approximate(self, aspect: str) -> bool:
        """Can the edge approximate this cloud aspect? Usually no."""
        return aspect in self.EDGE_STRENGTHS

    def log_divergence(self, cloud_assumption: str, edge_reality: str,
                       severity: float = 0.5, context: str = "") -> None:
        """Record a point where cloud assumption diverged from edge reality."""
        entry: dict = {
            "timestamp": time.time(),
            "cloud_assumption": cloud_assumption,
            "edge_reality": edge_reality,
            "severity": max(0.0, min(1.0, severity)),
            "context": context,
        }
        self.divergence_log.append(entry)
        if severity >= 0.7:
            self.assumption_failures.append(entry)

    def divergence_summary(self) -> dict:
        """Summary of recorded divergences."""
        total = len(self.divergence_log)
        failures = len(self.assumption_failures)
        avg_severity = (
            sum(d["severity"] for d in self.divergence_log) / total
            if total > 0 else 0.0
        )
        return {
            "total_divergences": total,
            "assumption_failures": failures,
            "average_severity": round(avg_severity, 4),
            "recent": self.divergence_log[-10:] if self.divergence_log else [],
        }

    def to_dict(self) -> dict:
        """Serialize asymmetry state to dictionary."""
        return {
            "cloud_strengths": self.CLOUD_STRENGTHS,
            "edge_strengths": self.EDGE_STRENGTHS,
            "cloud_blind_spots": self.CLOUD_BLIND_SPOTS,
            "edge_blind_spots": self.EDGE_BLIND_SPOTS,
            "divergence_count": len(self.divergence_log),
            "assumption_failures": len(self.assumption_failures),
            "divergence_summary": self.divergence_summary(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'CloudEdgeAsymmetry':
        """Deserialize asymmetry state from dictionary."""
        asym = cls()
        return asym


# ─── Data models ───────────────────────────────────────────────────────────────

@dataclass
class CloudSource:
    """A registered cloud data source."""
    source_id: str
    capabilities: List[str]
    registered_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "source_id": self.source_id,
            "capabilities": self.capabilities,
            "registered_at": self.registered_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'CloudSource':
        """Deserialize from dictionary."""
        return cls(
            source_id=data["source_id"],
            capabilities=data.get("capabilities", []),
            registered_at=data.get("registered_at", time.time()),
        )


@dataclass
class EdgeNode:
    """A registered edge device with constraints."""
    node_id: str
    capabilities: List[str]
    constraints: Dict[str, Any]
    registered_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "node_id": self.node_id,
            "capabilities": self.capabilities,
            "constraints": self.constraints,
            "registered_at": self.registered_at,
            "last_seen": self.last_seen,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'EdgeNode':
        """Deserialize from dictionary."""
        return cls(
            node_id=data["node_id"],
            capabilities=data.get("capabilities", []),
            constraints=data.get("constraints", {}),
            registered_at=data.get("registered_at", time.time()),
            last_seen=data.get("last_seen", time.time()),
        )


@dataclass
class ResearchQuery:
    """A research query submitted by the cloud."""
    query_id: str
    query_text: str
    source_id: str
    priority: MessagePriority = MessagePriority.MEDIUM
    created_at: float = field(default_factory=time.time)
    status: str = "pending"  # pending, sent, completed, failed

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "query_id": self.query_id,
            "query_text": self.query_text,
            "source_id": self.source_id,
            "priority": self.priority.value,
            "created_at": self.created_at,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ResearchQuery':
        """Deserialize from dictionary."""
        return cls(
            query_id=data["query_id"],
            query_text=data["query_text"],
            source_id=data["source_id"],
            priority=MessagePriority(data.get("priority", MessagePriority.MEDIUM.value)),
            created_at=data.get("created_at", time.time()),
            status=data.get("status", "pending"),
        )


@dataclass
class EdgeFinding:
    """A finding submitted by an edge node."""
    finding_id: str
    node_id: str
    data: Any
    query_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    priority: MessagePriority = MessagePriority.MEDIUM

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "finding_id": self.finding_id,
            "node_id": self.node_id,
            "data": self.data,
            "query_id": self.query_id,
            "created_at": self.created_at,
            "priority": self.priority.value,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'EdgeFinding':
        """Deserialize from dictionary."""
        return cls(
            finding_id=data["finding_id"],
            node_id=data["node_id"],
            data=data.get("data"),
            query_id=data.get("query_id"),
            created_at=data.get("created_at", time.time()),
            priority=MessagePriority(data.get("priority", MessagePriority.MEDIUM.value)),
        )


@dataclass
class RelayMessage:
    """A message routed through the relay."""
    message_id: str
    payload: Any
    direction: MessageDirection
    source: str
    destination: str
    priority: MessagePriority = MessagePriority.MEDIUM
    created_at: float = field(default_factory=time.time)
    size_bytes: int = 0

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "message_id": self.message_id,
            "payload": self.payload,
            "direction": self.direction.value,
            "source": self.source,
            "destination": self.destination,
            "priority": self.priority.value,
            "created_at": self.created_at,
            "size_bytes": self.size_bytes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'RelayMessage':
        """Deserialize from dictionary."""
        return cls(
            message_id=data["message_id"],
            payload=data.get("payload"),
            direction=MessageDirection(data["direction"]),
            source=data["source"],
            destination=data["destination"],
            priority=MessagePriority(data.get("priority", MessagePriority.MEDIUM.value)),
            created_at=data.get("created_at", time.time()),
            size_bytes=data.get("size_bytes", 0),
        )


# ─── ResearchRelay ─────────────────────────────────────────────────────────────

class ResearchRelay:
    """Main relay engine bridging cloud and edge research ecosystems.

    Manages registration, query submission, finding collection, compression,
    expansion, prioritization, batching, and intelligent message routing.
    """

    def __init__(self) -> None:
        self.asymmetry = CloudEdgeAsymmetry()
        self.cloud_sources: Dict[str, CloudSource] = {}
        self.edge_nodes: Dict[str, EdgeNode] = {}
        self.queries: Dict[str, ResearchQuery] = {}
        self.findings: Dict[str, EdgeFinding] = {}
        self.message_log: List[RelayMessage] = []
        self._id_counter: int = 0

    def _next_id(self) -> str:
        """Generate the next sequential relay ID."""
        self._id_counter += 1
        return f"relay-{self._id_counter:06d}"

    # ── Registration ──────────────────────────────────────────────────────

    def register_cloud_source(self, source_id: str,
                              capabilities: List[str]) -> CloudSource:
        """Register a cloud data source.

        Args:
            source_id: Unique identifier for the cloud source.
            capabilities: List of capability strings this source provides.

        Returns:
            The registered CloudSource instance.
        """
        source = CloudSource(source_id=source_id, capabilities=capabilities)
        self.cloud_sources[source_id] = source
        return source

    def register_edge_node(self, node_id: str, capabilities: List[str],
                           constraints: Optional[Dict[str, Any]] = None) -> EdgeNode:
        """Register an edge device with its capabilities and constraints.

        Args:
            node_id: Unique identifier for the edge node.
            capabilities: List of capability strings this node provides.
            constraints: Dictionary of hardware/resource constraints.

        Returns:
            The registered EdgeNode instance.
        """
        node = EdgeNode(
            node_id=node_id,
            capabilities=capabilities,
            constraints=constraints or {},
        )
        self.edge_nodes[node_id] = node
        return node

    def unregister_cloud_source(self, source_id: str) -> bool:
        """Unregister a cloud source by ID.

        Returns:
            True if the source was found and removed.
        """
        return self.cloud_sources.pop(source_id, None) is not None

    def unregister_edge_node(self, node_id: str) -> bool:
        """Unregister an edge node by ID.

        Returns:
            True if the node was found and removed.
        """
        return self.edge_nodes.pop(node_id, None) is not None

    # ── Query & Finding submission ─────────────────────────────────────────

    def submit_research_query(self, query_text: str, source_id: str = "",
                              priority: MessagePriority = MessagePriority.MEDIUM
                              ) -> ResearchQuery:
        """Cloud submits a research query for edge processing.

        Args:
            query_text: The research query text.
            source_id: ID of the submitting cloud source.
            priority: Message priority level.

        Returns:
            The created ResearchQuery instance.
        """
        query = ResearchQuery(
            query_id=self._next_id(),
            query_text=query_text,
            source_id=source_id or "unknown",
            priority=priority,
        )
        self.queries[query.query_id] = query
        return query

    def submit_edge_finding(self, node_id: str, data: Any,
                            query_id: Optional[str] = None,
                            priority: MessagePriority = MessagePriority.MEDIUM
                            ) -> EdgeFinding:
        """Edge submits a local finding for cloud consumption.

        Args:
            node_id: ID of the submitting edge node.
            data: Finding data (arbitrary structure).
            query_id: Optional query ID this finding responds to.
            priority: Message priority level.

        Returns:
            The created EdgeFinding instance.
        """
        finding = EdgeFinding(
            finding_id=self._next_id(),
            node_id=node_id,
            data=data,
            query_id=query_id,
            priority=priority,
        )
        self.findings[finding.finding_id] = finding
        return finding

    # ── Compression & Expansion ────────────────────────────────────────────

    def compress_for_edge(self, data: Any, bandwidth_limit: int = 1024) -> dict:
        """Compress cloud data for edge transmission.

        Reduces data to fit within bandwidth_limit bytes (estimated).
        Strategy: strip metadata, truncate text, keep essential fields.

        Args:
            data: Any serializable data structure.
            bandwidth_limit: Maximum allowed size in bytes.

        Returns:
            Dictionary with compressed data and metadata.
        """
        serialized = json.dumps(data, default=str)
        original_size = len(serialized.encode("utf-8"))

        if original_size <= bandwidth_limit:
            return {
                "compressed": data,
                "original_size": original_size,
                "compressed_size": original_size,
                "ratio": 1.0,
                "truncated": False,
            }

        # Compress: truncate text fields, keep structure
        compressed = self._strip_for_edge(data)
        serialized = json.dumps(compressed, default=str)
        compressed_size = len(serialized.encode("utf-8"))

        # If still too large, further truncate
        if compressed_size > bandwidth_limit:
            compressed = self._truncate_to_fit(serialized, bandwidth_limit)
            compressed_size = len(compressed.encode("utf-8"))

        return {
            "compressed": compressed,
            "original_size": original_size,
            "compressed_size": compressed_size,
            "ratio": round(compressed_size / original_size, 4) if original_size > 0 else 1.0,
            "truncated": True,
        }

    def expand_from_edge(self, data: Any,
                         context: Optional[Dict[str, Any]] = None) -> dict:
        """Expand edge data with cloud context.

        Edge findings are enriched with fleet-wide context from the cloud
        side — the cloud has capacity to process everything.

        Args:
            data: Edge finding data.
            context: Optional additional context to attach.

        Returns:
            Expanded data dictionary with cloud metadata.
        """
        context = context or {}
        return {
            "data": data,
            "context": context,
            "cloud_timestamp": time.time(),
            "edge_nodes_count": len(self.edge_nodes),
            "cloud_sources_count": len(self.cloud_sources),
        }

    def _strip_for_edge(self, data: Any) -> Any:
        """Recursively strip non-essential fields for edge transmission."""
        if isinstance(data, dict):
            stripped: Dict[str, Any] = {}
            for k, v in data.items():
                if k.startswith("_") or k in ("metadata", "debug_info", "full_history"):
                    continue
                stripped[k] = self._strip_for_edge(v)
            return stripped
        elif isinstance(data, list):
            return [self._strip_for_edge(item) for item in data[:20]]  # cap lists
        elif isinstance(data, str) and len(data) > 256:
            return data[:250] + "..."
        return data

    @staticmethod
    def _truncate_to_fit(serialized: str, limit: int) -> str:
        """Hard-truncate a JSON string to fit within limit bytes."""
        truncated = serialized[:limit]
        # Try to close any open JSON structures
        open_braces = truncated.count("{") - truncated.count("}")
        open_brackets = truncated.count("[") - truncated.count("]")
        truncated = truncated.rstrip() + "}" * open_braces + "]" * open_brackets
        return truncated[:limit]

    # ── Prioritization ─────────────────────────────────────────────────────

    def prioritize_queries(self, queries: List[ResearchQuery],
                           edge_capacity: int = 5) -> List[ResearchQuery]:
        """Prioritize which queries to send to edge based on capacity.

        Higher priority queries go first. Ties broken by recency.

        Args:
            queries: List of ResearchQuery instances to prioritize.
            edge_capacity: Maximum number of queries the edge can handle.

        Returns:
            Prioritized and truncated list of queries.
        """
        if not queries:
            return []
        sorted_queries = sorted(
            queries,
            key=lambda q: (q.priority.value, -q.created_at),
        )
        return sorted_queries[:edge_capacity]

    # ── Batching ───────────────────────────────────────────────────────────

    def batch_findings(self, findings: List[EdgeFinding],
                       max_batch_size: int = 10) -> List[List[EdgeFinding]]:
        """Batch edge findings for cloud consumption.

        Batches are ordered by priority (highest first).

        Args:
            findings: List of EdgeFinding instances.
            max_batch_size: Maximum items per batch.

        Returns:
            List of batches (lists of findings).
        """
        if not findings:
            return []
        sorted_findings = sorted(
            findings,
            key=lambda f: (f.priority.value, -f.created_at),
        )
        batches: List[List[EdgeFinding]] = []
        for i in range(0, len(sorted_findings), max_batch_size):
            batches.append(sorted_findings[i:i + max_batch_size])
        return batches

    # ── Message Routing ────────────────────────────────────────────────────

    def route_message(self, message: RelayMessage) -> dict:
        """Intelligent message routing between cloud, edge, and peers.

        Determines optimal routing based on message direction, source,
        and destination capabilities.

        Args:
            message: The RelayMessage to route.

        Returns:
            Routing plan with route path and actions.
        """
        routing: dict = {
            "message_id": message.message_id,
            "direction": message.direction.value,
            "source": message.source,
            "destination": message.destination,
            "route": [],
            "actions": [],
        }

        if message.direction == MessageDirection.CLOUD_TO_EDGE:
            if message.destination in self.edge_nodes:
                node = self.edge_nodes[message.destination]
                routing["route"].append("direct_to_edge")
                routing["actions"].append(f"deliver_to_{node.node_id}")
            else:
                routing["route"].append("broadcast_to_all_edges")
                for nid in self.edge_nodes:
                    routing["actions"].append(f"deliver_to_{nid}")

        elif message.direction == MessageDirection.EDGE_TO_CLOUD:
            routing["route"].append("direct_to_cloud")
            routing["actions"].append("store_in_cloud")

        elif message.direction == MessageDirection.EDGE_TO_EDGE:
            if message.destination in self.edge_nodes:
                routing["route"].append("peer_to_peer")
                routing["actions"].append(f"relay_to_{message.destination}")
            else:
                routing["route"].append("no_route")
                routing["actions"].append("destination_not_found")

        else:
            routing["route"].append("internal_processing")
            routing["actions"].append("process_locally")

        self.message_log.append(message)
        return routing

    # ── Status ─────────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Get comprehensive relay status."""
        return {
            "cloud_sources_count": len(self.cloud_sources),
            "edge_nodes_count": len(self.edge_nodes),
            "queries_count": len(self.queries),
            "findings_count": len(self.findings),
            "messages_routed": len(self.message_log),
            "asymmetry": self.asymmetry.divergence_summary(),
        }

    # ── Serialization ──────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize relay state to dictionary."""
        return {
            "asymmetry": self.asymmetry.to_dict(),
            "cloud_sources": {k: v.to_dict() for k, v in self.cloud_sources.items()},
            "edge_nodes": {k: v.to_dict() for k, v in self.edge_nodes.items()},
            "queries_count": len(self.queries),
            "findings_count": len(self.findings),
            "messages_routed": len(self.message_log),
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ResearchRelay':
        """Deserialize relay state from dictionary."""
        relay = cls()
        for sid, sd in data.get("cloud_sources", {}).items():
            relay.cloud_sources[sid] = CloudSource.from_dict(sd)
        for nid, nd in data.get("edge_nodes", {}).items():
            relay.edge_nodes[nid] = EdgeNode.from_dict(nd)
        return relay
