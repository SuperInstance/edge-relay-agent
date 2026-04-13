"""
Agent Discovery — Auto-discover other agents on the network.

Provides heartbeat monitoring, capability advertisement, and a
service registry for fleet agents operating on edge or cloud nodes.

This is a NEW module for the standalone edge-relay-agent, not extracted
from the original edge-research-relay.
No external dependencies — uses only stdlib.
"""

import time
import json
import hashlib
import socket
import os
from typing import Optional, Dict, List, Any, Callable
from dataclasses import dataclass, field
from enum import Enum


# ─── Agent State ───────────────────────────────────────────────────────────────

class AgentState(Enum):
    """Lifecycle states for a discovered agent."""
    UNKNOWN = "unknown"
    ACTIVE = "active"
    IDLE = "idle"
    DEGRADED = "degraded"
    OFFLINE = "offline"


# ─── Agent Record ──────────────────────────────────────────────────────────────

@dataclass
class AgentRecord:
    """A discovered agent's registration record.

    Attributes:
        agent_id: Unique identifier for this agent.
        hostname: Machine hostname where the agent runs.
        capabilities: List of capability strings this agent provides.
        port: Port number the agent listens on (0 if unknown).
        state: Current lifecycle state of the agent.
        registered_at: Timestamp when first discovered.
        last_heartbeat: Timestamp of the most recent heartbeat.
        heartbeat_count: Total number of heartbeats received.
        metadata: Arbitrary metadata about the agent.
        version: Agent software version string.
    """
    agent_id: str
    hostname: str = ""
    capabilities: List[str] = field(default_factory=list)
    port: int = 0
    state: AgentState = AgentState.UNKNOWN
    registered_at: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)
    heartbeat_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    version: str = "0.0.0"

    @property
    def uptime_seconds(self) -> float:
        """Seconds since this agent was first registered."""
        return time.time() - self.registered_at

    @property
    def seconds_since_heartbeat(self) -> float:
        """Seconds since the last heartbeat was received."""
        return time.time() - self.last_heartbeat

    def to_dict(self) -> dict:
        """Serialize agent record to dictionary."""
        return {
            "agent_id": self.agent_id,
            "hostname": self.hostname,
            "capabilities": self.capabilities,
            "port": self.port,
            "state": self.state.value,
            "registered_at": self.registered_at,
            "last_heartbeat": self.last_heartbeat,
            "heartbeat_count": self.heartbeat_count,
            "uptime_seconds": round(self.uptime_seconds, 2),
            "seconds_since_heartbeat": round(self.seconds_since_heartbeat, 2),
            "metadata": self.metadata,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'AgentRecord':
        """Deserialize agent record from dictionary."""
        return cls(
            agent_id=data["agent_id"],
            hostname=data.get("hostname", ""),
            capabilities=data.get("capabilities", []),
            port=data.get("port", 0),
            state=AgentState(data.get("state", "unknown")),
            registered_at=data.get("registered_at", time.time()),
            last_heartbeat=data.get("last_heartbeat", time.time()),
            heartbeat_count=data.get("heartbeat_count", 0),
            metadata=data.get("metadata", {}),
            version=data.get("version", "0.0.0"),
        )

    def fingerprint(self) -> str:
        """Generate a stable fingerprint hash for this agent's identity.

        Combines agent_id + hostname + capabilities for uniqueness.
        """
        raw = f"{self.agent_id}:{self.hostname}:{','.join(sorted(self.capabilities))}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ─── Service Registry ──────────────────────────────────────────────────────────

class ServiceRegistry:
    """Registry for tracking agent services and capabilities.

    Provides lookup by capability, agent ID, and hostname.
    """

    def __init__(self) -> None:
        self._agents: Dict[str, AgentRecord] = {}
        self._capability_index: Dict[str, List[str]] = {}
        self._hostname_index: Dict[str, List[str]] = {}

    def register(self, agent: AgentRecord) -> dict:
        """Register or update an agent in the registry.

        Updates capability and hostname indices.
        """
        is_new = agent.agent_id not in self._agents
        self._agents[agent.agent_id] = agent

        # Update capability index
        for cap in agent.capabilities:
            if cap not in self._capability_index:
                self._capability_index[cap] = []
            if agent.agent_id not in self._capability_index[cap]:
                self._capability_index[cap].append(agent.agent_id)

        # Update hostname index
        if agent.hostname:
            if agent.hostname not in self._hostname_index:
                self._hostname_index[agent.hostname] = []
            if agent.agent_id not in self._hostname_index[agent.hostname]:
                self._hostname_index[agent.hostname].append(agent.agent_id)

        return {
            "agent_id": agent.agent_id,
            "registered": is_new,
            "total_agents": len(self._agents),
        }

    def unregister(self, agent_id: str) -> bool:
        """Remove an agent from the registry.

        Cleans up capability and hostname indices.

        Returns:
            True if the agent was found and removed.
        """
        agent = self._agents.pop(agent_id, None)
        if not agent:
            return False

        # Clean capability index
        for cap in agent.capabilities:
            if cap in self._capability_index:
                self._capability_index[cap] = [
                    aid for aid in self._capability_index[cap]
                    if aid != agent_id
                ]
                if not self._capability_index[cap]:
                    del self._capability_index[cap]

        # Clean hostname index
        if agent.hostname and agent.hostname in self._hostname_index:
            self._hostname_index[agent.hostname] = [
                aid for aid in self._hostname_index[agent.hostname]
                if aid != agent_id
            ]
            if not self._hostname_index[agent.hostname]:
                del self._hostname_index[agent.hostname]

        return True

    def get_agent(self, agent_id: str) -> Optional[AgentRecord]:
        """Look up an agent by ID."""
        return self._agents.get(agent_id)

    def find_by_capability(self, capability: str) -> List[AgentRecord]:
        """Find all agents that provide a given capability."""
        agent_ids = self._capability_index.get(capability, [])
        return [self._agents[aid] for aid in agent_ids if aid in self._agents]

    def find_by_hostname(self, hostname: str) -> List[AgentRecord]:
        """Find all agents on a given hostname."""
        agent_ids = self._hostname_index.get(hostname, [])
        return [self._agents[aid] for aid in agent_ids if aid in self._agents]

    def all_agents(self) -> List[AgentRecord]:
        """Return all registered agents."""
        return list(self._agents.values())

    def all_capabilities(self) -> List[str]:
        """Return sorted list of all known capabilities."""
        return sorted(self._capability_index.keys())

    @property
    def size(self) -> int:
        """Number of registered agents."""
        return len(self._agents)

    def to_dict(self) -> dict:
        """Serialize registry state."""
        return {
            "total_agents": self.size,
            "capabilities": self.all_capabilities(),
            "agents": {aid: a.to_dict() for aid, a in self._agents.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ServiceRegistry':
        """Deserialize registry state."""
        registry = cls()
        for aid, ad in data.get("agents", {}).items():
            registry.register(AgentRecord.from_dict(ad))
        return registry


# ─── Heartbeat Monitor ────────────────────────────────────────────────────────

class HeartbeatMonitor:
    """Monitors agent health via heartbeat tracking.

    Agents are expected to send periodic heartbeats. If an agent
    misses the heartbeat timeout, it is marked as degraded, then offline.
    """

    DEFAULT_TIMEOUT = 30.0   # seconds before degraded
    DEFAULT_OFFLINE = 90.0   # seconds before offline

    def __init__(self, timeout: float = DEFAULT_TIMEOUT,
                 offline_threshold: float = DEFAULT_OFFLINE) -> None:
        self.timeout = timeout
        self.offline_threshold = offline_threshold
        self._callbacks: List[Callable[[AgentRecord, AgentState, AgentState], None]] = []

    def on_state_change(self, callback: Callable[[AgentRecord, AgentState, AgentState], None]) -> None:
        """Register a callback for agent state transitions.

        Args:
            callback: Function called with (agent, old_state, new_state).
        """
        self._callbacks.append(callback)

    def check_heartbeat(self, agent: AgentRecord) -> AgentState:
        """Check if an agent's heartbeat is within acceptable thresholds.

        Updates agent state based on time since last heartbeat.

        Returns:
            The updated (or unchanged) AgentState.
        """
        elapsed = agent.seconds_since_heartbeat
        old_state = agent.state

        if elapsed >= self.offline_threshold:
            new_state = AgentState.OFFLINE
        elif elapsed >= self.timeout:
            new_state = AgentState.DEGRADED
        elif agent.heartbeat_count == 0:
            new_state = AgentState.UNKNOWN
        elif elapsed < self.timeout * 0.5:
            new_state = AgentState.ACTIVE
        else:
            new_state = AgentState.IDLE

        if new_state != old_state:
            agent.state = new_state
            for cb in self._callbacks:
                try:
                    cb(agent, old_state, new_state)
                except Exception:
                    pass

        return new_state

    def record_heartbeat(self, agent: AgentRecord) -> dict:
        """Record a heartbeat for an agent.

        Updates last_heartbeat and heartbeat_count, then rechecks state.

        Returns:
            Updated heartbeat info.
        """
        agent.last_heartbeat = time.time()
        agent.heartbeat_count += 1
        state = self.check_heartbeat(agent)
        return {
            "agent_id": agent.agent_id,
            "heartbeat_count": agent.heartbeat_count,
            "state": state.value,
        }

    def health_report(self, registry: ServiceRegistry) -> dict:
        """Generate a health report for all agents in the registry.

        Returns counts by state and lists of problematic agents.
        """
        counts: Dict[str, int] = {s.value: 0 for s in AgentState}
        degraded: List[dict] = []
        offline: List[dict] = []

        for agent in registry.all_agents():
            self.check_heartbeat(agent)
            counts[agent.state.value] += 1
            if agent.state == AgentState.DEGRADED:
                degraded.append({
                    "agent_id": agent.agent_id,
                    "seconds_since_heartbeat": round(agent.seconds_since_heartbeat, 1),
                })
            elif agent.state == AgentState.OFFLINE:
                offline.append({
                    "agent_id": agent.agent_id,
                    "seconds_since_heartbeat": round(agent.seconds_since_heartbeat, 1),
                })

        return {
            "total_agents": registry.size,
            "state_counts": counts,
            "degraded": degraded,
            "offline": offline,
            "healthy": counts.get("active", 0) + counts.get("idle", 0),
        }


# ─── Capability Advertiser ────────────────────────────────────────────────────

class CapabilityAdvertiser:
    """Manages capability advertisement for a local agent.

    Generates an advertisement payload describing this agent's
    capabilities, which can be broadcast or sent to a discovery service.
    """

    def __init__(self, agent_id: str,
                 capabilities: Optional[List[str]] = None,
                 port: int = 0) -> None:
        self.agent_id = agent_id
        self.capabilities: List[str] = capabilities or []
        self.port = port
        self.metadata: Dict[str, Any] = {}
        self.version: str = "1.0.0"

    def set_capabilities(self, capabilities: List[str]) -> None:
        """Set the list of advertised capabilities."""
        self.capabilities = sorted(set(capabilities))

    def add_capability(self, capability: str) -> None:
        """Add a single capability."""
        if capability not in self.capabilities:
            self.capabilities.append(capability)
            self.capabilities.sort()

    def remove_capability(self, capability: str) -> bool:
        """Remove a capability. Returns True if it existed."""
        if capability in self.capabilities:
            self.capabilities.remove(capability)
            return True
        return False

    def build_advertisement(self) -> dict:
        """Build an advertisement payload for discovery.

        Returns:
            Dictionary describing this agent for network discovery.
        """
        return {
            "agent_id": self.agent_id,
            "hostname": socket.gethostname(),
            "capabilities": self.capabilities,
            "port": self.port,
            "version": self.version,
            "metadata": self.metadata,
            "timestamp": time.time(),
        }

    def to_agent_record(self) -> AgentRecord:
        """Convert this advertiser's state to an AgentRecord."""
        ad = self.build_advertisement()
        return AgentRecord(
            agent_id=ad["agent_id"],
            hostname=ad["hostname"],
            capabilities=ad["capabilities"],
            port=ad["port"],
            metadata=ad["metadata"],
            version=ad["version"],
        )


# ─── Discovery Service ────────────────────────────────────────────────────────

class DiscoveryService:
    """High-level discovery service combining registry, heartbeat, and advertising.

    Provides the main interface for:
    - Registering self and discovering peers
    - Heartbeat monitoring and health reporting
    - Capability-based agent lookup
    - Serializing and restoring discovery state
    """

    def __init__(self, agent_id: str,
                 capabilities: Optional[List[str]] = None,
                 port: int = 0,
                 heartbeat_timeout: float = 30.0) -> None:
        self.registry = ServiceRegistry()
        self.monitor = HeartbeatMonitor(timeout=heartbeat_timeout)
        self.advertiser = CapabilityAdvertiser(
            agent_id=agent_id,
            capabilities=capabilities,
            port=port,
        )
        self._started_at = time.time()

    @property
    def agent_id(self) -> str:
        """This agent's ID."""
        return self.advertiser.agent_id

    @property
    def uptime_seconds(self) -> float:
        """Seconds since this discovery service was created."""
        return time.time() - self._started_at

    def register_self(self) -> dict:
        """Register this agent in the discovery registry.

        Returns:
            Registration result.
        """
        record = self.advertiser.to_agent_record()
        result = self.registry.register(record)
        self.monitor.record_heartbeat(record)
        return result

    def discover_agent(self, agent_id: str, hostname: str = "",
                       capabilities: Optional[List[str]] = None,
                       port: int = 0, metadata: Optional[Dict[str, Any]] = None) -> dict:
        """Register a discovered remote agent.

        Args:
            agent_id: The remote agent's ID.
            hostname: The remote agent's hostname.
            capabilities: The remote agent's capabilities.
            port: The remote agent's port.
            metadata: Additional metadata about the agent.

        Returns:
            Registration result.
        """
        record = AgentRecord(
            agent_id=agent_id,
            hostname=hostname,
            capabilities=capabilities or [],
            port=port,
            metadata=metadata or {},
        )
        return self.registry.register(record)

    def heartbeat(self, agent_id: str) -> Optional[dict]:
        """Record a heartbeat from an agent.

        Returns:
            Heartbeat info, or None if agent not found.
        """
        agent = self.registry.get_agent(agent_id)
        if not agent:
            return None
        return self.monitor.record_heartbeat(agent)

    def remove_agent(self, agent_id: str) -> bool:
        """Remove an agent from the discovery registry."""
        return self.registry.unregister(agent_id)

    def find_capable(self, capability: str) -> List[AgentRecord]:
        """Find all agents (including self) that provide a capability."""
        return self.registry.find_by_capability(capability)

    def health_report(self) -> dict:
        """Generate a health report for all discovered agents."""
        report = self.monitor.health_report(self.registry)
        report["local_agent_id"] = self.agent_id
        report["uptime_seconds"] = round(self.uptime_seconds, 2)
        return report

    def to_dict(self) -> dict:
        """Serialize discovery service state."""
        return {
            "agent_id": self.agent_id,
            "uptime_seconds": round(self.uptime_seconds, 2),
            "registry": self.registry.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'DiscoveryService':
        """Deserialize discovery service state."""
        service = cls(agent_id=data.get("agent_id", "unknown"))
        service.registry = ServiceRegistry.from_dict(data.get("registry", {}))
        return service
