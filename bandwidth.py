"""
Bandwidth Management — Edge device bandwidth constraints and optimization.

Edge devices have limited bandwidth. This module manages allocation,
adaptive distribution, overflow queuing, compression strategies, and
priority-based preemption.

Standalone extraction from the edge-research-relay fleet module.
No external dependencies — uses only stdlib.
"""

import time
import zlib
import json
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum


# ─── Compression Strategies ───────────────────────────────────────────────────

class CompressionStrategy(Enum):
    """Available compression strategies for edge-bound data."""
    NONE = "none"
    ZLIB = "zlib"
    TRUNCATE = "truncate"
    STRIP_METADATA = "strip_metadata"
    HYBRID = "hybrid"


class CompressionEngine:
    """Compression strategies optimized for edge bandwidth constraints.

    Provides multiple strategies: raw passthrough, zlib compression,
    metadata stripping, truncation, and hybrid approaches.
    """

    def __init__(self) -> None:
        self.stats: Dict[str, int] = {
            "compressed_count": 0,
            "total_original_bytes": 0,
            "total_compressed_bytes": 0,
        }

    def compress(self, data: str, strategy: CompressionStrategy = CompressionStrategy.HYBRID,
                 max_bytes: int = 0) -> dict:
        """Compress data using the specified strategy.

        Args:
            data: Input data string to compress.
            strategy: Compression strategy to apply.
            max_bytes: Optional maximum output size in bytes.

        Returns:
            Dictionary with compressed data and metadata.
        """
        original_size = len(data.encode("utf-8"))
        self.stats["compressed_count"] += 1
        self.stats["total_original_bytes"] += original_size

        if strategy == CompressionStrategy.NONE:
            result = data

        elif strategy == CompressionStrategy.ZLIB:
            result = zlib.compress(data.encode("utf-8")).decode("latin-1")

        elif strategy == CompressionStrategy.TRUNCATE:
            result = data[:max_bytes] if max_bytes else data

        elif strategy == CompressionStrategy.STRIP_METADATA:
            result = self._strip_metadata(data)

        elif strategy == CompressionStrategy.HYBRID:
            # First strip, then compress
            stripped = self._strip_metadata(data)
            result = zlib.compress(stripped.encode("utf-8")).decode("latin-1")

        else:
            result = data

        compressed_size = len(result.encode("utf-8")) if isinstance(result, str) else len(result)
        self.stats["total_compressed_bytes"] += compressed_size

        # Apply max_bytes limit if specified
        if max_bytes and compressed_size > max_bytes:
            result = result[:max_bytes]
            compressed_size = max_bytes

        return {
            "data": result,
            "original_size": original_size,
            "compressed_size": compressed_size,
            "ratio": round(compressed_size / original_size, 4) if original_size > 0 else 1.0,
            "strategy": strategy.value,
        }

    def decompress(self, data: str, strategy: CompressionStrategy = CompressionStrategy.HYBRID) -> str:
        """Decompress data that was compressed with the given strategy."""
        if strategy == CompressionStrategy.ZLIB:
            return zlib.decompress(data.encode("latin-1")).decode("utf-8")
        elif strategy == CompressionStrategy.HYBRID:
            return zlib.decompress(data.encode("latin-1")).decode("utf-8")
        return data

    @staticmethod
    def _strip_metadata(data: str) -> str:
        """Strip metadata-like patterns from data (JSON fields starting with _ or common metadata keys)."""
        try:
            parsed = json.loads(data)
            if isinstance(parsed, dict):
                stripped = {
                    k: v for k, v in parsed.items()
                    if not k.startswith("_") and k not in (
                        "metadata", "debug_info", "full_history", "timestamps",
                        "internal_notes", "provenance",
                    )
                }
                return json.dumps(stripped, default=str)
        except (json.JSONDecodeError, TypeError):
            pass
        return data

    def best_strategy(self, data: str, max_bytes: int = 512) -> dict:
        """Find the best compression strategy for the given data.

        Tries all strategies and returns the one that achieves the best ratio
        while staying within max_bytes if possible.
        """
        results = {}
        for strategy in CompressionStrategy:
            try:
                result = self.compress(data, strategy=strategy, max_bytes=max_bytes)
                results[strategy.value] = result
            except Exception:
                continue

        if not results:
            return self.compress(data, strategy=CompressionStrategy.NONE)

        # Pick the strategy with the smallest output that fits, or smallest overall
        fitting = {k: v for k, v in results.items() if v["compressed_size"] <= max_bytes}
        if fitting:
            best = min(fitting.values(), key=lambda r: r["compressed_size"])
        else:
            best = min(results.values(), key=lambda r: r["compressed_size"])

        return best

    def get_stats(self) -> dict:
        """Get compression engine statistics."""
        avg_ratio = (
            self.stats["total_compressed_bytes"] / self.stats["total_original_bytes"]
            if self.stats["total_original_bytes"] > 0
            else 1.0
        )
        return {
            "compressed_count": self.stats["compressed_count"],
            "total_original_bytes": self.stats["total_original_bytes"],
            "total_compressed_bytes": self.stats["total_compressed_bytes"],
            "average_ratio": round(avg_ratio, 4),
        }


