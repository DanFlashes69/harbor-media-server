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
    }


class FakeStore:
    def __init__(self) -> None:
        self.runtime = {}


class FakeQBClient:
    def __init__(self) -> None:
        self.rechecked: list[list[str]] = []
        self.reannounced: list[list[str]] = []

    def recheck(self, hashes: list[str]) -> None:
        self.rechecked.append(list(hashes))

    def reannounce(self, hashes: list[str]) -> None:
        self.reannounced.append(list(hashes))


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
                        self.assertGreaterEqual(desired, 0)
                        self.assertLessEqual(desired, healthy_count)
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

    def test_choose_allowed_never_exceeds_budget_after_first_pick(self) -> None:
        candidates = [
            make_torrent("a", "A", progress=0.95, amount_left=2 * 1024**3, num_seeds=2, availability=2.0),
            make_torrent("b", "B", progress=0.85, amount_left=6 * 1024**3, num_seeds=2, availability=2.0),
            make_torrent("c", "C", progress=0.75, amount_left=9 * 1024**3, num_seeds=2, availability=2.0),
            make_torrent("d", "D", progress=0.25, amount_left=20 * 1024**3, num_seeds=2, availability=2.0),
        ]
        stall = {torrent["hash"]: {"stalledSeconds": 0, "longStalled": False} for torrent in candidates}
        allowed = orch.choose_allowed(candidates, "constrained", int(30 * 1024**3), stall, 3)
        total_remaining = sum(t["amount_left"] for t in allowed[1:])
        self.assertLessEqual(total_remaining, int((30 - orch.CONFIG.reserved_free_gb) * 1024**3))

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
        allowed = orch.choose_allowed(candidates, "constrained", int(25 * 1024**3), stall, 1)
        self.assertEqual([torrent["hash"] for torrent in allowed], ["seeded"])

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
            dispatch = orch.maybe_apply_arr_recovery(FakeStore(), arr_collector, report)
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
        self.assertTrue(any(action.get("type") == "arr-search-command" for action in actions))

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
        self.assertEqual(candidate[0]["reason"], "queue-warning")
        self.assertEqual(candidate[0]["recommendedAction"]["command"], "EpisodeSearch")

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
                        "added": "2026-03-10T00:00:00Z",
                        "lastSearchTime": "2026-03-20T00:00:00Z",
                    }
                ]
            },
            arr_collector,
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["reason"], "wanted-missing-stale")
        self.assertEqual(candidates[0]["recommendedAction"]["command"], "MoviesSearch")

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
            dispatch = orch.maybe_apply_arr_recovery(store, arr_collector, report)
            self.assertEqual(len(dispatch["triggered"]), 1)
            self.assertEqual(len(seen_actions), 1)
            self.assertIn("arr_last_command_at", store.runtime)

            dispatch = orch.maybe_apply_arr_recovery(store, arr_collector, report)
            self.assertTrue(any(item["reason"] == "global-cooldown" for item in dispatch["skipped"]))

            store.runtime["arr_last_command_at"] = orch.now_ts() - 4000
            report["retroRepairCandidates"] = []
            dispatch = orch.maybe_apply_arr_recovery(store, arr_collector, report)
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
                    },
                    {
                        "hash": "recover-b",
                        "name": "Recover B",
                        "referenceTs": orch.now_ts() - 7100,
                        "recoveryMode": "salvage",
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
