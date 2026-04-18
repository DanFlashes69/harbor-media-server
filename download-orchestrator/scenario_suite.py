import unittest

import orchestrate as orch


def make_torrent(
    torrent_hash: str,
    name: str,
    *,
    state: str = "queuedDL",
    category: str = "radarr",
    progress: float = 0.0,
    amount_left: int = 10 * 1024**3,
    dlspeed: int = 0,
    num_seeds: int = 0,
    availability: float = 0.0,
    has_metadata: bool = True,
    added_on: int | None = None,
    completion_on: int = 0,
    save_path: str | None = None,
    last_activity: int | None = None,
    seen_complete: int = 0,
) -> dict:
    return {
        "hash": torrent_hash,
        "name": name,
        "state": state,
        "category": category,
        "progress": progress,
        "amount_left": amount_left,
        "dlspeed": dlspeed,
        "num_seeds": num_seeds,
        "num_leechs": 0,
        "availability": availability,
        "has_metadata": has_metadata,
        "force_start": False,
        "added_on": added_on if added_on is not None else orch.now_ts() - 7200,
        "completion_on": completion_on,
        "save_path": save_path or f"/downloads/{category}",
        "last_activity": last_activity if last_activity is not None else orch.now_ts() - 7200,
        "seen_complete": seen_complete,
    }


class FakeStore:
    def __init__(self) -> None:
        self.runtime = {"probe_quarantine_until": {}}


class FakeQBClient:
    def __init__(self) -> None:
        self.rechecked: list[list[str]] = []
        self.reannounced: list[list[str]] = []
        self.stopped: list[list[str]] = []
        self.started: list[list[str]] = []
        self.deleted: list[dict[str, object]] = []

    def recheck(self, hashes: list[str]) -> None:
        self.rechecked.append(list(hashes))

    def reannounce(self, hashes: list[str]) -> None:
        self.reannounced.append(list(hashes))

    def stop(self, hashes: list[str]) -> None:
        self.stopped.append(list(hashes))

    def start(self, hashes: list[str]) -> None:
        self.started.append(list(hashes))

    def delete(self, hashes: list[str], delete_files: bool = False) -> None:
        self.deleted.append({"hashes": list(hashes), "deleteFiles": delete_files})