# ─── BandwidthMessage ─────────────────────────────────────────────────────────

@dataclass
class BandwidthMessage:
    """A message with bandwidth metadata."""
    message_id: str
    payload_size: int  # bytes
    priority: int = 2  # 0=critical, 1=high, 2=medium, 3=low, 4=info
    tender_type: str = "general"
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """Serialize message to dictionary."""
        return {
            "message_id": self.message_id,
            "payload_size": self.payload_size,
            "priority": self.priority,
            "tender_type": self.tender_type,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'BandwidthMessage':
        """Deserialize message from dictionary."""
        return cls(
            message_id=data["message_id"],
            payload_size=data.get("payload_size", 0),
            priority=data.get("priority", 2),
            tender_type=data.get("tender_type", "general"),
            created_at=data.get("created_at", time.time()),
        )


# ─── Priority Queue ───────────────────────────────────────────────────────────

class PriorityQueue:
    """Priority queue for bandwidth-managed messages.

    Higher priority (lower number) messages are dequeued first.
    Supports bounded capacity with automatic eviction of lowest-priority items.
    """

    def __init__(self, max_size: int = 1000) -> None:
        self.max_size = max_size
        self._queue: List[BandwidthMessage] = []

    def enqueue(self, message: BandwidthMessage) -> dict:
        """Add a message to the queue.

        If queue is full, evicts the lowest-priority message first.
        """
        if len(self._queue) >= self.max_size:
            # Find and evict lowest priority
            evict_idx = max(range(len(self._queue)),
                            key=lambda i: self._queue[i].priority)
            evicted = self._queue.pop(evict_idx)
            self._queue.append(message)
            return {
                "enqueued": True,
                "evicted": evicted.message_id,
                "queue_size": len(self._queue),
            }
        self._queue.append(message)
        return {
            "enqueued": True,
            "evicted": None,
            "queue_size": len(self._queue),
        }

    def dequeue(self) -> Optional[BandwidthMessage]:
        """Remove and return the highest-priority message."""
        if not self._queue:
            return None
        # Highest priority = lowest number
        best_idx = min(range(len(self._queue)),
                       key=lambda i: self._queue[i].priority)
        return self._queue.pop(best_idx)

    def dequeue_batch(self, max_count: int = 5) -> List[BandwidthMessage]:
        """Dequeue up to max_count highest-priority messages."""
        result: List[BandwidthMessage] = []
        for _ in range(min(max_count, len(self._queue))):
            msg = self.dequeue()
            if msg:
                result.append(msg)
        return result

    def peek(self) -> Optional[BandwidthMessage]:
        """Peek at the highest-priority message without removing it."""
        if not self._queue:
            return None
        return min(self._queue, key=lambda m: m.priority)

    @property
    def size(self) -> int:
        """Current queue size."""
        return len(self._queue)

    def get_by_priority(self, max_priority: int = 2) -> List[BandwidthMessage]:
        """Get all messages with priority <= max_priority."""
        return [m for m in self._queue if m.priority <= max_priority]

    def to_dict(self) -> dict:
        """Serialize queue state."""
        return {
            "max_size": self.max_size,
            "current_size": self.size,
            "messages": [m.to_dict() for m in self._queue],
        }


# ─── BandwidthBudget ──────────────────────────────────────────────────────────

class BandwidthBudget:
    """Manages edge device bandwidth allocation and enforcement.

    Features:
    - Total bandwidth limit (bytes/sec)
    - Per-tender allocation
    - Adaptive allocation (more bandwidth for active research sessions)
    - Overflow queue (queue messages when bandwidth exceeded)
    - Priority-based preemption (drop low-priority when overloaded)
    """

    def __init__(self, total_bps: int = 1024) -> None:
        self.total_bps = total_bps
        self.base_allocations: Dict[str, float] = {
            "research": 0.30,
            "data": 0.25,
            "priority": 0.25,
            "context": 0.10,
            "general": 0.10,
        }
        self.active_sessions: Dict[str, float] = {}  # session_id -> boost factor
        self.overflow_queue: List[BandwidthMessage] = []
        self.dropped_messages: List[dict] = []
        self.delivered_bytes: int = 0
        self.queued_bytes: int = 0
        self.priority_queue = PriorityQueue(max_size=500)

    def allocate(self, tender_type: str, message: BandwidthMessage) -> dict:
        """Try to allocate bandwidth for a message.

        Returns allocation result with whether it was accepted, queued, or dropped.
        """
        fraction = self.base_allocations.get(tender_type, 0.05)
        # Apply adaptive boost for active research sessions
        if tender_type == "research" and self.active_sessions:
            boost = min(sum(self.active_sessions.values()), 2.0)
            fraction = min(fraction * (1.0 + boost), 0.80)

        available = int(self.total_bps * fraction)
        needed = message.payload_size

        if needed <= available:
            self.delivered_bytes += needed
            return {
                "status": "delivered",
                "bytes": needed,
                "available": available,
                "tender_type": tender_type,
            }
        elif needed <= self.total_bps:
            # Queue it — might fit later
            self.overflow_queue.append(message)
            self.queued_bytes += needed
            self.priority_queue.enqueue(message)
            return {
                "status": "queued",
                "bytes": needed,
                "available": available,
                "queue_position": len(self.overflow_queue),
            }
        else:
            # Message exceeds total capacity — drop it
            self.dropped_messages.append({
                "message_id": message.message_id,
                "reason": "exceeds_total_capacity",
                "size": needed,
                "timestamp": time.time(),
            })
            return {
                "status": "dropped",
                "bytes": needed,
                "reason": "exceeds_total_capacity",
            }

    def add_active_session(self, session_id: str, boost: float = 0.5) -> None:
        """Register an active research session for adaptive allocation."""
        self.active_sessions[session_id] = boost

    def remove_active_session(self, session_id: str) -> None:
        """Remove an active research session."""
        self.active_sessions.pop(session_id, None)

    def process_overflow(self, max_messages: int = 5) -> List[dict]:
        """Try to deliver queued messages from overflow.

        Processes up to max_messages, returns delivery results.
        Does NOT re-queue via allocate() — manages queue directly.
        """
        results: List[dict] = []
        to_process = self.overflow_queue[:max_messages]
        rest = self.overflow_queue[max_messages:]

        for msg in to_process:
            fraction = self.base_allocations.get(msg.tender_type, 0.05)
            if msg.tender_type == "research" and self.active_sessions:
                boost = min(sum(self.active_sessions.values()), 2.0)
                fraction = min(fraction * (1.0 + boost), 0.80)
            available = int(self.total_bps * fraction)
            needed = msg.payload_size

            if needed <= available:
                self.delivered_bytes += needed
                self.queued_bytes -= needed
                results.append({
                    "status": "delivered",
                    "bytes": needed,
                    "available": available,
                    "tender_type": msg.tender_type,
                })
            elif needed <= self.total_bps:
                # Still can't fit, keep in queue
                rest.append(msg)
            else:
                # Drop — exceeds total capacity
                self.dropped_messages.append({
                    "message_id": msg.message_id,
                    "reason": "exceeds_total_capacity",
                    "size": needed,
                    "timestamp": time.time(),
                })
                self.queued_bytes -= needed

        self.overflow_queue = rest
        return results

    def preempt(self, max_priority: int = 3) -> List[dict]:
        """Drop low-priority messages from overflow when overloaded.

        Drops messages with priority >= max_priority.
        """
        dropped: List[dict] = []
        kept: List[BandwidthMessage] = []
        for msg in self.overflow_queue:
            if msg.priority >= max_priority:
                self.dropped_messages.append({
                    "message_id": msg.message_id,
                    "reason": "preempted",
                    "size": msg.payload_size,
                    "timestamp": time.time(),
                })
                self.queued_bytes -= msg.payload_size
                dropped.append(msg.to_dict())
            else:
                kept.append(msg)
        self.overflow_queue = kept
        return dropped

    def set_allocation(self, tender_type: str, fraction: float) -> None:
        """Set custom per-tender allocation fraction."""
        self.base_allocations[tender_type] = max(0.0, min(1.0, fraction))

    def available_bandwidth(self) -> dict:
        """Get current bandwidth availability snapshot."""
        return {
            "total_bps": self.total_bps,
            "allocated_tenders": dict(self.base_allocations),
            "active_sessions": len(self.active_sessions),
            "overflow_queue_size": len(self.overflow_queue),
            "queued_bytes": self.queued_bytes,
            "delivered_bytes": self.delivered_bytes,
            "dropped_count": len(self.dropped_messages),
        }

    def to_dict(self) -> dict:
        """Serialize budget state to dictionary."""
        return self.available_bandwidth()

    @classmethod
    def from_dict(cls, data: dict) -> 'BandwidthBudget':
        """Deserialize budget state from dictionary."""
        budget = cls(total_bps=data.get("total_bps", 1024))
        for tt, frac in data.get("allocated_tenders", {}).items():
            budget.base_allocations[tt] = frac
        return budget
