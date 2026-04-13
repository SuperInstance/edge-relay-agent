#!/usr/bin/env python3
"""
Test suite for the Edge Relay Agent standalone CLI.

Covers all modules:
- relay.py: CloudEdgeAsymmetry, ResearchRelay, message routing, compression
- tender_types.py: ResearchTender, DataTender, PriorityTender, ContextTender
- bandwidth.py: BandwidthBudget, CompressionEngine, PriorityQueue
- discovery.py: DiscoveryService, ServiceRegistry, HeartbeatMonitor, CapabilityAdvertiser
- cli.py: CLI subcommand parsing and basic flows

No external dependencies — uses only stdlib + unittest.
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from relay import (
    CloudEdgeAsymmetry, ResearchRelay, CloudSource, EdgeNode,
    ResearchQuery, EdgeFinding, RelayMessage,
    MessageDirection, MessagePriority,
)
from tender_types import (
    ResearchTender, DataTender, PriorityTender, ContextTender,
    CloudUrgency, EdgeUrgency,
)
from bandwidth import (
    BandwidthBudget, BandwidthMessage, CompressionEngine,
    CompressionStrategy, PriorityQueue,
)
from discovery import (
    AgentRecord, AgentState, ServiceRegistry, HeartbeatMonitor,
    CapabilityAdvertiser, DiscoveryService,
)


# ═══════════════════════════════════════════════════════════════════════════
# 1. CloudEdgeAsymmetry
# ═══════════════════════════════════════════════════════════════════════════

class TestCloudEdgeAsymmetry(unittest.TestCase):
    def test_cloud_strengths_populated(self):
        a = CloudEdgeAsymmetry()
        self.assertGreaterEqual(len(a.CLOUD_STRENGTHS), 4)

    def test_edge_strengths_populated(self):
        a = CloudEdgeAsymmetry()
        self.assertGreaterEqual(len(a.EDGE_STRENGTHS), 4)

    def test_cloud_can_approximate_edge_strength(self):
        a = CloudEdgeAsymmetry()
        self.assertTrue(a.cloud_can_approximate("validation"))

    def test_edge_cannot_approximate_fleet_context(self):
        a = CloudEdgeAsymmetry()
        self.assertFalse(a.edge_can_approximate("fleet_wide_context"))

    def test_log_divergence_high_severity(self):
        a = CloudEdgeAsymmetry()
        a.log_divergence("Jetson has 8GB VRAM", "Actually 6GB usable", severity=0.8)
        self.assertEqual(len(a.divergence_log), 1)
        self.assertEqual(len(a.assumption_failures), 1)

    def test_log_divergence_low_severity(self):
        a = CloudEdgeAsymmetry()
        a.log_divergence("minor diff", "slightly off", severity=0.3)
        self.assertEqual(len(a.assumption_failures), 0)

    def test_divergence_summary(self):
        a = CloudEdgeAsymmetry()
        a.log_divergence("a", "b", 0.5)
        a.log_divergence("c", "d", 0.9)
        s = a.divergence_summary()
        self.assertEqual(s["total_divergences"], 2)
        self.assertEqual(s["assumption_failures"], 1)
        self.assertTrue(0.0 < s["average_severity"] <= 1.0)

    def test_to_dict(self):
        a = CloudEdgeAsymmetry()
        d = a.to_dict()
        self.assertIn("cloud_strengths", d)
        self.assertIn("edge_strengths", d)

    def test_from_dict(self):
        a = CloudEdgeAsymmetry.from_dict({})
        self.assertIsNotNone(a)


# ═══════════════════════════════════════════════════════════════════════════
# 2. ResearchRelay
# ═══════════════════════════════════════════════════════════════════════════

class TestResearchRelay(unittest.TestCase):
    def test_register_cloud_source(self):
        r = ResearchRelay()
        src = r.register_cloud_source("oracle1", ["architecture", "specs"])
        self.assertEqual(src.source_id, "oracle1")
        self.assertIn("oracle1", r.cloud_sources)

    def test_register_edge_node(self):
        r = ResearchRelay()
        node = r.register_edge_node("jetson1", ["cuda", "sensors"], {"vram": 8192})
        self.assertEqual(node.node_id, "jetson1")
        self.assertEqual(node.constraints["vram"], 8192)

    def test_unregister_cloud_source(self):
        r = ResearchRelay()
        r.register_cloud_source("o1", ["arch"])
        self.assertTrue(r.unregister_cloud_source("o1"))
        self.assertNotIn("o1", r.cloud_sources)
        self.assertFalse(r.unregister_cloud_source("nonexistent"))

    def test_unregister_edge_node(self):
        r = ResearchRelay()
        r.register_edge_node("j1", ["cuda"], {})
        self.assertTrue(r.unregister_edge_node("j1"))
        self.assertFalse(r.unregister_edge_node("nonexistent"))

    def test_submit_research_query(self):
        r = ResearchRelay()
        q = r.submit_research_query("Test kernel latency", "oracle1")
        self.assertEqual(q.status, "pending")
        self.assertIn(q.query_id, r.queries)

    def test_submit_edge_finding(self):
        r = ResearchRelay()
        f = r.submit_edge_finding("jetson1", {"latency_ms": 2.3})
        self.assertEqual(f.node_id, "jetson1")
        self.assertIn(f.finding_id, r.findings)

    def test_compress_small_data(self):
        r = ResearchRelay()
        result = r.compress_for_edge({"key": "value"}, bandwidth_limit=1024)
        self.assertFalse(result["truncated"])
        self.assertEqual(result["ratio"], 1.0)

    def test_compress_large_data(self):
        r = ResearchRelay()
        data = {"metadata": "x" * 2000, "debug_info": "y" * 2000, "core": "keep"}
        result = r.compress_for_edge(data, bandwidth_limit=256)
        self.assertTrue(result["truncated"])
        self.assertLess(result["compressed_size"], result["original_size"])

    def test_expand_from_edge(self):
        r = ResearchRelay()
        r.register_edge_node("j1", ["sensors"], {"vram": 8192})
        result = r.expand_from_edge({"temp": 42.0})
        self.assertEqual(result["data"]["temp"], 42.0)
        self.assertEqual(result["edge_nodes_count"], 1)

    def test_prioritize_queries(self):
        r = ResearchRelay()
        queries = [
            r.submit_research_query(f"query {i}", priority=MessagePriority(i % 3))
            for i in range(10)
        ]
        prioritized = r.prioritize_queries(queries, edge_capacity=3)
        self.assertEqual(len(prioritized), 3)

    def test_batch_findings(self):
        r = ResearchRelay()
        findings = [r.submit_edge_finding("j1", {"i": i}) for i in range(15)]
        batches = r.batch_findings(findings, max_batch_size=5)
        self.assertEqual(len(batches), 3)

    def test_route_cloud_to_edge_direct(self):
        r = ResearchRelay()
        r.register_edge_node("j1", ["cuda"], {})
        msg = RelayMessage("m1", {}, MessageDirection.CLOUD_TO_EDGE, "o1", "j1")
        routing = r.route_message(msg)
        self.assertIn("direct_to_edge", routing["route"])

    def test_route_cloud_to_edge_broadcast(self):
        r = ResearchRelay()
        r.register_edge_node("j1", ["cuda"], {})
        r.register_edge_node("j2", ["sensors"], {})
        msg = RelayMessage("m1", {}, MessageDirection.CLOUD_TO_EDGE, "o1", "unknown")
        routing = r.route_message(msg)
        self.assertIn("broadcast_to_all_edges", routing["route"])

    def test_route_edge_to_cloud(self):
        r = ResearchRelay()
        msg = RelayMessage("m1", {}, MessageDirection.EDGE_TO_CLOUD, "j1", "cloud")
        routing = r.route_message(msg)
        self.assertIn("direct_to_cloud", routing["route"])

    def test_route_edge_to_edge_not_found(self):
        r = ResearchRelay()
        msg = RelayMessage("m1", {}, MessageDirection.EDGE_TO_EDGE, "j1", "ghost")
        routing = r.route_message(msg)
        self.assertIn("no_route", routing["route"])

    def test_status(self):
        r = ResearchRelay()
        r.register_cloud_source("o1", ["arch"])
        r.register_edge_node("j1", ["cuda"], {})
        s = r.status()
        self.assertEqual(s["cloud_sources_count"], 1)
        self.assertEqual(s["edge_nodes_count"], 1)

    def test_to_dict_from_dict(self):
        r = ResearchRelay()
        r.register_cloud_source("o1", ["arch"])
        r.register_edge_node("j1", ["cuda"], {"vram": 8})
        d = r.to_dict()
        r2 = ResearchRelay.from_dict(d)
        self.assertIn("o1", r2.cloud_sources)
        self.assertIn("j1", r2.edge_nodes)


# ═══════════════════════════════════════════════════════════════════════════
# 3. Tender Types
# ═══════════════════════════════════════════════════════════════════════════

class TestTenderTypes(unittest.TestCase):
    def test_research_tender_compress(self):
        t = ResearchTender()
        long_q = "First sentence. " * 200
        result = t.compress_query(long_q, bandwidth_limit=100)
        self.assertTrue(result["truncated"])

    def test_research_tender_session_lifecycle(self):
        t = ResearchTender()
        s = t.start_session("s1", "test query")
        self.assertEqual(s["status"], "active")
        t.add_session_finding("s1", {"result": True})
        c = t.complete_session("s1")
        self.assertEqual(c["status"], "completed")

    def test_data_tender_add_and_dedup(self):
        t = DataTender()
        t.add_event("model", {"output": 0.9})
        r = t.add_event("model", {"output": 0.9})
        self.assertFalse(r["accepted"])
        self.assertEqual(r["reason"], "duplicate")

    def test_data_tender_batch_priority(self):
        t = DataTender()
        t.add_event("general", {"info": "stuff"})
        t.add_event("trust", {"level": 0.9})
        batches = t.batch(max_batch_size=10)
        self.assertEqual(batches[0][0]["type"], "trust")

    def test_data_tender_flush_and_batch(self):
        t = DataTender()
        for i in range(3):
            t.add_event("trust", {"i": i})
        batches = t.flush_and_batch(max_batch_size=2)
        self.assertEqual(len(batches), 2)
        self.assertEqual(t.pending_count, 0)

    def test_priority_tender_critical_to_immediate(self):
        t = PriorityTender()
        r = t.cloud_to_edge_urgency(CloudUrgency.CRITICAL)
        self.assertEqual(r["edge_urgency"], "immediate")

    def test_priority_tender_deferral_escalation(self):
        t = PriorityTender()
        ctx = "kernel-bench"
        for _ in range(3):
            t.record_deferral(ctx)
        r = t.cloud_to_edge_urgency(CloudUrgency.LOW, context_id=ctx)
        self.assertEqual(r["edge_urgency"], "queued")
        self.assertTrue(r["escalated"])

    def test_priority_tender_configure_mapping(self):
        t = PriorityTender()
        t.configure_mapping(CloudUrgency.HIGH, EdgeUrgency.IMMEDIATE)
        r = t.cloud_to_edge_urgency(CloudUrgency.HIGH)
        self.assertEqual(r["edge_urgency"], "immediate")

    def test_context_tender_differential_update(self):
        t = ContextTender()
        t.update_context("j1", {"temp": 42, "status": "ok"})
        diff = t.update_context("j1", {"temp": 43, "status": "ok"})
        self.assertIn("temp", diff["changed_keys"])
        self.assertNotIn("status", diff["changed_keys"])

    def test_context_tender_conflict_detection(self):
        t = ContextTender()
        t.update_context("j1", {"v": 1})
        t.update_context("j1", {"v": 2})
        conflict = t.detect_conflict("j1", 1, {"v": "old"})
        self.assertIsNotNone(conflict)
        self.assertEqual(conflict["stored_version"], 2)

    def test_context_tender_sync_diff(self):
        t = ContextTender()
        t.update_context("j1", {"x": 1, "y": 2})
        sync = t.sync_diff("j1", since_version=0)
        self.assertTrue(sync["needs_sync"])
        self.assertTrue(sync["full_sync"])


# ═══════════════════════════════════════════════════════════════════════════
# 4. Bandwidth Management
# ═══════════════════════════════════════════════════════════════════════════

class TestBandwidthManagement(unittest.TestCase):
    def test_deliver_within_budget(self):
        b = BandwidthBudget(total_bps=1024)
        msg = BandwidthMessage("m1", payload_size=100, tender_type="research")
        result = b.allocate("research", msg)
        self.assertEqual(result["status"], "delivered")

    def test_queue_when_over_allocation(self):
        b = BandwidthBudget(total_bps=100)
        msg = BandwidthMessage("m1", payload_size=50, tender_type="context")
        result = b.allocate("context", msg)
        self.assertEqual(result["status"], "queued")

    def test_drop_when_exceeds_total(self):
        b = BandwidthBudget(total_bps=100)
        msg = BandwidthMessage("m1", payload_size=200, tender_type="research")
        result = b.allocate("research", msg)
        self.assertEqual(result["status"], "dropped")

    def test_adaptive_boost(self):
        b = BandwidthBudget(total_bps=100)
        b.add_active_session("s1", boost=2.0)
        msg = BandwidthMessage("m1", payload_size=70, tender_type="research")
        result = b.allocate("research", msg)
        self.assertEqual(result["status"], "delivered")

    def test_process_overflow(self):
        b = BandwidthBudget(total_bps=100)
        msg = BandwidthMessage("m1", payload_size=50, tender_type="research")
        b.allocate("research", msg)
        self.assertEqual(len(b.overflow_queue), 1)
        b.add_active_session("s1", boost=5.0)
        delivered = b.process_overflow(max_messages=5)
        self.assertEqual(len(delivered), 1)

    def test_preempt_low_priority(self):
        b = BandwidthBudget(total_bps=100)
        b.overflow_queue = [
            BandwidthMessage("low1", 10, priority=4, tender_type="general"),
            BandwidthMessage("crit1", 10, priority=0, tender_type="priority"),
        ]
        b.queued_bytes = 20
        dropped = b.preempt(max_priority=3)
        self.assertEqual(len(dropped), 1)
        self.assertEqual(len(b.overflow_queue), 1)

    def test_compression_engine_zlib(self):
        engine = CompressionEngine()
        data = json.dumps({"key": "value " * 100})
        result = engine.compress(data, strategy=CompressionStrategy.ZLIB)
        self.assertLess(result["compressed_size"], result["original_size"])
        self.assertEqual(result["strategy"], "zlib")

    def test_compression_engine_strip_metadata(self):
        engine = CompressionEngine()
        data = json.dumps({"core": "data", "metadata": "strip me", "_internal": "gone"})
        result = engine.compress(data, strategy=CompressionStrategy.STRIP_METADATA)
        self.assertNotIn("metadata", result["data"])
        self.assertNotIn("_internal", result["data"])

    def test_compression_engine_best_strategy(self):
        engine = CompressionEngine()
        data = json.dumps({"metadata": "x" * 500, "core": "keep this"})
        best = engine.best_strategy(data, max_bytes=100)
        self.assertIsNotNone(best)
        self.assertIn("strategy", best)

    def test_priority_queue_enqueue_dequeue(self):
        pq = PriorityQueue(max_size=10)
        pq.enqueue(BandwidthMessage("low", 10, priority=4))
        pq.enqueue(BandwidthMessage("high", 10, priority=0))
        msg = pq.dequeue()
        self.assertEqual(msg.message_id, "high")

    def test_priority_queue_eviction(self):
        pq = PriorityQueue(max_size=2)
        pq.enqueue(BandwidthMessage("a", 10, priority=2))
        pq.enqueue(BandwidthMessage("b", 10, priority=1))
        result = pq.enqueue(BandwidthMessage("c", 10, priority=0))
        self.assertIsNotNone(result.get("evicted"))


# ═══════════════════════════════════════════════════════════════════════════
# 5. Discovery
# ═══════════════════════════════════════════════════════════════════════════

class TestDiscovery(unittest.TestCase):
    def test_agent_record_creation(self):
        rec = AgentRecord(agent_id="test-agent", hostname="localhost")
        self.assertEqual(rec.agent_id, "test-agent")
        self.assertEqual(rec.state, AgentState.UNKNOWN)

    def test_agent_record_fingerprint(self):
        rec = AgentRecord(agent_id="a1", hostname="h1", capabilities=["cuda", "sensors"])
        fp = rec.fingerprint()
        self.assertIsInstance(fp, str)
        self.assertEqual(len(fp), 16)

    def test_agent_record_serialization(self):
        rec = AgentRecord(agent_id="a1", capabilities=["relay"])
        d = rec.to_dict()
        rec2 = AgentRecord.from_dict(d)
        self.assertEqual(rec2.agent_id, "a1")
        self.assertEqual(rec2.capabilities, ["relay"])

    def test_service_registry_register(self):
        reg = ServiceRegistry()
        agent = AgentRecord(agent_id="a1", capabilities=["relay", "research"])
        result = reg.register(agent)
        self.assertTrue(result["registered"])
        self.assertEqual(reg.size, 1)

    def test_service_registry_unregister(self):
        reg = ServiceRegistry()
        reg.register(AgentRecord(agent_id="a1", capabilities=["relay"]))
        self.assertTrue(reg.unregister("a1"))
        self.assertFalse(reg.unregister("a1"))
        self.assertEqual(reg.size, 0)

    def test_service_registry_find_by_capability(self):
        reg = ServiceRegistry()
        reg.register(AgentRecord(agent_id="a1", capabilities=["relay", "cuda"]))
        reg.register(AgentRecord(agent_id="a2", capabilities=["research"]))
        agents = reg.find_by_capability("relay")
        self.assertEqual(len(agents), 1)
        self.assertEqual(agents[0].agent_id, "a1")

    def test_service_registry_all_capabilities(self):
        reg = ServiceRegistry()
        reg.register(AgentRecord(agent_id="a1", capabilities=["z-cap", "a-cap"]))
        reg.register(AgentRecord(agent_id="a2", capabilities=["b-cap"]))
        caps = reg.all_capabilities()
        self.assertEqual(caps, ["a-cap", "b-cap", "z-cap"])

    def test_heartbeat_monitor_healthy(self):
        mon = HeartbeatMonitor(timeout=30.0, offline_threshold=90.0)
        agent = AgentRecord(agent_id="a1")
        mon.record_heartbeat(agent)
        state = mon.check_heartbeat(agent)
        self.assertEqual(state, AgentState.ACTIVE)

    def test_heartbeat_monitor_degraded(self):
        mon = HeartbeatMonitor(timeout=0.01, offline_threshold=90.0)
        agent = AgentRecord(agent_id="a1")
        mon.record_heartbeat(agent)
        time.sleep(0.02)
        state = mon.check_heartbeat(agent)
        self.assertEqual(state, AgentState.DEGRADED)

    def test_capability_advertiser(self):
        adv = CapabilityAdvertiser(agent_id="test", capabilities=["relay", "research"])
        ad = adv.build_advertisement()
        self.assertEqual(ad["agent_id"], "test")
        self.assertIn("relay", ad["capabilities"])
        adv.add_capability("monitoring")
        self.assertIn("monitoring", adv.capabilities)

    def test_discovery_service_full_flow(self):
        svc = DiscoveryService(agent_id="local", capabilities=["relay"])
        svc.register_self()
        svc.discover_agent("remote-1", hostname="edge-host",
                           capabilities=["cuda", "sensors"], port=9090)
        svc.heartbeat("remote-1")

        agents = svc.find_capable("cuda")
        self.assertEqual(len(agents), 1)
        self.assertEqual(agents[0].agent_id, "remote-1")

        report = svc.health_report()
        self.assertIn("total_agents", report)
        self.assertGreaterEqual(report["total_agents"], 2)

    def test_discovery_service_serialization(self):
        svc = DiscoveryService(agent_id="local", capabilities=["relay"])
        svc.register_self()
        d = svc.to_dict()
        svc2 = DiscoveryService.from_dict(d)
        self.assertEqual(svc2.agent_id, "local")


# ═══════════════════════════════════════════════════════════════════════════
# 6. Integration: Full Cloud -> Edge -> Cloud Round Trip
# ═══════════════════════════════════════════════════════════════════════════

class TestIntegration(unittest.TestCase):
    def test_full_round_trip(self):
        relay = ResearchRelay()
        tender = ResearchTender()
        data_tender = DataTender()

        # Register participants
        relay.register_cloud_source("oracle1", ["architecture"])
        relay.register_edge_node("jetson1", ["cuda", "sensors"], {"vram": 8192})

        # Cloud submits query
        query = relay.submit_research_query(
            "Benchmark matrix multiplication kernel on Orin",
            source_id="oracle1",
            priority=MessagePriority.HIGH,
        )

        # Compress for edge
        large_data = {
            "query": query.query_text,
            "background": "Extensive context. " * 50,
            "metadata": {"author": "oracle1", "history": "a" * 500},
        }
        compressed = relay.compress_for_edge(large_data, bandwidth_limit=128)
        self.assertTrue(compressed["truncated"])

        # Start session
        session = tender.start_session("bench-001", query.query_text)
        self.assertEqual(session["status"], "active")

        # Edge produces finding
        finding = relay.submit_edge_finding(
            "jetson1",
            {"kernel_ms": 12.4, "throughput_gflops": 8.7},
            query_id=query.query_id,
            priority=MessagePriority.HIGH,
        )

        # Expand for cloud
        expanded = relay.expand_from_edge(finding.data)
        self.assertEqual(expanded["data"]["kernel_ms"], 12.4)

        # Batch findings
        data_tender.add_event("model", tender.format_finding(
            finding.data, query_id=query.query_id, node_id="jetson1"
        ))
        batches = data_tender.flush_and_batch(max_batch_size=5)
        self.assertEqual(len(batches), 1)

        # Complete session
        tender.complete_session("bench-001")
        self.assertEqual(tender.sessions["bench-001"]["status"], "completed")

    def test_relay_with_discovery_and_bandwidth(self):
        relay = ResearchRelay()
        discovery = DiscoveryService(agent_id="relay-1", capabilities=["relay"])
        budget = BandwidthBudget(total_bps=512)

        discovery.register_self()
        discovery.discover_agent("edge-1", capabilities=["cuda"], port=9000)

        relay.register_edge_node("edge-1", ["cuda"], {"vram": 8192})

        msg = BandwidthMessage("m1", payload_size=100, tender_type="research", priority=0)
        alloc = budget.allocate("research", msg)
        self.assertEqual(alloc["status"], "delivered")

        route_msg = RelayMessage(
            "r1", {"benchmark": True},
            MessageDirection.CLOUD_TO_EDGE, "cloud", "edge-1",
        )
        routing = relay.route_message(route_msg)
        self.assertIn("direct_to_edge", routing["route"])


# ═══════════════════════════════════════════════════════════════════════════
# 7. CLI Commands (basic parsing, no network)
# ═══════════════════════════════════════════════════════════════════════════

class TestCLI(unittest.TestCase):
    def test_parse_onboard(self):
        from cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["onboard", "--agent-id", "test-cli"])
        self.assertEqual(args.command, "onboard")
        self.assertEqual(args.agent_id, "test-cli")

    def test_parse_status(self):
        from cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["status"])
        self.assertEqual(args.command, "status")

    def test_parse_bandwidth_verbose(self):
        from cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["bandwidth", "--verbose"])
        self.assertEqual(args.command, "bandwidth")
        self.assertTrue(args.verbose)

    def test_parse_register_cloud(self):
        from cli import build_parser
        parser = build_parser()
        args = parser.parse_args([
            "register-cloud", "https://api.example.com",
            "--name", "oracle1", "--capabilities", "arch,specs",
        ])
        self.assertEqual(args.command, "register-cloud")
        self.assertEqual(args.name, "oracle1")

    def test_parse_route(self):
        from cli import build_parser
        parser = build_parser()
        args = parser.parse_args([
            "route", "hello edge",
            "--from", "cloud", "--to", "jetson1",
            "--direction", "c2e", "--priority", "high",
        ])
        self.assertEqual(args.command, "route")
        self.assertEqual(args.source, "cloud")
        self.assertEqual(args.target, "jetson1")

    def test_onboard_creates_state(self):
        from cli import cmd_onboard, _load_state
        with tempfile.TemporaryDirectory() as tmpdir:
            class Args:
                state_dir = tmpdir
                agent_id = "test-agent"
                port = 9999
                bandwidth = 2048
                extra_capabilities = "monitoring"
                force = False

            result = cmd_onboard(Args())
            self.assertEqual(result, 0)
            state = _load_state(tmpdir)
            self.assertIsNotNone(state)
            self.assertEqual(state["version"], "1.0.0")

    def test_status_no_state(self):
        from cli import cmd_status
        with tempfile.TemporaryDirectory() as tmpdir:
            class Args:
                state_dir = tmpdir

            result = cmd_status(Args())
            self.assertEqual(result, 1)

    def test_discover_no_state(self):
        from cli import cmd_discover
        with tempfile.TemporaryDirectory() as tmpdir:
            class Args:
                state_dir = tmpdir
                agent_id = "test-cli"
                health = False
                capabilities = False

            result = cmd_discover(Args())
            self.assertEqual(result, 0)

    def test_main_no_command(self):
        from cli import main
        result = main([])
        self.assertEqual(result, 1)


# ═══════════════════════════════════════════════════════════════════════════
# 8. Edge Cases
# ═══════════════════════════════════════════════════════════════════════════

class TestEdgeCases(unittest.TestCase):
    def test_relay_empty_state(self):
        r = ResearchRelay()
        self.assertEqual(len(r.cloud_sources), 0)
        self.assertEqual(r.edge_nodes_count, 0) if hasattr(r, 'edge_nodes_count') else None
        d = r.to_dict()
        self.assertEqual(d["queries_count"], 0)

    def test_bandwidth_zero(self):
        b = BandwidthBudget(total_bps=0)
        msg = BandwidthMessage("m1", payload_size=10, tender_type="research")
        result = b.allocate("research", msg)
        self.assertEqual(result["status"], "dropped")

    def test_compression_with_empty_data(self):
        engine = CompressionEngine()
        result = engine.compress("", strategy=CompressionStrategy.ZLIB)
        self.assertIsNotNone(result)

    def test_priority_queue_empty_dequeue(self):
        pq = PriorityQueue()
        self.assertIsNone(pq.dequeue())
        self.assertEqual(pq.size, 0)

    def test_discovery_service_remove_nonexistent(self):
        svc = DiscoveryService(agent_id="local")
        self.assertFalse(svc.remove_agent("ghost"))

    def test_data_tender_batch_empty(self):
        t = DataTender()
        self.assertEqual(t.batch(), [])

    def test_context_tender_empty_sync(self):
        t = ContextTender()
        sync = t.sync_diff("ghost", since_version=0)
        self.assertFalse(sync["needs_sync"])

    def test_research_tender_complete_nonexistent(self):
        t = ResearchTender()
        result = t.complete_session("nonexistent")
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