class OrchestratorScenarioTests(unittest.TestCase):
    def test_target_active_downloads_respects_health_budget_and_reserved_capacity_matrix(self) -> None:
        scenario_index = 0
        for free_gb in (12, 28, 80, 220):
            for healthy_count in (1, 2, 4):
                for reserved_count in (0, 1):
                    scenario_index += 1
                    candidates = [
                        make_torrent(
                            f"h{scenario_index}_{index}",
                            f"Healthy {index}",
                            state="queuedDL",
                            progress=0.85 if index < 2 else 0.35,
                            amount_left=(2 + index) * 1024**3,
                            num_seeds=3,
                            availability=3.0,
                        )
                        for index in range(healthy_count)
                    ]
                    candidates.extend(
                        make_torrent(
                            f"d{scenario_index}_{index}",
                            f"Dead {index}",
                            state="queuedDL",
                            progress=0.1,
                            amount_left=15 * 1024**3,
                            has_metadata=False,
                        )
                        for index in range(3)
                    )
                    stall = {torrent["hash"]: {"stalledSeconds": 0, "longStalled": False} for torrent in candidates}
                    metrics = orch.collect_workload_metrics(candidates, stall)
                    mode = orch.compute_mode(int(free_gb * 1024**3), len(candidates))
                    desired_total = orch.target_active_downloads(
                        mode,
                        candidates,
                        int(free_gb * 1024**3),
                        stall,
                        metrics,
                    )
                    desired = orch.managed_active_download_budget(desired_total, reserved_count, len(candidates))
                    budget_fit = orch.count_budget_fit_candidates(candidates, mode, int(free_gb * 1024**3), stall)
                    with self.subTest(free_gb=free_gb, healthy_count=healthy_count, reserved_count=reserved_count):
                        healthy_cap = healthy_count + (orch.CONFIG.expansive_probe_slots if mode == "expansive" else 0)
                        self.assertGreaterEqual(desired, 0)
                        self.assertLessEqual(desired, healthy_cap)
                        self.assertLessEqual(desired, budget_fit if budget_fit > 0 else healthy_count)
                        if reserved_count >= 1 and mode in {"focused", "emergency", "constrained"}:
                            self.assertLessEqual(desired, max(0, healthy_count - 0))

    def test_storage_limited_completion_first(self) -> None:
        candidates = [
            make_torrent(
                "a",
                "Finishable One",
                state="downloading",
                progress=0.92,
                amount_left=2 * 1024**3,
                dlspeed=250_000,
                num_seeds=2,
                availability=2.0,
            ),
            make_torrent(
                "b",
                "Finishable Two",
                state="downloading",
                progress=0.65,
                amount_left=4 * 1024**3,
                dlspeed=100_000,
                num_seeds=3,
                availability=3.5,
            ),
            make_torrent("c", "Dead Queue", state="queuedDL", amount_left=12 * 1024**3, has_metadata=False),
            make_torrent("d", "Dead Queue 2", state="queuedDL", amount_left=12 * 1024**3, has_metadata=False),
        ]
        stall = {torrent["hash"]: {"stalledSeconds": 0, "longStalled": False} for torrent in candidates}
        metrics = orch.collect_workload_metrics(candidates, stall)
        desired = orch.target_active_downloads("constrained", candidates, int(27 * 1024**3), stall, metrics)
        self.assertEqual(desired, 2)

    def test_expansive_mode_allows_more_healthy_torrents(self) -> None:
        candidates = [
            make_torrent(
                str(index),
                f"Healthy {index}",
                state="queuedDL",
                progress=0.2,
                amount_left=8 * 1024**3,
                num_seeds=5,
                availability=4.0,
                has_metadata=True,
            )
            for index in range(5)
        ]
        stall = {torrent["hash"]: {"stalledSeconds": 0, "longStalled": False} for torrent in candidates}
        metrics = orch.collect_workload_metrics(candidates, stall)
        desired = orch.target_active_downloads("expansive", candidates, int(250 * 1024**3), stall, metrics)
        self.assertGreaterEqual(desired, 3)

    def test_expansive_mode_keeps_probe_headroom_when_only_a_few_healthy_swarms_exist(self) -> None:
        candidates = [
            make_torrent(
                f"healthy-{index}",
                f"Healthy {index}",
                state="queuedDL",
                progress=0.35,
                amount_left=8 * 1024**3,
                num_seeds=3,
                availability=2.0,
            )
            for index in range(3)
        ]
        candidates.extend(
            make_torrent(
                f"probe-{index}",
                f"Probe {index}",
                state="stoppedDL",
                progress=0.15,
                amount_left=10 * 1024**3,
                num_seeds=0,
                availability=0.2,
            )
            for index in range(4)
        )
        stall = {torrent["hash"]: {"stalledSeconds": 0, "longStalled": False, "probeStalled": False} for torrent in candidates}
        metrics = orch.collect_workload_metrics(candidates, stall)
        desired = orch.target_active_downloads("expansive", candidates, int(500 * 1024**3), stall, metrics)
        self.assertEqual(desired, 7)

    def test_partial_resume_candidates_are_tracked_separately_from_healthy_pool(self) -> None:
        candidates = [
            make_torrent(
                "partial-a",
                "Partial A",
                state="stoppedDL",
                progress=0.41,
                amount_left=3 * 1024**3,
                num_seeds=0,
                availability=0.18,
            ),
            make_torrent(
                "partial-b",
                "Partial B",
                state="stoppedDL",
                progress=0.18,
                amount_left=6 * 1024**3,
                num_seeds=0,
                availability=0.09,
            ),
        ]
        stall = {torrent["hash"]: {"stalledSeconds": 0, "probeStalled": False, "longStalled": False} for torrent in candidates}
        metrics = orch.collect_workload_metrics(candidates, stall)
        self.assertEqual(metrics["healthyCandidateCount"], 0)
        self.assertEqual(metrics["partialResumeCount"], 2)

    def test_cold_dead_backlog_candidate_is_ignored_only_after_grace_period(self) -> None:
        old_dead = make_torrent(
            "old-dead",
            "Old Dead",
            state="stoppedDL",
            progress=0.0,
            has_metadata=False,
            added_on=orch.now_ts() - (orch.CONFIG.cold_dead_backlog_grace_seconds + 600),
            last_activity=orch.now_ts() - (orch.CONFIG.cold_dead_backlog_grace_seconds + 600),
        )
        recent_dead = make_torrent(
            "recent-dead",
            "Recent Dead",
            state="stoppedDL",
            progress=0.0,
            has_metadata=False,
            added_on=orch.now_ts() - 300,
            last_activity=orch.now_ts() - 300,
        )
        stall = {
            old_dead["hash"]: {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
            recent_dead["hash"]: {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
        }
        self.assertTrue(orch.is_cold_dead_backlog_candidate(old_dead, stall[old_dead["hash"]]))
        self.assertFalse(orch.is_cold_dead_backlog_candidate(recent_dead, stall[recent_dead["hash"]]))

    def test_partial_or_near_complete_items_are_not_treated_as_cold_dead_backlog(self) -> None:
        partial = make_torrent(
            "partial",
            "Partial Resume",
            state="stoppedDL",
            progress=0.35,
            availability=0.35,
            added_on=orch.now_ts() - (orch.CONFIG.cold_dead_backlog_grace_seconds + 600),
            last_activity=orch.now_ts() - (orch.CONFIG.cold_dead_backlog_grace_seconds + 600),
        )
        near_complete = make_torrent(
            "near-complete",
            "Near Complete",
            state="stalledDL",
            progress=0.96,
            availability=0.96,
            added_on=orch.now_ts() - (orch.CONFIG.cold_dead_backlog_grace_seconds + 600),
            last_activity=orch.now_ts() - (orch.CONFIG.cold_dead_backlog_grace_seconds + 600),
        )
        stall = {
            partial["hash"]: {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
            near_complete["hash"]: {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
        }
        self.assertFalse(orch.is_cold_dead_backlog_candidate(partial, stall[partial["hash"]]))
        self.assertFalse(orch.is_cold_dead_backlog_candidate(near_complete, stall[near_complete["hash"]]))

    def test_expansive_mode_resumes_partial_backlog_with_positive_availability(self) -> None:
        candidates = [
            make_torrent(
                "active",
                "Active",
                state="downloading",
                progress=0.96,
                amount_left=250 * 1024**2,
                dlspeed=700_000,
                num_seeds=3,
                availability=3.5,
            ),
            make_torrent(
                "partial-a",
                "Partial A",
                state="stoppedDL",
                progress=0.91,
                amount_left=2 * 1024**3,
                availability=0.91,
            ),
            make_torrent(
                "partial-b",
                "Partial B",
                state="stoppedDL",
                progress=0.62,
                amount_left=900 * 1024**2,
                availability=0.61,
            ),
            make_torrent(
                "partial-c",
                "Partial C",
                state="stoppedDL",
                progress=0.36,
                amount_left=7 * 1024**3,
                availability=0.35,
            ),
        ]
        stall = {torrent["hash"]: {"stalledSeconds": 0, "probeStalled": False, "longStalled": False} for torrent in candidates}
        metrics = orch.collect_workload_metrics(candidates, stall)
        desired = orch.target_active_downloads("expansive", candidates, int(500 * 1024**3), stall, metrics)
        allowed = orch.choose_allowed(FakeStore(), candidates, "expansive", int(500 * 1024**3), stall, desired)
        self.assertGreaterEqual(desired, 4)
        self.assertEqual([torrent["hash"] for torrent in allowed[:4]], ["active", "partial-a", "partial-b", "partial-c"])

    def test_single_torrent_speed_bias(self) -> None:
        metrics = {
            "movingCount": 1,
            "stalledRatio": 0.0,
            "highAvailabilityCount": 1,
            "averageMovingSpeed": 250_000,
            "completionPriorityCount": 1,
            "deadSwarmCount": 0,
            "healthyCandidateCount": 1,
            "metadataMissingCount": 0,
            "candidateCount": 1,
        }
        targets, reasons = orch.qbit_speed_targets("focused", 1, metrics)
        self.assertIn("single-moving-torrent-bias", reasons)
        self.assertIn("max_concurrent_http_announces", targets)
        self.assertGreaterEqual(targets["max_connec_per_torrent"], orch.CONFIG.speed_conn_per_torrent_focused + 20)

    def test_healthy_swarm_expansion_bias(self) -> None:
        metrics = {
            "movingCount": 0,
            "stalledRatio": 0.0,
            "highAvailabilityCount": 10,
            "averageMovingSpeed": 0,
            "completionPriorityCount": 0,
            "deadSwarmCount": 0,
            "healthyCandidateCount": 10,
            "metadataMissingCount": 0,
            "candidateCount": 12,
        }
        targets, reasons = orch.qbit_speed_targets("balanced", 2, metrics)
        self.assertIn("bootstrap-swarm-probe", reasons)
        self.assertIn("healthy-swarm-expansion", reasons)
        self.assertGreaterEqual(targets["max_connec"], orch.CONFIG.speed_conn_floor)
        self.assertGreaterEqual(targets["max_concurrent_http_announces"], orch.CONFIG.speed_http_announces_balanced + 20)

    def test_plan_qbit_pref_writes_emits_network_tuning_diffs_when_allowlisted(self) -> None:
        original_allowlist = orch.CONFIG.qbit_write_allowlist
        original_advanced = orch.CONFIG.allow_advanced_qbit_pref_writes
        try:
            object.__setattr__(orch.CONFIG, "allow_advanced_qbit_pref_writes", True)
            object.__setattr__(
                orch.CONFIG,
                "qbit_write_allowlist",
                (
                    "max_active_downloads",
                    "max_active_torrents",
                    "max_active_uploads",
                    "max_connec",
                    "max_connec_per_torrent",
                    "max_uploads_per_torrent",
                    "connection_speed",
                    "max_concurrent_http_announces",
                    "async_io_threads",
                    "disk_cache",
                    "disk_cache_ttl",
                    "disk_queue_size",
                    "request_queue_size",
                    "enable_piece_extent_affinity",
                    "enable_coalesce_read_write",
                    "send_buffer_low_watermark",
                    "send_buffer_watermark",
                    "send_buffer_watermark_factor",
                    "socket_backlog_size",
                    "peer_turnover",
                    "peer_turnover_cutoff",
                    "peer_turnover_interval",
                    "file_pool_size",
                    "checking_memory_use",
                ),
            )
            prefs = {
                "max_active_downloads": 3,
                "max_active_torrents": 5,
                "max_active_uploads": 5,
                "max_connec": 500,
                "max_connec_per_torrent": 100,
                "max_uploads_per_torrent": 10,
                "connection_speed": 30,
                "max_concurrent_http_announces": 50,
                "async_io_threads": 10,
                "disk_cache": -1,
                "disk_cache_ttl": 60,
                "disk_queue_size": 1048576,
                "request_queue_size": 500,
                "enable_piece_extent_affinity": False,
                "enable_coalesce_read_write": False,
                "send_buffer_low_watermark": 10,
                "send_buffer_watermark": 500,
                "send_buffer_watermark_factor": 50,
                "socket_backlog_size": 30,
                "peer_turnover": 4,
                "peer_turnover_cutoff": 90,
                "peer_turnover_interval": 300,
                "file_pool_size": 100,
                "checking_memory_use": 32,
            }
            metrics = {
                "movingCount": 0,
                "stalledRatio": 0.0,
                "highAvailabilityCount": 8,
                "averageMovingSpeed": 0,
                "completionPriorityCount": 0,
                "deadSwarmCount": 1,
                "healthyCandidateCount": 8,
                "metadataMissingCount": 0,
                "candidateCount": 10,
            }
            updates, diffs, _, reasons = orch.plan_qbit_pref_writes(prefs, 2, "balanced", metrics)
            self.assertIn("healthy-swarm-expansion", reasons)
            self.assertIn("max_connec", updates)
            self.assertIn("connection_speed", updates)
            self.assertIn("max_concurrent_http_announces", updates)
            self.assertIn("max_connec_per_torrent", diffs)
            self.assertIn("disk_cache", updates)
            self.assertIn("enable_piece_extent_affinity", updates)
            self.assertIn("checking_memory_use", updates)
        finally:
            object.__setattr__(orch.CONFIG, "allow_advanced_qbit_pref_writes", original_advanced)
            object.__setattr__(orch.CONFIG, "qbit_write_allowlist", original_allowlist)

    def test_tunnel_guard_blocks_on_port_or_interface_drift(self) -> None:
        ok, _ = orch.tunnel_guard(
            {"listen_port": 12345, "current_network_interface": "eth0", "queueing_enabled": True},
            58947,
        )
        self.assertFalse(ok)

    def test_protected_settings_guard_blocks_category_drift(self) -> None:
        store = FakeStore()
        prefs = {
            key: {
                "current_network_interface": "tun0",
                "save_path": "/downloads",
                "temp_path": "/downloads/incomplete",
                "temp_path_enabled": True,
                "queueing_enabled": True,
                "proxy_type": "None",
                "proxy_ip": "",
                "proxy_port": 8080,
                "proxy_hostname_lookup": False,
                "proxy_bittorrent": True,
                "proxy_misc": True,
                "proxy_rss": True,
                "web_ui_port": 8081,
                "web_ui_username": "user",
                "web_ui_address": "*",
                "use_https": False,
                "upnp": False,
            }[key]
            for key in orch.PROTECTED_QBIT_PREF_KEYS
        }
        baseline_categories = {
            "radarr": {"savePath": "/downloads/radarr"},
            "sonarr": {"savePath": "/downloads/sonarr"},
            "lidarr": {"savePath": "/downloads/lidarr"},
        }
        ok, _ = orch.protected_settings_guard(store, prefs, baseline_categories)
        self.assertTrue(ok)
        drift_categories = {
            "radarr": {"savePath": "/downloads/wrong"},
            "sonarr": {"savePath": "/downloads/sonarr"},
            "lidarr": {"savePath": "/downloads/lidarr"},
        }
        ok, details = orch.protected_settings_guard(store, prefs, drift_categories)
        self.assertFalse(ok)
        self.assertIn("radarr", details["categoryPathDrift"])

    def test_protected_settings_guard_ignores_forwarded_port_rotation(self) -> None:
        store = FakeStore()
        baseline_prefs = {
            key: {
                "current_network_interface": "tun0",
                "save_path": "/downloads",
                "temp_path": "/downloads/incomplete",
                "temp_path_enabled": True,
                "queueing_enabled": True,
                "proxy_type": "None",
                "proxy_ip": "",
                "proxy_port": 8080,
                "proxy_hostname_lookup": False,
                "proxy_bittorrent": True,
                "proxy_misc": True,
                "proxy_rss": True,
                "web_ui_port": 8081,
                "web_ui_username": "user",
                "web_ui_address": "*",
                "use_https": False,
                "upnp": False,
            }[key]
            for key in orch.PROTECTED_QBIT_PREF_KEYS
        }
        categories = {
            "radarr": {"savePath": "/downloads/radarr"},
            "sonarr": {"savePath": "/downloads/sonarr"},
            "lidarr": {"savePath": "/downloads/lidarr"},
        }
        ok, _ = orch.protected_settings_guard(store, baseline_prefs, categories)
        self.assertTrue(ok)

        rotated_port_prefs = dict(baseline_prefs)
        rotated_port_prefs["listen_port"] = 36367
        ok, details = orch.protected_settings_guard(store, rotated_port_prefs, categories)
        self.assertTrue(ok)
        self.assertEqual(details["prefDrift"], {})

    def test_protected_settings_guard_prunes_legacy_baseline_keys(self) -> None:
        store = FakeStore()
        store.runtime["protected_qbit_pref_baseline"] = {
            "current_network_interface": "tun0",
            "listen_port": 58947,
            "save_path": "/downloads",
            "temp_path": "/downloads/incomplete",
            "temp_path_enabled": True,
            "queueing_enabled": True,
        }
        prefs = {
            "current_network_interface": "tun0",
            "save_path": "/downloads",
            "temp_path": "/downloads/incomplete",
            "temp_path_enabled": True,
            "queueing_enabled": True,
        }
        categories = {
            "radarr": {"savePath": "/downloads/radarr"},
            "sonarr": {"savePath": "/downloads/sonarr"},
            "lidarr": {"savePath": "/downloads/lidarr"},
        }
        ok, details = orch.protected_settings_guard(store, prefs, categories)
        self.assertTrue(ok)
        self.assertNotIn("listen_port", store.runtime["protected_qbit_pref_baseline"])
        self.assertEqual(details["prefDrift"], {})

    def test_action_plan_stops_downloader_overage_before_backlog(self) -> None:
        candidates = [
            make_torrent("keep1", "Keep 1", state="downloading", dlspeed=500_000, progress=0.9, amount_left=1 * 1024**3, num_seeds=4, availability=3.0),
            make_torrent("keep2", "Keep 2", state="downloading", dlspeed=300_000, progress=0.8, amount_left=2 * 1024**3, num_seeds=3, availability=2.5),
            make_torrent("drop1", "Drop 1", state="downloading", dlspeed=50_000, progress=0.3, amount_left=15 * 1024**3, num_seeds=1, availability=1.2),
            make_torrent("drop2", "Drop 2", state="downloading", dlspeed=40_000, progress=0.2, amount_left=14 * 1024**3, num_seeds=1, availability=1.1),
            make_torrent("queue1", "Queue 1", state="queuedDL", has_metadata=False),
            make_torrent("queue2", "Queue 2", state="queuedDL", has_metadata=False),
            make_torrent("queue3", "Queue 3", state="queuedDL", has_metadata=False),
            make_torrent("queue4", "Queue 4", state="queuedDL", has_metadata=False),
        ]
        stall = {torrent["hash"]: {"stalledSeconds": 0, "longStalled": False} for torrent in candidates}
        to_stop, _ = orch.plan_torrent_actions(candidates, {"keep1", "keep2"}, "constrained", stall, 2)
        self.assertGreaterEqual(len(to_stop), 2)
        self.assertEqual(to_stop[:2], ["drop2", "drop1"])

    def test_action_plan_does_not_restart_probe_stalled_allowed_torrent(self) -> None:
        candidates = [
            make_torrent(
                "probe-stalled",
                "Probe Stalled",
                state="stalledDL",
                category="lidarr",
                progress=0.2,
                amount_left=500 * 1024**2,
                availability=1.1,
                num_seeds=1,
            )
        ]
        stall = {"probe-stalled": {"stalledSeconds": 400, "probeStalled": True, "longStalled": False}}
        to_stop, to_start = orch.plan_torrent_actions(candidates, {"probe-stalled"}, "constrained", stall, 1)
        self.assertEqual(to_stop, [])
        self.assertEqual(to_start, [])

    def test_force_started_download_reserves_capacity(self) -> None:
        candidates = [
            make_torrent(
                "managed1",
                "Managed One",
                state="queuedDL",
                progress=0.9,
                amount_left=1 * 1024**3,
                num_seeds=2,
                availability=2.0,
            ),
            make_torrent(
                "managed2",
                "Managed Two",
                state="queuedDL",
                progress=0.8,
                amount_left=2 * 1024**3,
                num_seeds=2,
                availability=2.2,
            ),
        ]
        reserved = make_torrent(
            "forced",
            "User Forced",
            state="forcedDL",
            progress=0.5,
            amount_left=5 * 1024**3,
            dlspeed=400_000,
            num_seeds=3,
            availability=3.0,
        )
        reserved["force_start"] = True
        stall = {torrent["hash"]: {"stalledSeconds": 0, "longStalled": False} for torrent in candidates}
        reserved_torrents = orch.reserved_active_downloads([reserved], {})
        metrics = orch.collect_workload_metrics(candidates, stall)
        desired_total = orch.target_active_downloads(
            "constrained",
            candidates,
            int(30 * 1024**3),
            stall,
            metrics,
        )
        desired = orch.managed_active_download_budget(desired_total, len(reserved_torrents), len(candidates))
        self.assertEqual(len(reserved_torrents), 1)
        self.assertEqual(desired_total, 2)
        self.assertEqual(desired, 1)

    def test_weak_force_started_download_does_not_consume_reserved_slot(self) -> None:
        candidates = [
            make_torrent(
                "managed1",
                "Managed One",
                state="queuedDL",
                progress=0.85,
                amount_left=2 * 1024**3,
                num_seeds=4,
                availability=2.5,
            ),
            make_torrent(
                "managed2",
                "Managed Two",
                state="queuedDL",
                progress=0.55,
                amount_left=4 * 1024**3,
                num_seeds=3,
                availability=2.2,
            ),
        ]
        weak_forced = make_torrent(
            "forced",
            "Weak Forced",
            state="forcedDL",
            progress=0.9,
            amount_left=8 * 1024**3,
            dlspeed=2_000,
            num_seeds=2,
            availability=1.8,
        )
        weak_forced["force_start"] = True
        stall = {torrent["hash"]: {"stalledSeconds": 0, "longStalled": False} for torrent in candidates}
        reserved = orch.reserved_active_downloads([weak_forced], {})
        weak_reserved = orch.weak_reserved_active_downloads([weak_forced], {})
        metrics = orch.collect_workload_metrics(candidates, stall)
        desired_total = orch.target_active_downloads(
            "constrained",
            candidates,
            int(30 * 1024**3),
            stall,
            metrics,
        )
        desired = orch.managed_active_download_budget(desired_total, len(reserved), len(candidates), len(weak_reserved))
        self.assertEqual(reserved, [])
        self.assertEqual(len(weak_reserved), 1)
        self.assertEqual(desired, 1)

    def test_near_complete_force_started_download_reserves_capacity_even_when_slow(self) -> None:
        candidates = [
            make_torrent(
                "managed1",
                "Managed One",
                state="queuedDL",
                progress=0.45,
                amount_left=5 * 1024**3,
                num_seeds=20,
                availability=12.0,
            ),
        ]
        near_complete_forced = make_torrent(
            "forced-near-complete",
            "Near Complete Forced",
            state="forcedDL",
            progress=0.987,
            amount_left=400 * 1024**2,
            dlspeed=12_000,
            num_seeds=1,
            availability=2.0,
        )
        near_complete_forced["force_start"] = True
        stall = {torrent["hash"]: {"stalledSeconds": 0, "longStalled": False} for torrent in candidates}
        reserved = orch.reserved_active_downloads([near_complete_forced], {})
        weak_reserved = orch.weak_reserved_active_downloads([near_complete_forced], {})
        metrics = orch.collect_workload_metrics(candidates, stall)
        desired_total = orch.target_active_downloads(
            "emergency",
            candidates,
            int(12 * 1024**3),
            stall,
            metrics,
        )
        desired = orch.managed_active_download_budget(desired_total, len(reserved), len(candidates), len(weak_reserved))
        self.assertEqual(len(reserved), 1)
        self.assertEqual(weak_reserved, [])
        self.assertEqual(desired, 0)

    def test_choose_allowed_never_exceeds_budget_after_first_pick(self) -> None:
        candidates = [
            make_torrent("a", "A", progress=0.95, amount_left=2 * 1024**3, num_seeds=2, availability=2.0),
            make_torrent("b", "B", progress=0.85, amount_left=6 * 1024**3, num_seeds=2, availability=2.0),
            make_torrent("c", "C", progress=0.75, amount_left=9 * 1024**3, num_seeds=2, availability=2.0),
            make_torrent("d", "D", progress=0.25, amount_left=20 * 1024**3, num_seeds=2, availability=2.0),
        ]
        stall = {torrent["hash"]: {"stalledSeconds": 0, "longStalled": False} for torrent in candidates}
        allowed = orch.choose_allowed(FakeStore(), candidates, "constrained", int(30 * 1024**3), stall, 3)
        total_remaining = sum(t["amount_left"] for t in allowed[1:])
        self.assertLessEqual(total_remaining, int((30 - orch.CONFIG.reserved_free_gb) * 1024**3))

    def test_choose_allowed_skips_missing_files_after_first_pick(self) -> None:
        candidates = [
            make_torrent(
                "healthy",
                "Healthy",
                state="downloading",
                dlspeed=3 * 1024**2,
                progress=0.6,
                amount_left=2 * 1024**3,
                num_seeds=4,
                availability=2.0,
                category="radarr",
            ),
            make_torrent(
                "missing",
                "Missing Files",
                state="missingFiles",
                progress=0.4,
                amount_left=4 * 1024**3,
                num_seeds=0,
                availability=0.0,
                category="radarr",
            ),
            make_torrent(
                "viable",
                "Viable",
                state="stoppedDL",
                progress=0.2,
                amount_left=3 * 1024**3,
                num_seeds=2,
                availability=1.4,
                category="radarr",
            ),
        ]
        stall = {
            torrent["hash"]: {"stalledSeconds": 0, "probeStalled": False, "longStalled": False}
            for torrent in candidates
        }
        allowed = orch.choose_allowed(FakeStore(), candidates, "expansive", int(30 * 1024**3), stall, 2)
        self.assertEqual([torrent["hash"] for torrent in allowed], ["healthy", "viable"])

    def test_constrained_selection_prefers_viable_seeded_swarm_over_zero_seed_probe(self) -> None:
        candidates = [
            make_torrent(
                "probe",
                "Probe",
                state="stoppedDL",
                dlspeed=0,
                progress=0.05,
                amount_left=1 * 1024**3,
                num_seeds=0,
                availability=0.04,
                category="sonarr",
            ),
            make_torrent(
                "seeded",
                "Seeded",
                state="stalledDL",
                dlspeed=0,
                progress=0.01,
                amount_left=350 * 1024**2,
                num_seeds=1,
                availability=1.01,
                category="lidarr",
            ),
        ]
        stall = {torrent["hash"]: {"stalledSeconds": 0, "longStalled": False} for torrent in candidates}
        allowed = orch.choose_allowed(FakeStore(), candidates, "constrained", int(25 * 1024**3), stall, 1)
        self.assertEqual([torrent["hash"] for torrent in allowed], ["seeded"])

    def test_choose_allowed_rotates_away_from_stalled_active_probe(self) -> None:
        stalled_active = make_torrent(
            "stalled",
            "Stalled Active",
            state="stalledDL",
            dlspeed=0,
            progress=0.35,
            amount_left=2 * 1024**3,
            num_seeds=1,
            availability=1.05,
            category="lidarr",
        )
        fresh_probe = make_torrent(
            "fresh",
            "Fresh Probe",
            state="stoppedDL",
            dlspeed=0,
            progress=0.05,
            amount_left=3 * 1024**3,
            num_seeds=2,
            availability=1.4,
            category="sonarr",
        )
        stall = {
            "stalled": {"stalledSeconds": orch.CONFIG.probe_rotation_seconds + 5, "probeStalled": False, "longStalled": False},
            "fresh": {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
        }
        allowed = orch.choose_allowed(FakeStore(), [stalled_active, fresh_probe], "constrained", int(30 * 1024**3), stall, 1)
        self.assertEqual([torrent["hash"] for torrent in allowed], ["fresh"])

    def test_choose_allowed_falls_back_when_only_rotated_probe_exists(self) -> None:
        stalled_active = make_torrent(
            "stalled",
            "Only Probe",
            state="stalledDL",
            dlspeed=0,
            progress=0.35,
            amount_left=2 * 1024**3,
            num_seeds=1,
            availability=1.05,
            category="lidarr",
        )
        stall = {
            "stalled": {"stalledSeconds": orch.CONFIG.probe_rotation_seconds + 5, "probeStalled": False, "longStalled": False},
        }
        allowed = orch.choose_allowed(FakeStore(), [stalled_active], "constrained", int(30 * 1024**3), stall, 1)
        self.assertEqual([torrent["hash"] for torrent in allowed], ["stalled"])

    def test_expansive_choose_allowed_bootstraps_multiple_candidates_when_no_active_downloads(self) -> None:
        completion = make_torrent(
            "completion",
            "Almost Done",
            state="stalledDL",
            progress=0.996,
            amount_left=32 * 1024**2,
            num_seeds=1,
            availability=1.9,
            has_metadata=True,
            added_on=100,
        )
        partial = make_torrent(
            "partial",
            "Partial Resume",
            state="stoppedDL",
            progress=0.54,
            amount_left=int(1.4 * 1024**3),
            num_seeds=0,
            availability=0.54,
            has_metadata=True,
            added_on=200,
        )
        meta_a = make_torrent(
            "meta-a",
            "Metadata Bootstrap A",
            state="stoppedDL",
            progress=0.0,
            amount_left=0,
            has_metadata=False,
            added_on=300,
        )
        meta_a["trackers_count"] = 12
        meta_b = make_torrent(
            "meta-b",
            "Metadata Bootstrap B",
            state="stoppedDL",
            progress=0.0,
            amount_left=0,
            has_metadata=False,
            added_on=400,
        )
        meta_b["trackers_count"] = 10
        stall = {
            "completion": {"stalledSeconds": orch.CONFIG.probe_rotation_seconds + 30, "probeStalled": False, "longStalled": False},
            "partial": {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
            "meta-a": {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
            "meta-b": {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
        }
        allowed = orch.choose_allowed(
            FakeStore(),
            [completion, partial, meta_a, meta_b],
            "expansive",
            int(500 * 1024**3),
            stall,
            4,
        )
        self.assertEqual([torrent["hash"] for torrent in allowed], ["completion", "partial", "meta-a", "meta-b"])

    def test_expansive_choose_allowed_backfills_when_only_one_downloader_is_moving(self) -> None:
        moving = make_torrent(
            "moving",
            "Weak Mover",
            state="downloading",
            dlspeed=220 * 1024,
            progress=0.31,
            amount_left=int(1.8 * 1024**3),
            num_seeds=1,
            availability=1.2,
            added_on=100,
        )
        completion = make_torrent(
            "completion",
            "Almost Done",
            state="stalledDL",
            progress=0.996,
            amount_left=32 * 1024**2,
            num_seeds=1,
            availability=1.9,
            has_metadata=True,
            added_on=200,
        )
        meta_a = make_torrent(
            "meta-a",
            "Metadata Bootstrap A",
            state="stoppedDL",
            progress=0.0,
            amount_left=0,
            has_metadata=False,
            added_on=300,
        )
        meta_a["trackers_count"] = 12
        meta_b = make_torrent(
            "meta-b",
            "Metadata Bootstrap B",
            state="stoppedDL",
            progress=0.0,
            amount_left=0,
            has_metadata=False,
            added_on=400,
        )
        meta_b["trackers_count"] = 10
        stall = {
            "moving": {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
            "completion": {"stalledSeconds": orch.CONFIG.probe_rotation_seconds + 30, "probeStalled": False, "longStalled": False},
            "meta-a": {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
            "meta-b": {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
        }
        allowed = orch.choose_allowed(
            FakeStore(),
            [moving, completion, meta_a, meta_b],
            "expansive",
            int(500 * 1024**3),
            stall,
            4,
        )
        self.assertEqual([torrent["hash"] for torrent in allowed], ["moving", "completion", "meta-a", "meta-b"])

    def test_expansive_choose_allowed_backfills_when_only_two_downloaders_are_moving(self) -> None:
        moving_a = make_torrent(
            "moving-a",
            "Mover A",
            state="downloading",
            dlspeed=900 * 1024,
            progress=0.44,
            amount_left=int(6 * 1024**3),
            num_seeds=3,
            availability=2.4,
            added_on=100,
        )
        moving_b = make_torrent(
            "moving-b",
            "Mover B",
            state="downloading",
            dlspeed=600 * 1024,
            progress=0.27,
            amount_left=int(8 * 1024**3),
            num_seeds=2,
            availability=1.9,
            added_on=200,
        )
        completion = make_torrent(
            "completion",
            "Almost Done",
            state="stalledDL",
            progress=0.996,
            amount_left=24 * 1024**2,
            num_seeds=1,
            availability=0.99,
            has_metadata=True,
            added_on=300,
        )
        partial = make_torrent(
            "partial",
            "Partial Resume",
            state="stoppedDL",
            progress=0.82,
            amount_left=int(2 * 1024**3),
            num_seeds=0,
            availability=0.82,
            has_metadata=True,
            added_on=400,
        )
        meta_a = make_torrent(
            "meta-a",
            "Metadata Bootstrap A",
            state="stoppedDL",
            progress=0.0,
            amount_left=0,
            has_metadata=False,
            added_on=500,
        )
        meta_a["trackers_count"] = 12
        stall = {
            "moving-a": {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
            "moving-b": {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
            "completion": {"stalledSeconds": orch.CONFIG.probe_rotation_seconds + 30, "probeStalled": False, "longStalled": False},
            "partial": {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
            "meta-a": {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
        }
        allowed = orch.choose_allowed(
            FakeStore(),
            [moving_a, moving_b, completion, partial, meta_a],
            "expansive",
            int(500 * 1024**3),
            stall,
            5,
        )
        self.assertEqual([torrent["hash"] for torrent in allowed], ["moving-a", "moving-b", "completion", "partial", "meta-a"])

    def test_near_complete_stalled_download_is_reserved_until_long_stalled(self) -> None:
        stalled = make_torrent(
            "stalled",
            "Nearly Finished",
            state="stalledDL",
            progress=0.996,
            amount_left=32 * 1024**2,
            num_seeds=0,
            availability=0.99,
        )
        self.assertTrue(
            orch.should_reserve_completion_priority_active(
                stalled,
                {"stalledSeconds": orch.CONFIG.probe_rotation_seconds + 30, "probeStalled": True, "longStalled": False},
            )
        )
        self.assertFalse(
            orch.should_reserve_completion_priority_active(
                stalled,
                {"stalledSeconds": orch.CONFIG.stall_failover_seconds + 30, "probeStalled": True, "longStalled": True},
            )
        )

    def test_choose_allowed_returns_empty_when_only_dead_zero_seed_probes_exist(self) -> None:
        dead_probe = make_torrent(
            "dead",
            "Dead Probe",
            state="stoppedDL",
            dlspeed=0,
            progress=0.05,
            amount_left=1 * 1024**3,
            num_seeds=0,
            availability=0.04,
            category="sonarr",
        )
        stall = {
            "dead": {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
        }
        allowed = orch.choose_allowed(FakeStore(), [dead_probe], "constrained", int(30 * 1024**3), stall, 1)
        self.assertEqual(allowed, [])

    def test_choose_allowed_uses_best_effort_fallback_when_no_healthy_probe_exists(self) -> None:
        partial = make_torrent(
            "partial",
            "Partial Recovery Candidate",
            state="stoppedDL",
            dlspeed=0,
            progress=0.22,
            amount_left=3 * 1024**3,
            num_seeds=0,
            availability=0.22,
            category="radarr",
        )
        dead = make_torrent(
            "dead",
            "Dead Candidate",
            state="stoppedDL",
            dlspeed=0,
            progress=0.0,
            amount_left=8 * 1024**3,
            num_seeds=0,
            availability=0.0,
            category="sonarr",
        )
        stall = {
            "partial": {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
            "dead": {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
        }
        allowed = orch.choose_allowed(FakeStore(), [dead, partial], "emergency", int(12 * 1024**3), stall, 1)
        self.assertEqual([torrent["hash"] for torrent in allowed], ["partial"])

    def test_low_space_selection_prefers_more_finished_partial_over_less_finished_healthier_candidate(self) -> None:
        more_finished = make_torrent(
            "more-finished",
            "More Finished",
            state="stoppedDL",
            progress=0.31,
            amount_left=16 * 1024**3,
            num_seeds=0,
            availability=0.31,
            category="radarr",
        )
        less_finished_healthier = make_torrent(
            "less-finished",
            "Less Finished But Healthier",
            state="stoppedDL",
            progress=0.18,
            amount_left=2.5 * 1024**3,
            num_seeds=3,
            availability=3.2,
            category="radarr",
        )
        stall = {
            "more-finished": {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
            "less-finished": {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
        }
        allowed = orch.choose_allowed(
            FakeStore(),
            [less_finished_healthier, more_finished],
            "emergency",
            int(12 * 1024**3),
            stall,
            1,
        )
        self.assertEqual([torrent["hash"] for torrent in allowed], ["more-finished"])

    def test_low_space_selection_replaces_active_less_finished_torrent_with_more_finished_partial(self) -> None:
        active_less_finished = make_torrent(
            "active-less-finished",
            "Active Less Finished",
            state="downloading",
            dlspeed=900 * 1024,
            progress=0.18,
            amount_left=2.5 * 1024**3,
            num_seeds=3,
            availability=3.2,
            category="radarr",
        )
        more_finished = make_torrent(
            "more-finished",
            "More Finished",
            state="stoppedDL",
            progress=0.31,
            amount_left=16 * 1024**3,
            num_seeds=0,
            availability=0.31,
            category="radarr",
        )
        stall = {
            "active-less-finished": {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
            "more-finished": {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
        }
        allowed = orch.choose_allowed(
            FakeStore(),
            [active_less_finished, more_finished],
            "emergency",
            int(12 * 1024**3),
            stall,
            1,
        )
        self.assertEqual([torrent["hash"] for torrent in allowed], ["more-finished"])

    def test_maybe_apply_torrent_control_quarantines_rotated_probe(self) -> None:
        store = FakeStore()
        client = FakeQBClient()
        torrent = make_torrent(
            "stalled",
            "Rotated Probe",
            state="stalledDL",
            dlspeed=0,
            progress=0.2,
            amount_left=1 * 1024**3,
            num_seeds=1,
            availability=1.02,
        )
        stall = {
            "stalled": {"stalledSeconds": orch.CONFIG.probe_rotation_seconds + 5, "probeStalled": False, "longStalled": False},
        }
        original_observe = orch.CONFIG.observe_only
        original_allow = orch.CONFIG.allow_torrent_control
        try:
            object.__setattr__(orch.CONFIG, "observe_only", False)
            object.__setattr__(orch.CONFIG, "allow_torrent_control", True)
            changed = orch.maybe_apply_torrent_control(store, client, [torrent], stall, ["stalled"], [], True)
            self.assertTrue(changed)
            self.assertEqual(client.stopped, [["stalled"]])
            self.assertIn("stalled", store.runtime["probe_quarantine_until"])
        finally:
            object.__setattr__(orch.CONFIG, "observe_only", original_observe)
            object.__setattr__(orch.CONFIG, "allow_torrent_control", original_allow)

    def test_maybe_apply_torrent_control_quarantines_replaced_nonmoving_probe(self) -> None:
        store = FakeStore()
        client = FakeQBClient()
        torrent = make_torrent(
            "probe",
            "Replaced Probe",
            state="stalledDL",
            dlspeed=0,
            progress=0.15,
            amount_left=1 * 1024**3,
            num_seeds=0,
            availability=0.04,
        )
        stall = {
            "probe": {"stalledSeconds": 30, "probeStalled": False, "longStalled": False},
        }
        original_observe = orch.CONFIG.observe_only
        original_allow = orch.CONFIG.allow_torrent_control
        try:
            object.__setattr__(orch.CONFIG, "observe_only", False)
            object.__setattr__(orch.CONFIG, "allow_torrent_control", True)
            changed = orch.maybe_apply_torrent_control(store, client, [torrent], stall, ["probe"], [], True)
            self.assertTrue(changed)
            self.assertEqual(client.stopped, [["probe"]])
            self.assertIn("probe", store.runtime["probe_quarantine_until"])
        finally:
            object.__setattr__(orch.CONFIG, "observe_only", original_observe)
            object.__setattr__(orch.CONFIG, "allow_torrent_control", original_allow)

    def test_rotation_urgent_shortens_torrent_action_cooldown(self) -> None:
        store = FakeStore()
        original_default = orch.CONFIG.min_torrent_action_interval_seconds
        original_rotation = orch.CONFIG.min_rotation_action_interval_seconds
        try:
            object.__setattr__(orch.CONFIG, "min_torrent_action_interval_seconds", 300)
            object.__setattr__(orch.CONFIG, "min_rotation_action_interval_seconds", 60)
            store.runtime["stability"] = {
                "lastTorrentActionAt": orch.now_ts() - 90,
                "modeSignature": "constrained",
                "selectionSignature": orch.stable_signature({"start": ["start-hash"], "stop": ["stop-hash"]}),
                "selectionStableCycles": orch.CONFIG.control_stability_cycles,
            }
            meta = orch.update_stability_guard(
                store,
                "constrained",
                ["stop-hash"],
                ["start-hash"],
                {},
                rotation_urgent=True,
            )
            self.assertTrue(meta["torrentControlReady"])
            self.assertEqual(meta["effectiveTorrentActionIntervalSeconds"], 60)
        finally:
            object.__setattr__(orch.CONFIG, "min_torrent_action_interval_seconds", original_default)
            object.__setattr__(orch.CONFIG, "min_rotation_action_interval_seconds", original_rotation)

    def test_update_stability_guard_bootstraps_immediately_when_no_active_downloads(self) -> None:
        store = FakeStore()
        store.runtime["stability"] = {
            "lastTorrentActionAt": orch.now_ts() - 120,
            "modeSignature": "expansive",
            "selectionSignature": orch.stable_signature({"start": [], "stop": []}),
            "selectionStableCycles": 1,
        }
        meta = orch.update_stability_guard(
            store,
            "expansive",
            [],
            ["bootstrap-hash"],
            {},
            rotation_urgent=True,
            no_active_downloads=True,
        )
        self.assertTrue(meta["torrentControlReady"])

    def test_broken_download_recovery_does_not_fire_when_gate_off(self) -> None:
        original_allow_arr = orch.CONFIG.allow_arr_commands
        original_allow_recovery = orch.CONFIG.allow_broken_download_recovery
        try:
            object.__setattr__(orch.CONFIG, "allow_arr_commands", False)
            object.__setattr__(orch.CONFIG, "allow_broken_download_recovery", False)
            arr_collector = orch.ArrHistoryCollector()
            torrent = make_torrent(
                "recover3",
                "No Fire Missing",
                state="missingFiles",
                amount_left=0,
                progress=0.0,
                added_on=orch.now_ts() - 10_000,
            )
            grabbed = {"eventType": "grabbed", "date": "2026-03-28T00:00:00Z", "movieId": 777}
            report = orch.build_orphan_report(
                [torrent],
                {"recover3": {"apps": {"radarr": {"latestGrabbed": grabbed, "latestImported": None, "records": [grabbed]}}}},
                arr_collector,
            )
            dispatch = orch.maybe_apply_arr_recovery(FakeStore(), arr_collector, FakeQBClient(), report)
            suspect = report["brokenSuspects"][0]
            self.assertNotIn("retryTriggered", suspect)
            self.assertNotIn("retryError", suspect)
            self.assertEqual(dispatch["triggered"], [])
        finally:
            object.__setattr__(orch.CONFIG, "allow_arr_commands", original_allow_arr)
            object.__setattr__(orch.CONFIG, "allow_broken_download_recovery", original_allow_recovery)

    def test_missing_files_recovery_recommends_arr_search(self) -> None:
        arr_collector = orch.ArrHistoryCollector()
        torrent = make_torrent(
            "recover1",
            "Recoverable Missing",
            state="missingFiles",
            amount_left=0,
            progress=0.0,
            num_seeds=0,
            availability=0.0,
            added_on=orch.now_ts() - 10_000,
        )
        grabbed = {"eventType": "grabbed", "date": "2026-03-28T00:00:00Z", "movieId": 123}
        report = orch.build_orphan_report(
            [torrent],
            {"recover1": {"apps": {"radarr": {"latestGrabbed": grabbed, "latestImported": None, "records": [grabbed]}}}},
            arr_collector,
        )
        self.assertEqual(len(report["brokenSuspects"]), 1)
        actions = report["brokenSuspects"][0]["recommendedActions"]
        self.assertTrue(any(action.get("type") == "qbit-delete" for action in actions))
        self.assertTrue(any(action.get("type") == "arr-search-command" for action in actions))

    def test_missing_files_recovery_uses_queue_mapping_when_history_is_missing(self) -> None:
        arr_collector = orch.ArrHistoryCollector()
        torrent = make_torrent(
            "recover-queue-map",
            "Queue Mapped Missing",
            state="missingFiles",
            category="sonarr",
            amount_left=0,
            progress=0.0,
            num_seeds=0,
            availability=0.0,
            added_on=orch.now_ts() - 10_000,
        )
        report = orch.build_orphan_report(
            [torrent],
            {},
            arr_collector,
            arr_queue={
                "sonarr": [
                    {
                        "id": 101,
                        "episodeId": 9001,
                        "downloadId": "recover-queue-map",
                        "title": "Queue Mapped Missing",
                        "added": "2026-03-27T00:00:00Z",
                        "trackedDownloadStatus": "ok",
                        "trackedDownloadState": "downloading",
                        "status": "warning",
                        "episodeHasFile": False,
                    },
                    {
                        "id": 102,
                        "episodeId": 9002,
                        "downloadId": "recover-queue-map",
                        "title": "Queue Mapped Missing",
                        "added": "2026-03-27T00:00:00Z",
                        "trackedDownloadStatus": "ok",
                        "trackedDownloadState": "downloading",
                        "status": "warning",
                        "episodeHasFile": False,
                    },
                ]
            },
        )
        self.assertEqual(len(report["brokenSuspects"]), 1)
        suspect = report["brokenSuspects"][0]
        self.assertEqual(suspect["entityIds"], [9001, 9002])
        self.assertEqual(suspect["queueCleanupAction"]["queueIds"], [101, 102])
        actions = suspect["recommendedActions"]
        search_actions = [action for action in actions if action.get("type") == "arr-search-command"]
        self.assertEqual(len(search_actions), 1)
        self.assertEqual(search_actions[0]["episodeIds"], [9001, 9002])

    def test_missing_files_salvage_recommends_qbit_recovery_first(self) -> None:
        arr_collector = orch.ArrHistoryCollector()
        torrent = make_torrent(
            "recover-salvage",
            "Salvage Missing",
            state="missingFiles",
            amount_left=4 * 1024**3,
            progress=0.4,
            num_seeds=2,
            availability=2.0,
            added_on=orch.now_ts() - 10_000,
        )
        grabbed = {"eventType": "grabbed", "date": "2026-03-28T00:00:00Z", "movieId": 999}
        report = orch.build_orphan_report(
            [torrent],
            {"recover-salvage": {"apps": {"radarr": {"latestGrabbed": grabbed, "latestImported": None, "records": [grabbed]}}}},
            arr_collector,
        )
        actions = report["brokenSuspects"][0]["recommendedActions"]
        action_types = [action["type"] for action in actions]
        self.assertEqual(report["brokenSuspects"][0]["recoveryMode"], "salvage")
        self.assertIn("qbit-recheck", action_types)
        self.assertIn("qbit-reannounce", action_types)
        self.assertIn("arr-search-command", action_types)

    def test_missing_files_with_negative_completion_uses_recent_activity_as_reference(self) -> None:
        arr_collector = orch.ArrHistoryCollector()
        recent_activity = orch.now_ts() - 10_000
        torrent = make_torrent(
            "recover-negative",
            "Negative Completion Missing",
            state="missingFiles",
            amount_left=8 * 1024**3,
            progress=0.0,
            num_seeds=0,
            availability=0.0,
            added_on=orch.now_ts() - 100_000,
            completion_on=-1,
            last_activity=recent_activity,
            seen_complete=recent_activity,
        )
        grabbed = {"eventType": "grabbed", "date": "2026-03-28T00:00:00Z", "movieId": 321}
        report = orch.build_orphan_report(
            [torrent],
            {"recover-negative": {"apps": {"radarr": {"latestGrabbed": grabbed, "latestImported": None, "records": [grabbed]}}}},
            arr_collector,
        )
        self.assertEqual(len(report["brokenSuspects"]), 1)
        self.assertEqual(report["brokenSuspects"][0]["referenceTs"], recent_activity)

    def test_long_stalled_torrent_enters_broken_recovery_lane(self) -> None:
        arr_collector = orch.ArrHistoryCollector()
        torrent = make_torrent(
            "recover-stalled",
            "Long Stalled",
            state="stalledDL",
            category="lidarr",
            amount_left=350 * 1024**2,
            progress=0.1,
            num_seeds=1,
            availability=1.1,
            added_on=orch.now_ts() - 10_000,
            completion_on=-1,
            last_activity=orch.now_ts() - 10_000,
        )
        grabbed = {"eventType": "grabbed", "date": "2026-03-28T00:00:00Z", "albumId": 9}
        report = orch.build_orphan_report(
            [torrent],
            {"recover-stalled": {"apps": {"lidarr": {"latestGrabbed": grabbed, "latestImported": None, "records": [grabbed]}}}},
            arr_collector,
            {"recover-stalled": {"stalledSeconds": 7200, "probeStalled": True, "longStalled": True}},
        )
        self.assertEqual(len(report["brokenSuspects"]), 1)
        actions = report["brokenSuspects"][0]["recommendedActions"]
        action_types = [action["type"] for action in actions]
        self.assertEqual(report["brokenSuspects"][0]["recoveryMode"], "salvage")
        self.assertIn("qbit-reannounce", action_types)
        self.assertIn("qbit-soft-reset", action_types)
        self.assertIn("arr-search-command", action_types)

    def test_probe_stalled_torrent_enters_broken_recovery_lane_before_long_stall(self) -> None:
        arr_collector = orch.ArrHistoryCollector()
        torrent = make_torrent(
            "recover-probe-stalled",
            "Probe Stalled",
            state="stalledDL",
            category="lidarr",
            amount_left=350 * 1024**2,
            progress=0.1,
            num_seeds=1,
            availability=1.1,
            added_on=orch.now_ts() - 10_000,
            completion_on=-1,
            last_activity=orch.now_ts() - 10_000,
        )
        grabbed = {"eventType": "grabbed", "date": "2026-03-28T00:00:00Z", "albumId": 9}
        report = orch.build_orphan_report(
            [torrent],
            {"recover-probe-stalled": {"apps": {"lidarr": {"latestGrabbed": grabbed, "latestImported": None, "records": [grabbed]}}}},
            arr_collector,
            {"recover-probe-stalled": {"stalledSeconds": 400, "probeStalled": True, "longStalled": False}},
        )
        self.assertEqual(len(report["brokenSuspects"]), 1)
        self.assertEqual(report["brokenSuspects"][0]["brokenReason"], "stalled-no-progress")
        self.assertEqual(report["brokenSuspects"][0]["recoveryMode"], "salvage")

    def test_imported_media_is_not_requeued(self) -> None:
        arr_collector = orch.ArrHistoryCollector()
        torrent = make_torrent(
            "recover2",
            "Already Imported",
            state="missingFiles",
            amount_left=0,
            progress=0.0,
            num_seeds=0,
            availability=0.0,
            added_on=orch.now_ts() - 10_000,
        )
        grabbed = {"eventType": "grabbed", "date": "2026-03-28T00:00:00Z", "movieId": 456}
        imported = {"eventType": "downloadFolderImported", "date": "2026-03-28T02:00:00Z", "movieId": 456}
        report = orch.build_orphan_report(
            [torrent],
            {"recover2": {"apps": {"radarr": {"latestGrabbed": grabbed, "latestImported": imported, "records": [grabbed, imported]}}}},
            arr_collector,
        )
        self.assertEqual(report["brokenSuspects"], [])

    def test_queue_warning_repair_candidate_detected(self) -> None:
        arr_collector = orch.ArrHistoryCollector()
        candidate = orch.build_retroactive_arr_repair_candidates(
            [],
            {},
            {
                "sonarr": [
                    {
                        "episodeId": 55,
                        "title": "Broken Queue Item",
                        "downloadId": "ABC123",
                        "added": "2026-03-27T00:00:00Z",
                        "trackedDownloadStatus": "warning",
                        "trackedDownloadState": "importPending",
                        "statusMessages": [{"messages": ["bad release"]}],
                        "episodeHasFile": False,
                    }
                ]
            },
            arr_collector,
        )
        self.assertEqual(len(candidate), 1)
        self.assertEqual(candidate[0]["reason"], "queue-import-warning")
        self.assertEqual(candidate[0]["recommendedAction"]["command"], "EpisodeSearch")

    def test_queue_warning_repair_groups_multi_episode_download(self) -> None:
        arr_collector = orch.ArrHistoryCollector()
        candidates = orch.build_retroactive_arr_repair_candidates(
            [],
            {},
            {
                "sonarr": [
                    {
                        "episodeId": 101,
                        "title": "Pack Download",
                        "downloadId": "PACK123",
                        "added": "2026-03-27T00:00:00Z",
                        "trackedDownloadStatus": "warning",
                        "trackedDownloadState": "importBlocked",
                        "statusMessages": [{"messages": ["Episode 1 was unexpected"]}],
                        "episodeHasFile": False,
                    },
                    {
                        "episodeId": 102,
                        "title": "Pack Download",
                        "downloadId": "PACK123",
                        "added": "2026-03-27T00:00:00Z",
                        "trackedDownloadStatus": "warning",
                        "trackedDownloadState": "importBlocked",
                        "statusMessages": [{"messages": ["Episode 2 was unexpected"]}],
                        "episodeHasFile": False,
                    },
                ]
            },
            arr_collector,
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["reason"], "queue-import-warning")
        self.assertEqual(candidates[0]["recommendedAction"]["episodeIds"], [101, 102])

    def test_queue_download_missing_candidate_detected_when_hash_absent(self) -> None:
        arr_collector = orch.ArrHistoryCollector()
        candidates = orch.build_retroactive_arr_repair_candidates(
            [],
            {},
            {
                "radarr": [
                    {
                        "movieId": 900,
                        "title": "Missing Download",
                        "downloadId": "MISSINGHASH",
                        "added": "2026-03-27T00:00:00Z",
                        "status": "paused",
                        "trackedDownloadStatus": "ok",
                        "trackedDownloadState": "downloading",
                        "statusMessages": [],
                        "movieHasFile": False,
                    }
                ]
            },
            arr_collector,
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["reason"], "queue-download-missing")
        self.assertEqual(candidates[0]["recommendedAction"]["command"], "MoviesSearch")

    def test_retroactive_history_repair_candidate_detected(self) -> None:
        arr_collector = orch.ArrHistoryCollector()
        grabbed = {
            "eventType": "grabbed",
            "date": "2026-03-27T00:00:00Z",
            "movieId": 123,
            "downloadId": "OLDHASH",
            "sourceTitle": "Old Movie Grab",
        }
        candidates = orch.build_backlog_candidates(
            [],
            {"oldhash": {"apps": {"radarr": {"latestGrabbed": grabbed, "latestImported": None, "records": [grabbed]}}}},
            {"radarr": []},
            {},
            arr_collector,
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["reason"], "history-grabbed-no-import")
        self.assertEqual(candidates[0]["recommendedAction"]["command"], "MoviesSearch")

    def test_retroactive_history_repair_groups_shared_download_into_single_search(self) -> None:
        arr_collector = orch.ArrHistoryCollector()
        grabbed_a = {
            "eventType": "grabbed",
            "date": "2026-03-27T00:00:00Z",
            "episodeId": 701,
            "downloadId": "PACKXYZ",
            "sourceTitle": "Shared Season Pack",
        }
        grabbed_b = {
            "eventType": "grabbed",
            "date": "2026-03-27T00:00:01Z",
            "episodeId": 702,
            "downloadId": "PACKXYZ",
            "sourceTitle": "Shared Season Pack",
        }
        candidates = orch.build_backlog_candidates(
            [],
            {
                "pack-a": {"apps": {"sonarr": {"latestGrabbed": grabbed_a, "latestImported": None, "records": [grabbed_a]}}},
                "pack-b": {"apps": {"sonarr": {"latestGrabbed": grabbed_b, "latestImported": None, "records": [grabbed_b]}}},
            },
            {"sonarr": []},
            {},
            arr_collector,
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["entityIds"], [701, 702])
        self.assertEqual(candidates[0]["recommendedAction"]["episodeIds"], [701, 702])

    def test_failed_history_repair_candidate_detected(self) -> None:
        arr_collector = orch.ArrHistoryCollector()
        failed = {
            "eventType": "downloadFailed",
            "date": "2026-03-27T02:00:00Z",
            "movieId": 555,
            "downloadId": "FAILEDHASH",
            "sourceTitle": "Failed Movie Grab",
        }
        grabbed = {
            "eventType": "grabbed",
            "date": "2026-03-27T00:00:00Z",
            "movieId": 555,
            "downloadId": "FAILEDHASH",
            "sourceTitle": "Failed Movie Grab",
        }
        candidates = orch.build_backlog_candidates(
            [],
            {"failedhash": {"apps": {"radarr": {"latestGrabbed": grabbed, "latestFailed": failed, "latestImported": None, "records": [grabbed, failed]}}}},
            {"radarr": []},
            {},
            arr_collector,
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["reason"], "history-failed-no-import")
        self.assertEqual(candidates[0]["recommendedAction"]["command"], "MoviesSearch")

    def test_radarr_wanted_stale_backlog_candidate_detected(self) -> None:
        arr_collector = orch.ArrHistoryCollector()
        candidates = orch.build_backlog_candidates(
            [],
            {},
            {"radarr": []},
            {
                "radarr": [
                    {
                        "id": 88,
                        "title": "Stale Wanted Movie",
                        "monitored": True,
                        "hasFile": False,
                        "isAvailable": True,
                        "added": "2026-03-20T00:00:00Z",
                        "lastSearchTime": "2026-03-20T00:00:00Z",
                    }
                ]
            },
            arr_collector,
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["reason"], "wanted-missing-stale")
        self.assertEqual(candidates[0]["recommendedAction"]["command"], "MoviesSearch")

    def test_sonarr_wanted_stale_backlog_candidate_detected(self) -> None:
        arr_collector = orch.ArrHistoryCollector()
        candidates = orch.build_backlog_candidates(
            [],
            {},
            {"sonarr": []},
            {
                "sonarr": [
                    {
                        "id": 3830,
                        "title": "#466",
                        "monitored": True,
                        "hasFile": False,
                        "airDateUtc": "2026-03-20T01:00:00Z",
                        "lastSearchTime": "2026-03-20T02:00:00Z",
                    }
                ]
            },
            arr_collector,
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["reason"], "wanted-missing-stale")
        self.assertEqual(candidates[0]["recommendedAction"]["command"], "EpisodeSearch")

    def test_lidarr_wanted_stale_backlog_candidate_detected(self) -> None:
        arr_collector = orch.ArrHistoryCollector()
        candidates = orch.build_backlog_candidates(
            [],
            {},
            {"lidarr": []},
            {
                "lidarr": [
                    {
                        "id": 6,
                        "title": "Goodbye & Good Riddance",
                        "monitored": True,
                        "releaseDate": "2026-03-20T00:00:00Z",
                        "lastSearchTime": "2026-03-20T00:00:00Z",
                        "statistics": {"trackFileCount": 0, "trackCount": 20},
                    }
                ]
            },
            arr_collector,
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["reason"], "wanted-missing-stale")
        self.assertEqual(candidates[0]["recommendedAction"]["command"], "AlbumSearch")

    def test_arr_recovery_budget_and_cooldown(self) -> None:
        original_observe = orch.CONFIG.observe_only
        original_allow_arr = orch.CONFIG.allow_arr_commands
        original_allow_recovery = orch.CONFIG.allow_broken_download_recovery
        original_allow_retro = orch.CONFIG.allow_retroactive_arr_repair
        original_allow_backlog = orch.CONFIG.allow_backlog_arr_repair
        original_budget = orch.CONFIG.max_arr_commands_per_cycle
        original_cooldown = orch.CONFIG.min_arr_command_interval_seconds
        original_global_cooldown = orch.CONFIG.arr_global_command_interval_seconds
        try:
            object.__setattr__(orch.CONFIG, "observe_only", False)
            object.__setattr__(orch.CONFIG, "allow_arr_commands", True)
            object.__setattr__(orch.CONFIG, "allow_broken_download_recovery", True)
            object.__setattr__(orch.CONFIG, "allow_retroactive_arr_repair", True)
            object.__setattr__(orch.CONFIG, "allow_backlog_arr_repair", True)
            object.__setattr__(orch.CONFIG, "max_arr_commands_per_cycle", 1)
            object.__setattr__(orch.CONFIG, "min_arr_command_interval_seconds", 3600)
            object.__setattr__(orch.CONFIG, "arr_global_command_interval_seconds", 1800)

            arr_collector = orch.ArrHistoryCollector()
            seen_actions: list[dict] = []

            def fake_run_search_action(app_name: str, action: dict[str, object]) -> dict[str, object]:
                seen_actions.append({"app": app_name, "action": action})
                return {"name": action["command"], "id": 1}

            arr_collector.run_search_action = fake_run_search_action  # type: ignore[method-assign]

            report = {
                "brokenSuspects": [],
                "suspects": [
                    {
                        "app": "radarr",
                        "title": "First",
                        "completionOn": orch.now_ts() - 7200,
                        "recommendedAction": orch.build_arr_search_action_for_entity("radarr", 101, arr_collector),
                    }
                ],
                "retroRepairCandidates": [
                    {
                        "app": "radarr",
                        "title": "Second",
                        "lane": "retro-queue-warning",
                        "reason": "wanted-missing-stale",
                        "priority": 30,
                        "maxRetries": 1,
                        "referenceTs": orch.now_ts() - 8000,
                        "recommendedAction": orch.build_arr_search_action_for_entity("radarr", 202, arr_collector),
                    }
                ],
                "backlogCandidates": [
                    {
                        "app": "radarr",
                        "title": "Third",
                        "lane": "backlog-history",
                        "reason": "history-grabbed-no-import",
                        "priority": 40,
                        "maxRetries": 1,
                        "referenceTs": orch.now_ts() - 9000,
                        "recommendedAction": orch.build_arr_search_action_for_entity("radarr", 303, arr_collector),
                    }
                ],
            }
            store = FakeStore()
            dispatch = orch.maybe_apply_arr_recovery(store, arr_collector, FakeQBClient(), report)
            self.assertEqual(len(dispatch["triggered"]), 2)
            self.assertEqual(len(seen_actions), 2)
            self.assertIn("arr_last_command_at", store.runtime)

            dispatch = orch.maybe_apply_arr_recovery(store, arr_collector, FakeQBClient(), report)
            self.assertTrue(any(item["reason"] == "global-cooldown" for item in dispatch["skipped"]))

            store.runtime["arr_last_command_at"] = orch.now_ts() - 4000
            report["retroRepairCandidates"] = []
            dispatch = orch.maybe_apply_arr_recovery(store, arr_collector, FakeQBClient(), report)
            self.assertTrue(any(item["reason"] == "retry-limit" for item in dispatch["skipped"]))
        finally:
            object.__setattr__(orch.CONFIG, "observe_only", original_observe)
            object.__setattr__(orch.CONFIG, "allow_arr_commands", original_allow_arr)
            object.__setattr__(orch.CONFIG, "allow_broken_download_recovery", original_allow_recovery)
            object.__setattr__(orch.CONFIG, "allow_retroactive_arr_repair", original_allow_retro)
            object.__setattr__(orch.CONFIG, "allow_backlog_arr_repair", original_allow_backlog)
            object.__setattr__(orch.CONFIG, "max_arr_commands_per_cycle", original_budget)
            object.__setattr__(orch.CONFIG, "min_arr_command_interval_seconds", original_cooldown)
            object.__setattr__(orch.CONFIG, "arr_global_command_interval_seconds", original_global_cooldown)

    def test_arr_recovery_rearms_backlog_action_after_retry_reset_window(self) -> None:
        original_observe = orch.CONFIG.observe_only
        original_allow_arr = orch.CONFIG.allow_arr_commands
        original_allow_backlog = orch.CONFIG.allow_backlog_arr_repair
        original_global = orch.CONFIG.arr_global_command_interval_seconds
        original_backlog_interval = orch.CONFIG.backlog_arr_command_interval_seconds
        original_backlog_reset = orch.CONFIG.backlog_arr_retry_reset_seconds
        try:
            object.__setattr__(orch.CONFIG, "observe_only", False)
            object.__setattr__(orch.CONFIG, "allow_arr_commands", True)
            object.__setattr__(orch.CONFIG, "allow_backlog_arr_repair", True)
            object.__setattr__(orch.CONFIG, "arr_global_command_interval_seconds", 0)
            object.__setattr__(orch.CONFIG, "backlog_arr_command_interval_seconds", 60)
            object.__setattr__(orch.CONFIG, "backlog_arr_retry_reset_seconds", 300)

            arr_collector = orch.ArrHistoryCollector()
            searches: list[dict[str, object]] = []
            arr_collector.run_search_action = lambda app_name, action: searches.append({"app": app_name, "action": action}) or {"id": 12, "name": action["command"]}  # type: ignore[method-assign]

            action = orch.build_arr_search_action_for_entity("radarr", 999, arr_collector)
            report = {
                "brokenSuspects": [],
                "suspects": [],
                "retroRepairCandidates": [],
                "backlogCandidates": [
                    {
                        "app": "radarr",
                        "title": "Old Missing Movie",
                        "lane": "backlog-history",
                        "reason": "history-grabbed-no-import",
                        "priority": 25,
                        "maxRetries": 1,
                        "referenceTs": orch.now_ts() - 9000,
                        "recommendedAction": action,
                    }
                ],
            }
            store = FakeStore()
            action_key = action["actionKey"]
            store.runtime["arr_command_history"] = {
                action_key: {"lastTriggeredAt": orch.now_ts() - 600, "triggerCount": 1}
            }

            dispatch = orch.maybe_apply_arr_recovery(store, arr_collector, FakeQBClient(), report, int(60 * 1024**3))
            self.assertEqual(len(dispatch["triggered"]), 1)
            self.assertEqual(len(searches), 1)
        finally:
            object.__setattr__(orch.CONFIG, "observe_only", original_observe)
            object.__setattr__(orch.CONFIG, "allow_arr_commands", original_allow_arr)
            object.__setattr__(orch.CONFIG, "allow_backlog_arr_repair", original_allow_backlog)
            object.__setattr__(orch.CONFIG, "arr_global_command_interval_seconds", original_global)
            object.__setattr__(orch.CONFIG, "backlog_arr_command_interval_seconds", original_backlog_interval)
            object.__setattr__(orch.CONFIG, "backlog_arr_retry_reset_seconds", original_backlog_reset)

    def test_arr_recovery_uses_repair_burst_budget_for_multiple_broken_items(self) -> None:
        original_observe = orch.CONFIG.observe_only
        original_allow_arr = orch.CONFIG.allow_arr_commands
        original_allow_recovery = orch.CONFIG.allow_broken_download_recovery
        original_budget = orch.CONFIG.max_arr_commands_per_cycle
        original_burst = orch.CONFIG.arr_command_budget_repair_burst
        original_global = orch.CONFIG.arr_global_command_interval_seconds
        original_urgent_global = orch.CONFIG.urgent_arr_global_command_interval_seconds
        try:
            object.__setattr__(orch.CONFIG, "observe_only", False)
            object.__setattr__(orch.CONFIG, "allow_arr_commands", True)
            object.__setattr__(orch.CONFIG, "allow_broken_download_recovery", True)
            object.__setattr__(orch.CONFIG, "max_arr_commands_per_cycle", 1)
            object.__setattr__(orch.CONFIG, "arr_command_budget_repair_burst", 3)
            object.__setattr__(orch.CONFIG, "arr_global_command_interval_seconds", 0)
            object.__setattr__(orch.CONFIG, "urgent_arr_global_command_interval_seconds", 0)

            arr_collector = orch.ArrHistoryCollector()
            searches: list[dict[str, object]] = []
            arr_collector.run_search_action = lambda app_name, action: searches.append({"app": app_name, "action": action}) or {"id": 7, "name": action["command"]}  # type: ignore[method-assign]

            report = {
                "brokenSuspects": [
                    {
                        "hash": "broken-a",
                        "name": "Broken A",
                        "app": "radarr",
                        "lane": "broken-recovery",
                        "priority": 5,
                        "referenceTs": orch.now_ts() - 9500,
                        "recoveryMode": "replace",
                        "recommendedActions": [orch.build_arr_search_action_for_entity("radarr", 401, arr_collector)],
                    },
                    {
                        "hash": "broken-b",
                        "name": "Broken B",
                        "app": "sonarr",
                        "lane": "broken-recovery",
                        "priority": 5,
                        "referenceTs": orch.now_ts() - 9400,
                        "recoveryMode": "replace",
                        "recommendedActions": [orch.build_arr_search_action_for_entity("sonarr", 402, arr_collector)],
                    },
                    {
                        "hash": "broken-c",
                        "name": "Broken C",
                        "app": "lidarr",
                        "lane": "broken-recovery",
                        "priority": 5,
                        "referenceTs": orch.now_ts() - 9300,
                        "recoveryMode": "replace",
                        "recommendedActions": [orch.build_arr_search_action_for_entity("lidarr", 403, arr_collector)],
                    },
                ],
                "suspects": [],
                "retroRepairCandidates": [],
                "backlogCandidates": [],
            }

            dispatch = orch.maybe_apply_arr_recovery(FakeStore(), arr_collector, FakeQBClient(), report, int(80 * 1024**3))
            self.assertEqual(len(dispatch["triggered"]), 3)
            self.assertEqual(len(searches), 3)
            self.assertEqual(dispatch["policy"]["actionBudget"], 3)
        finally:
            object.__setattr__(orch.CONFIG, "observe_only", original_observe)
            object.__setattr__(orch.CONFIG, "allow_arr_commands", original_allow_arr)
            object.__setattr__(orch.CONFIG, "allow_broken_download_recovery", original_allow_recovery)
            object.__setattr__(orch.CONFIG, "max_arr_commands_per_cycle", original_budget)
            object.__setattr__(orch.CONFIG, "arr_command_budget_repair_burst", original_burst)
            object.__setattr__(orch.CONFIG, "arr_global_command_interval_seconds", original_global)
            object.__setattr__(orch.CONFIG, "urgent_arr_global_command_interval_seconds", original_urgent_global)

    def test_qbit_salvage_recovery_budget_and_cooldown(self) -> None:
        original_observe = orch.CONFIG.observe_only
        original_recovery = orch.CONFIG.allow_broken_download_recovery
        original_qbit_recovery = orch.CONFIG.allow_qbit_recovery_actions
        original_budget = orch.CONFIG.max_qbit_recovery_actions_per_cycle
        original_cooldown = orch.CONFIG.min_qbit_recovery_interval_seconds
        original_retries = orch.CONFIG.max_qbit_recovery_attempts_per_hash
        try:
            object.__setattr__(orch.CONFIG, "observe_only", False)
            object.__setattr__(orch.CONFIG, "allow_broken_download_recovery", True)
            object.__setattr__(orch.CONFIG, "allow_qbit_recovery_actions", True)
            object.__setattr__(orch.CONFIG, "max_qbit_recovery_actions_per_cycle", 1)
            object.__setattr__(orch.CONFIG, "min_qbit_recovery_interval_seconds", 3600)
            object.__setattr__(orch.CONFIG, "max_qbit_recovery_attempts_per_hash", 1)

            store = FakeStore()
            client = FakeQBClient()
            report = {
                "brokenSuspects": [
                    {
                        "hash": "recover-a",
                        "name": "Recover A",
                        "referenceTs": orch.now_ts() - 7200,
                        "recoveryMode": "salvage",
                        "recommendedActions": [{"type": "qbit-recheck"}, {"type": "qbit-reannounce"}],
                    },
                    {
                        "hash": "recover-b",
                        "name": "Recover B",
                        "referenceTs": orch.now_ts() - 7100,
                        "recoveryMode": "salvage",
                        "recommendedActions": [{"type": "qbit-recheck"}, {"type": "qbit-reannounce"}],
                    },
                ]
            }

            dispatch = orch.maybe_apply_qbit_recovery(store, client, report)
            self.assertEqual(len(dispatch["triggered"]), 1)
            self.assertEqual(client.rechecked, [["recover-a"]])
            self.assertEqual(client.reannounced, [["recover-a"]])

            dispatch = orch.maybe_apply_qbit_recovery(store, client, report)
            self.assertTrue(any(item["reason"] == "retry-limit" for item in dispatch["skipped"]))
        finally:
            object.__setattr__(orch.CONFIG, "observe_only", original_observe)
            object.__setattr__(orch.CONFIG, "allow_broken_download_recovery", original_recovery)
            object.__setattr__(orch.CONFIG, "allow_qbit_recovery_actions", original_qbit_recovery)
            object.__setattr__(orch.CONFIG, "max_qbit_recovery_actions_per_cycle", original_budget)
            object.__setattr__(orch.CONFIG, "min_qbit_recovery_interval_seconds", original_cooldown)
            object.__setattr__(orch.CONFIG, "max_qbit_recovery_attempts_per_hash", original_retries)

    def test_qbit_stalled_salvage_soft_resets(self) -> None:
        original_observe = orch.CONFIG.observe_only
        original_recovery = orch.CONFIG.allow_broken_download_recovery
        original_qbit_recovery = orch.CONFIG.allow_qbit_recovery_actions
        try:
            object.__setattr__(orch.CONFIG, "observe_only", False)
            object.__setattr__(orch.CONFIG, "allow_broken_download_recovery", True)
            object.__setattr__(orch.CONFIG, "allow_qbit_recovery_actions", True)
            store = FakeStore()
            client = FakeQBClient()
            report = {
                "brokenSuspects": [
                    {
                        "hash": "recover-stalled",
                        "name": "Recover Stalled",
                        "referenceTs": orch.now_ts() - 7200,
                        "recoveryMode": "salvage",
                        "recommendedActions": [{"type": "qbit-reannounce"}, {"type": "qbit-soft-reset"}],
                    }
                ]
            }
            dispatch = orch.maybe_apply_qbit_recovery(store, client, report)
            self.assertEqual(len(dispatch["triggered"]), 1)
            self.assertEqual(client.reannounced, [["recover-stalled"]])
            self.assertEqual(client.stopped, [["recover-stalled"]])
            self.assertEqual(client.started, [["recover-stalled"]])
        finally:
            object.__setattr__(orch.CONFIG, "observe_only", original_observe)
            object.__setattr__(orch.CONFIG, "allow_broken_download_recovery", original_recovery)
            object.__setattr__(orch.CONFIG, "allow_qbit_recovery_actions", original_qbit_recovery)

    def test_arr_recovery_deletes_broken_torrent_before_requeue(self) -> None:
        original_observe = orch.CONFIG.observe_only
        original_allow_arr = orch.CONFIG.allow_arr_commands
        original_allow_recovery = orch.CONFIG.allow_broken_download_recovery
        try:
            object.__setattr__(orch.CONFIG, "observe_only", False)
            object.__setattr__(orch.CONFIG, "allow_arr_commands", True)
            object.__setattr__(orch.CONFIG, "allow_broken_download_recovery", True)
            arr_collector = orch.ArrHistoryCollector()
            arr_collector.run_search_action = lambda app, action: {"id": 7, "name": action["command"]}  # type: ignore[method-assign]
            store = FakeStore()
            client = FakeQBClient()
            report = {
                "brokenSuspects": [
                    {
                        "hash": "recover-delete",
                        "name": "Recover Delete",
                        "app": "radarr",
                        "lane": "broken-recovery",
                        "priority": 5,
                        "referenceTs": orch.now_ts() - 7200,
                        "recoveryMode": "replace",
                        "recommendedActions": [
                            {"type": "qbit-delete", "deleteFiles": False},
                            orch.build_arr_search_action_for_entity("radarr", 404, arr_collector),
                        ],
                    }
                ],
                "suspects": [],
                "retroRepairCandidates": [],
                "backlogCandidates": [],
            }
            dispatch = orch.maybe_apply_arr_recovery(store, arr_collector, client, report)
            self.assertEqual(len(dispatch["triggered"]), 1)
            self.assertEqual(client.deleted, [{"hashes": ["recover-delete"], "deleteFiles": False}])
        finally:
            object.__setattr__(orch.CONFIG, "observe_only", original_observe)
            object.__setattr__(orch.CONFIG, "allow_arr_commands", original_allow_arr)
            object.__setattr__(orch.CONFIG, "allow_broken_download_recovery", original_allow_recovery)

    def test_arr_recovery_clears_queue_warning_before_requeue(self) -> None:
        original_observe = orch.CONFIG.observe_only
        original_allow_arr = orch.CONFIG.allow_arr_commands
        original_allow_retro = orch.CONFIG.allow_retroactive_arr_repair
        original_global_cooldown = orch.CONFIG.arr_global_command_interval_seconds
        try:
            object.__setattr__(orch.CONFIG, "observe_only", False)
            object.__setattr__(orch.CONFIG, "allow_arr_commands", True)
            object.__setattr__(orch.CONFIG, "allow_retroactive_arr_repair", True)
            object.__setattr__(orch.CONFIG, "arr_global_command_interval_seconds", 0)
            arr_collector = orch.ArrHistoryCollector()
            queue_clears: list[dict] = []
            searches: list[dict] = []

            def fake_clear_queue_items(app_name: str, queue_ids: list[int], *, remove_from_client: bool = False, blocklist: bool = True) -> list[dict[str, object]]:
                queue_clears.append(
                    {
                        "app": app_name,
                        "queueIds": list(queue_ids),
                        "removeFromClient": remove_from_client,
                        "blocklist": blocklist,
                    }
                )
                return [{"queueId": queue_ids[0], "status": 200}] if queue_ids else []

            def fake_run_search_action(app_name: str, action: dict[str, object]) -> dict[str, object]:
                searches.append({"app": app_name, "action": action})
                return {"id": 9, "name": action["command"]}

            arr_collector.clear_queue_items = fake_clear_queue_items  # type: ignore[method-assign]
            arr_collector.run_search_action = fake_run_search_action  # type: ignore[method-assign]
            report = {
                "brokenSuspects": [],
                "suspects": [],
                "retroRepairCandidates": [
                    {
                        "app": "sonarr",
                        "title": "Import Blocked Pack",
                        "lane": "retro-queue-warning",
                        "reason": "queue-import-warning",
                        "priority": 8,
                        "maxRetries": 1,
                        "referenceTs": orch.now_ts() - 9000,
                        "queueCleanupAction": {
                            "type": "arr-queue-delete",
                            "queueIds": [1234],
                            "removeFromClient": False,
                            "blocklist": True,
                        },
                        "recommendedAction": orch.build_arr_search_action_for_entities("sonarr", [1001, 1002], arr_collector),
                    }
                ],
                "backlogCandidates": [],
            }
            dispatch = orch.maybe_apply_arr_recovery(FakeStore(), arr_collector, FakeQBClient(), report)
            self.assertEqual(len(dispatch["triggered"]), 1)
            self.assertEqual(queue_clears[0]["queueIds"], [1234])
            self.assertEqual(searches[0]["action"]["episodeIds"], [1001, 1002])
        finally:
            object.__setattr__(orch.CONFIG, "observe_only", original_observe)
            object.__setattr__(orch.CONFIG, "allow_arr_commands", original_allow_arr)
            object.__setattr__(orch.CONFIG, "allow_retroactive_arr_repair", original_allow_retro)
            object.__setattr__(orch.CONFIG, "arr_global_command_interval_seconds", original_global_cooldown)

    def test_arr_pagination_completion_uses_total_records_when_total_pages_missing(self) -> None:
        payload = {"page": 1, "pageSize": 200, "totalRecords": 796, "records": [{"id": 1}] * 200}
        self.assertFalse(orch.ArrHistoryCollector._page_complete(payload, 1, payload["records"], 200))
        self.assertFalse(orch.ArrHistoryCollector._page_complete(payload, 3, payload["records"], 200))
        final_payload = {"page": 4, "pageSize": 200, "totalRecords": 796, "records": [{"id": 1}] * 196}
        self.assertTrue(orch.ArrHistoryCollector._page_complete(final_payload, 4, final_payload["records"], 200))

    def test_arr_recovery_can_clear_queue_during_global_search_cooldown(self) -> None:
        original_observe = orch.CONFIG.observe_only
        original_allow_arr = orch.CONFIG.allow_arr_commands
        original_allow_retro = orch.CONFIG.allow_retroactive_arr_repair
        original_global_cooldown = orch.CONFIG.arr_global_command_interval_seconds
        try:
            object.__setattr__(orch.CONFIG, "observe_only", False)
            object.__setattr__(orch.CONFIG, "allow_arr_commands", True)
            object.__setattr__(orch.CONFIG, "allow_retroactive_arr_repair", True)
            object.__setattr__(orch.CONFIG, "arr_global_command_interval_seconds", 3600)
            arr_collector = orch.ArrHistoryCollector()
            queue_clears: list[dict] = []
            searches: list[dict] = []

            arr_collector.clear_queue_items = lambda app_name, queue_ids, **kwargs: queue_clears.append({"app": app_name, "queueIds": list(queue_ids)}) or [{"queueId": queue_ids[0], "status": 200}]  # type: ignore[method-assign]
            arr_collector.run_search_action = lambda app_name, action: searches.append({"app": app_name, "action": action}) or {"id": 9, "name": action["command"]}  # type: ignore[method-assign]

            report = {
                "brokenSuspects": [],
                "suspects": [],
                "retroRepairCandidates": [
                    {
                        "app": "sonarr",
                        "title": "Import Blocked Pack",
                        "lane": "retro-queue-warning",
                        "reason": "queue-import-warning",
                        "priority": 8,
                        "maxRetries": 1,
                        "referenceTs": orch.now_ts() - 9000,
                        "queueCleanupAction": {
                            "type": "arr-queue-delete",
                            "queueIds": [4321],
                            "removeFromClient": False,
                            "blocklist": True,
                        },
                        "recommendedAction": orch.build_arr_search_action_for_entities("sonarr", [1001, 1002], arr_collector),
                    }
                ],
                "backlogCandidates": [],
            }
            store = FakeStore()
            store.runtime["arr_last_command_at"] = orch.now_ts()
            dispatch = orch.maybe_apply_arr_recovery(store, arr_collector, FakeQBClient(), report)
            self.assertEqual(len(queue_clears), 1)
            self.assertEqual(len(searches), 0)
            self.assertTrue(any(item["reason"] == "global-cooldown" for item in dispatch["skipped"]))
            self.assertTrue(any("queue-cleanup" in item["reason"] for item in dispatch["triggered"]))
        finally:
            object.__setattr__(orch.CONFIG, "observe_only", original_observe)
            object.__setattr__(orch.CONFIG, "allow_arr_commands", original_allow_arr)
            object.__setattr__(orch.CONFIG, "allow_retroactive_arr_repair", original_allow_retro)
            object.__setattr__(orch.CONFIG, "arr_global_command_interval_seconds", original_global_cooldown)


if __name__ == "__main__":
    unittest.main(verbosity=2)
