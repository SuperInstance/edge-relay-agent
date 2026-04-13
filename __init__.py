"""
Edge Relay Agent — standalone research relay for cloud-edge communication.

Provides asymmetric information routing between cloud ecosystems
and edge computing nodes with bandwidth management, discovery,
and priority-based message delivery.

Modules:
- relay: Core research relay engine
- tender_types: Specialized message tender types
- bandwidth: Bandwidth management and compression
- discovery: Agent discovery and heartbeat monitoring
- cli: Command-line interface
"""

__version__ = "1.0.0"
__all__ = [
    "relay",
    "tender_types",
    "bandwidth",
    "discovery",
    "cli",
]
