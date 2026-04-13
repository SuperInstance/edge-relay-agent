"""
Tender Type System — Specialized message carriers for cloud-edge information routing.

The four tender types from the architecture docs:
1. ResearchTender — carries findings between cloud labs and edge labs
2. DataTender — batches and packages big data for edge consumption
3. PriorityTender — translates urgency between realities
4. ContextTender — synchronizes context between cloud and edge

Standalone extraction from the edge-research-relay fleet module.
No external dependencies — uses only stdlib.
"""

import time
import json
import hashlib
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from enum import Enum


# ─── ResearchTender ────────────────────────────────────────────────────────────

class ResearchTender:
    """Carries findings between cloud labs and edge labs.

    Compresses cloud research specs for edge bandwidth constraints.
    Formats edge findings back for cloud consumption.
    Tracks research session state across the relay.
    """

    def __init__(self) -> None:
        self.sessions: Dict[str, dict] = {}
        self.compression_ratio_target: float = 0.3  # target 30% of original size

    def compress_query(self, query_text: str, bandwidth_limit: int = 512) -> dict:
        """Compress a research query to fit edge bandwidth.

        Strips verbose language, extracts key terms, truncates.
        """
        original = query_text
        original_size = len(original.encode("utf-8"))

        # Extract sentences, keep only first N that fit
        sentences = [
            s.strip()
            for s in original.replace("\n", ".").split(".")
            if s.strip()
        ]

        compressed_parts: List[str] = []
        current_size = 0
        for sentence in sentences:
            part_bytes = (sentence + ". ").encode("utf-8")
            if current_size + len(part_bytes) > bandwidth_limit:
                break
            compressed_parts.append(sentence)
            current_size += len(part_bytes)

        compressed = ". ".join(compressed_parts) if compressed_parts else ""

        # If even one sentence doesn't fit, hard truncate
        if not compressed and original:
            truncated = original[:bandwidth_limit]
            compressed = truncated.rstrip()

        compressed_size = len(compressed.encode("utf-8"))
        return {
            "compressed_query": compressed,
            "original_size": original_size,
            "compressed_size": compressed_size,
            "ratio": round(compressed_size / original_size, 4) if original_size > 0 else 1.0,
            "truncated": compressed_size < original_size,
        }

    def format_finding(self, finding_data: Any, query_id: str = "",
                       node_id: str = "") -> dict:
        """Format an edge finding for cloud consumption.

        The cloud can handle everything, so we enrich with metadata.
        """
        return {
            "query_id": query_id,
            "node_id": node_id,
            "finding_data": finding_data,
            "received_at": time.time(),
            "data_size": len(json.dumps(finding_data, default=str).encode("utf-8")),
        }

    def start_session(self, session_id: str, query: str) -> dict:
        """Start a new research session tracking cloud->edge->cloud flow."""
        session: dict = {
            "session_id": session_id,
            "query": query,
            "started_at": time.time(),
            "status": "active",
            "findings_received": [],
            "query_sent": False,
            "completed_at": None,
        }
        self.sessions[session_id] = session
        return session

    def add_session_finding(self, session_id: str, finding_data: Any) -> None:
        """Add a finding to an existing session."""
        session = self.sessions.get(session_id)
        if session:
            session["findings_received"].append({
                "data": finding_data,
                "received_at": time.time(),
            })

    def complete_session(self, session_id: str) -> dict:
        """Mark a research session as completed."""
        session = self.sessions.get(session_id)
        if session:
            session["status"] = "completed"
            session["completed_at"] = time.time()
        return session or {}

    def to_dict(self) -> dict:
        """Serialize tender state to dictionary."""
        return {
            "compression_ratio_target": self.compression_ratio_target,
            "sessions": self.sessions,
            "active_sessions": sum(
                1 for s in self.sessions.values() if s["status"] == "active"
            ),
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ResearchTender':
        """Deserialize tender state from dictionary."""
        tender = cls()
        tender.compression_ratio_target = data.get("compression_ratio_target", 0.3)
        tender.sessions = data.get("sessions", {})
        return tender


# ─── DataTender ────────────────────────────────────────────────────────────────

class DataTender:
    """Batches and packages big data for edge consumption.

    Accumulates cloud events (model outputs, trust updates, capability changes).
    Batches into size-limited chunks. Priority ordering with deduplication.
    """

    EVENT_PRIORITY: Dict[str, int] = {
        "trust": 0,       # trust events are highest priority
        "capability": 1,   # capability changes are second
        "model": 2,        # model outputs are third
        "general": 3,      # general events are lowest
    }

    def __init__(self) -> None:
        self.accumulator: List[dict] = []
        self.seen_hashes: set = set()
        self.dedup_count: int = 0

    def add_event(self, event_type: str, data: Any, event_id: str = "") -> dict:
        """Add a cloud event to the accumulator.

        Returns info about whether it was accepted or deduplicated.
        """
        # Create dedup hash
        raw = json.dumps(
            {"type": event_type, "data": data}, sort_keys=True, default=str
        )
        event_hash = hashlib.md5(raw.encode()).hexdigest()

        if event_hash in self.seen_hashes:
            self.dedup_count += 1
            return {
                "accepted": False,
                "reason": "duplicate",
                "dedup_count": self.dedup_count,
            }

        self.seen_hashes.add(event_hash)
        event: dict = {
            "type": event_type,
            "data": data,
            "event_id": event_id or f"evt-{len(self.accumulator):06d}",
            "hash": event_hash,
            "added_at": time.time(),
        }
        self.accumulator.append(event)
        return {
            "accepted": True,
            "event_id": event["event_id"],
            "accumulator_size": len(self.accumulator),
        }

    def batch(self, max_batch_size: int = 10,
              max_bytes: int = 4096) -> List[List[dict]]:
        """Batch accumulated events, ordered by priority.

        Trust events > capability events > model events > general events.
        Respects both item count and byte limits.
        """
        if not self.accumulator:
            return []

        # Sort by priority
        sorted_events = sorted(
            self.accumulator,
            key=lambda e: self.EVENT_PRIORITY.get(e["type"], 3),
        )

        batches: List[List[dict]] = []
        current_batch: List[dict] = []
        current_bytes = 0

        for event in sorted_events:
            event_bytes = len(json.dumps(event, default=str).encode("utf-8"))
            would_exceed = (
                len(current_batch) >= max_batch_size
                or current_bytes + event_bytes > max_bytes
            )
            if would_exceed and current_batch:
                batches.append(current_batch)
                current_batch = []
                current_bytes = 0
            current_batch.append(event)
            current_bytes += event_bytes

        if current_batch:
            batches.append(current_batch)

        return batches

    def flush(self) -> List[dict]:
        """Return all accumulated events and clear the accumulator."""
        events = self.accumulator[:]
        self.accumulator = []
        return events

    def flush_and_batch(self, max_batch_size: int = 10,
                        max_bytes: int = 4096) -> List[List[dict]]:
        """Flush and batch in one operation."""
        batches = self.batch(max_batch_size, max_bytes)
        self.accumulator = []
        return batches

    @property
    def pending_count(self) -> int:
        """Number of events currently in the accumulator."""
        return len(self.accumulator)

    def to_dict(self) -> dict:
        """Serialize tender state to dictionary."""
        return {
            "pending_count": self.pending_count,
            "dedup_count": self.dedup_count,
            "seen_hashes_count": len(self.seen_hashes),
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'DataTender':
        """Deserialize tender state from dictionary."""
        tender = cls()
        tender.dedup_count = data.get("dedup_count", 0)
        return tender


# ─── PriorityTender ────────────────────────────────────────────────────────────

class CloudUrgency(Enum):
    """Cloud-side urgency levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFORMATIONAL = "informational"


class EdgeUrgency(Enum):
    """Edge-side urgency levels."""
    IMMEDIATE = "immediate"
    QUEUED = "queued"
    DEFERRED = "deferred"
    IGNORED = "ignored"


# Default cloud->edge mapping
DEFAULT_CLOUD_TO_EDGE: Dict[CloudUrgency, EdgeUrgency] = {
    CloudUrgency.CRITICAL: EdgeUrgency.IMMEDIATE,
    CloudUrgency.HIGH: EdgeUrgency.QUEUED,
    CloudUrgency.MEDIUM: EdgeUrgency.QUEUED,
    CloudUrgency.LOW: EdgeUrgency.DEFERRED,
    CloudUrgency.INFORMATIONAL: EdgeUrgency.IGNORED,
}

# Default edge->cloud mapping
DEFAULT_EDGE_TO_CLOUD: Dict[EdgeUrgency, CloudUrgency] = {
    EdgeUrgency.IMMEDIATE: CloudUrgency.CRITICAL,
    EdgeUrgency.QUEUED: CloudUrgency.HIGH,
    EdgeUrgency.DEFERRED: CloudUrgency.MEDIUM,
    EdgeUrgency.IGNORED: CloudUrgency.LOW,
}


class PriorityTender:
    """Translates urgency between cloud and edge realities.

    Cloud urgency: critical, high, medium, low, informational
    Edge urgency: immediate, queued, deferred, ignored
    Bidirectional translation with configurable mapping.
    Escalation rules: if edge defers 3 times, escalate to queued.
    """

    DEFERRAL_ESCALATION_LIMIT: int = 3

    def __init__(self) -> None:
        self.cloud_to_edge: Dict[CloudUrgency, EdgeUrgency] = dict(DEFAULT_CLOUD_TO_EDGE)
        self.edge_to_cloud: Dict[EdgeUrgency, CloudUrgency] = dict(DEFAULT_EDGE_TO_CLOUD)
        self.deferral_counts: Dict[str, int] = {}

    def cloud_to_edge_urgency(self, cloud: CloudUrgency,
                              context_id: str = "") -> dict:
        """Translate cloud urgency to edge urgency."""
        default_edge = self.cloud_to_edge.get(cloud, EdgeUrgency.DEFERRED)
        edge = default_edge

        # Check escalation: if deferred too many times, escalate
        if edge == EdgeUrgency.DEFERRED and context_id:
            count = self.deferral_counts.get(context_id, 0)
            if count >= self.DEFERRAL_ESCALATION_LIMIT:
                edge = EdgeUrgency.QUEUED

        return {
            "cloud_urgency": cloud.value,
            "edge_urgency": edge.value,
            "escalated": edge != default_edge,
        }

    def edge_to_cloud_urgency(self, edge: EdgeUrgency) -> dict:
        """Translate edge urgency to cloud urgency."""
        cloud = self.edge_to_cloud.get(edge, CloudUrgency.LOW)
        return {
            "edge_urgency": edge.value,
            "cloud_urgency": cloud.value,
        }

    def record_deferral(self, context_id: str) -> None:
        """Record that edge deferred a message with this context."""
        self.deferral_counts[context_id] = self.deferral_counts.get(context_id, 0) + 1

    def reset_deferrals(self, context_id: str) -> None:
        """Reset deferral count for a context."""
        self.deferral_counts.pop(context_id, None)

    def get_deferral_count(self, context_id: str) -> int:
        """Get current deferral count for a context."""
        return self.deferral_counts.get(context_id, 0)

    def configure_mapping(self, cloud: CloudUrgency, edge: EdgeUrgency) -> None:
        """Configure custom cloud->edge mapping."""
        self.cloud_to_edge[cloud] = edge

    def to_dict(self) -> dict:
        """Serialize tender state to dictionary."""
        return {
            "cloud_to_edge": {k.value: v.value for k, v in self.cloud_to_edge.items()},
            "edge_to_cloud": {k.value: v.value for k, v in self.edge_to_cloud.items()},
            "deferral_counts": dict(self.deferral_counts),
            "escalation_limit": self.DEFERRAL_ESCALATION_LIMIT,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'PriorityTender':
        """Deserialize tender state from dictionary."""
        tender = cls()
        for ck, ev in data.get("cloud_to_edge", {}).items():
            tender.cloud_to_edge[CloudUrgency(ck)] = EdgeUrgency(ev)
        for ek, cv in data.get("edge_to_cloud", {}).items():
            tender.edge_to_cloud[EdgeUrgency(ek)] = CloudUrgency(cv)
        tender.deferral_counts = data.get("deferral_counts", {})
        return tender


# ─── ContextTender ─────────────────────────────────────────────────────────────

class ContextTender:
    """Synchronizes context between cloud and edge.

    Implements differential context sync (only send changes),
    and context versioning for conflict detection.
    """

    def __init__(self) -> None:
        self.contexts: Dict[str, dict] = {}
        self.versions: Dict[str, int] = {}
        self.conflicts: List[dict] = []

    def update_context(self, node_id: str, context: Dict[str, Any]) -> dict:
        """Update context for a node, returning the diff from previous version."""
        prev = self.contexts.get(node_id, {})
        current_version = self.versions.get(node_id, 0)

        # Compute differential: only changed keys
        diff: Dict[str, dict] = {}
        all_keys = set(prev.keys()) | set(context.keys())
        for key in all_keys:
            old_val = prev.get(key)
            new_val = context.get(key)
            if old_val != new_val:
                diff[key] = {"old": old_val, "new": new_val}

        self.contexts[node_id] = context
        self.versions[node_id] = current_version + 1

        return {
            "node_id": node_id,
            "version": self.versions[node_id],
            "diff": diff,
            "changed_keys": list(diff.keys()),
        }

    def get_context(self, node_id: str) -> dict:
        """Get current context for a node."""
        return {
            "node_id": node_id,
            "context": self.contexts.get(node_id, {}),
            "version": self.versions.get(node_id, 0),
        }

    def sync_diff(self, node_id: str, since_version: int = 0) -> dict:
        """Get differential sync data since a specific version.

        If since_version < current version, returns the full current context
        (can't reconstruct history). If versions match, nothing to sync.
        """
        current = self.contexts.get(node_id, {})
        current_version = self.versions.get(node_id, 0)

        if since_version >= current_version:
            return {
                "node_id": node_id,
                "needs_sync": False,
                "version": current_version,
                "changes": {},
            }

        if since_version == 0:
            return {
                "node_id": node_id,
                "needs_sync": True,
                "version": current_version,
                "changes": current,  # full context for first sync
                "full_sync": True,
            }

        # Version mismatch but we can't reconstruct intermediate diffs
        return {
            "node_id": node_id,
            "needs_sync": True,
            "version": current_version,
            "changes": current,
            "full_sync": True,
            "reason": "version_gap_too_large",
        }

    def detect_conflict(self, node_id: str, incoming_version: int,
                        incoming_context: Dict[str, Any]) -> Optional[dict]:
        """Detect version conflict between incoming and stored context."""
        stored_version = self.versions.get(node_id, 0)

        if incoming_version < stored_version:
            conflict: dict = {
                "node_id": node_id,
                "incoming_version": incoming_version,
                "stored_version": stored_version,
                "detected_at": time.time(),
                "resolution": "stored_wins",
            }
            self.conflicts.append(conflict)
            return conflict

        return None

    def to_dict(self) -> dict:
        """Serialize tender state to dictionary."""
        return {
            "node_count": len(self.contexts),
            "versions": dict(self.versions),
            "conflict_count": len(self.conflicts),
            "nodes": list(self.contexts.keys()),
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ContextTender':
        """Deserialize tender state from dictionary."""
        tender = cls()
        tender.versions = data.get("versions", {})
        return tender
