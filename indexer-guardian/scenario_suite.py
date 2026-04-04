import copy
import tempfile
import unittest
from pathlib import Path

import guardian as g


class GuardianScenarioTests(unittest.TestCase):
    def test_parse_warning_indexers_supports_short_and_long_term_sources(self) -> None:
        long_term = g.parse_warning_indexers(
            [
                {
                    "source": "IndexerLongTermStatusCheck",
                    "message": "Indexers unavailable due to failures for more than 6 hours: LimeTorrents (Prowlarr), The Pirate Bay (Prowlarr)",
                }
            ]
        )
        short_term = g.parse_warning_indexers(
            [
                {
                    "source": "IndexerStatusCheck",
                    "message": "Indexers unavailable due to failures: 1337x (Prowlarr)",
                }
            ]
        )

        self.assertEqual(long_term, {"LimeTorrents", "The Pirate Bay"})
        self.assertEqual(short_term, {"1337x"})

    def test_replacement_due_requires_real_failure_when_warning_is_stale(self) -> None:
        store = g.StateStore()
        store.runtime = {"failureState": {}}
        due, meta = g.replacement_due(store, "general_secondary", "LimeTorrents", True, {"LimeTorrents"}, 0, 0)
        self.assertFalse(due)
        self.assertEqual(meta["failureCount"], 0)
        self.assertTrue(meta["warningPresent"])

    def test_replacement_due_trips_on_repeated_failures(self) -> None:
        store = g.StateStore()
        store.runtime = {"failureState": {}}
        for _ in range(g.CONFIG.replacement_failure_threshold - 1):
            due, _ = g.replacement_due(store, "general_secondary", "LimeTorrents", False, set(), 0, 0)
            self.assertFalse(due)
        due, meta = g.replacement_due(store, "general_secondary", "LimeTorrents", False, set(), 0, 0)
        self.assertTrue(due)
        self.assertEqual(meta["failureCount"], g.CONFIG.replacement_failure_threshold)

    def test_replacement_due_trips_on_repeated_log_failures(self) -> None:
        store = g.StateStore()
        store.runtime = {"failureState": {}}
        due, meta = g.replacement_due(
            store,
            "general_secondary",
            "TorrentDownload",
            True,
            set(),
            g.CONFIG.log_failure_threshold,
            0,
        )
        self.assertTrue(due)
        self.assertEqual(meta["logFailureCount"], g.CONFIG.log_failure_threshold)

    def test_replacement_due_trips_on_persistent_soft_failures_when_warning_present(self) -> None:
        store = g.StateStore()
        store.runtime = {"failureState": {}}
        due, meta = g.replacement_due(
            store,
            "general_primary",
            "1337x",
            True,
            {"1337x"},
            0,
            g.CONFIG.soft_log_failure_threshold,
        )
        self.assertTrue(due)
        self.assertTrue(meta["persistentSoftFailure"])
        self.assertEqual(meta["softLogFailureCount"], g.CONFIG.soft_log_failure_threshold)

    def test_choose_candidate_definition_skips_active_and_blacklisted(self) -> None:
        store = g.StateStore()
        store.runtime = {
            "replacementHistory": [
                {
                    "slot": "general_secondary",
                    "definitionName": "torrentdownloads",
                    "reason": "candidate-failed-validation",
                    "ts": g.now_ts(),
                }
            ]
        }
        candidate = g.choose_candidate_definition(
            "general_secondary",
            {"limetorrents", "bitsearch"},
            store,
        )
        self.assertEqual(candidate, "torrentproject2")

    def test_build_replacement_payload_preserves_slot_shape(self) -> None:
        template = {
            "definitionName": "bitsearch",
            "indexerUrls": ["https://bitsearch.to/"],
            "enable": False,
            "priority": 0,
            "appProfileId": 0,
            "tags": [],
            "fields": [
                {"name": "baseUrl", "value": None},
                {"name": "torrentBaseSettings.appMinimumSeeders", "value": 0},
                {"name": "baseSettings.queryLimit", "value": 0},
                {"name": "sort", "value": 2},
            ],
        }
        current = {
            "priority": 35,
            "appProfileId": 1,
            "tags": [2],
            "downloadClientId": 1,
            "fields": [
                {"name": "torrentBaseSettings.appMinimumSeeders", "value": 5},
                {"name": "baseSettings.queryLimit", "value": 20},
                {"name": "sort", "value": 0},
            ],
        }
        payload = g.build_replacement_payload("general_tertiary", current, template, 9)
        self.assertTrue(payload["enable"])
        self.assertEqual(payload["priority"], 35)
        self.assertEqual(payload["appProfileId"], 1)
        self.assertEqual(payload["downloadClientId"], 1)
        self.assertEqual(payload["tags"], [2, 9])
        fields = {field["name"]: field["value"] for field in payload["fields"]}
        self.assertEqual(fields["baseUrl"], "https://bitsearch.to/")
        self.assertEqual(fields["torrentBaseSettings.appMinimumSeeders"], 5)
        self.assertEqual(fields["baseSettings.queryLimit"], 20)
        self.assertEqual(fields["sort"], 0)

    def test_slot_seed_state_prefers_seed_definition(self) -> None:
        store = g.StateStore()
        store.runtime = {"slotState": {}}
        indexers = [
            {"id": 1, "definitionName": "1337x", "name": "1337x", "priority": 10, "appProfileId": 1, "tags": [2]},
            {"id": 2, "definitionName": "bitsearch", "name": "BitSearch", "priority": 20, "appProfileId": 1, "tags": []},
        ]
        slot_state = g.seed_slot_state(store, indexers)
        self.assertEqual(slot_state["general_primary"]["definitionName"], "1337x")

    def test_healthy_warning_heal_plan_only_targets_proxy_healthy_indexers(self) -> None:
        slot_reports = {
            "general_secondary": {
                "current": {"name": "LimeTorrents"},
                "proxyTest": {"status": 200},
            },
            "general_tertiary": {
                "current": {"name": "The Pirate Bay"},
                "proxyTest": {"status": 503},
            },
        }
        warnings = {
            "sonarr": {"LimeTorrents", "The Pirate Bay"},
            "lidarr": {"The Pirate Bay"},
        }
        plan = g.healthy_warning_heal_plan(warnings, slot_reports)
        self.assertEqual(plan["sonarr"], ["LimeTorrents"])
        self.assertNotIn("lidarr", plan)

    def test_application_sync_cooldown_tracks_by_application_name(self) -> None:
        store = g.StateStore()
        store.runtime = {"lastApplicationSyncAt": {}}
        self.assertEqual(g.app_sync_cooldown_remaining(store, "sonarr"), 0)
        g.note_app_sync(store, "sonarr")
        self.assertGreater(g.app_sync_cooldown_remaining(store, "sonarr"), 0)

    def test_replacement_cooldown_is_scoped_per_slot(self) -> None:
        store = g.StateStore()
        store.runtime = {"replacementHistory": [], "lastReplacementAtBySlot": {}}
        g.note_replacement_history(store, "general_secondary", "0magnet", "replaced:torrentdownload")
        self.assertGreater(g.replacement_cooldown_remaining(store, "general_secondary"), 0)
        self.assertEqual(g.replacement_cooldown_remaining(store, "general_primary"), 0)

    def test_stale_app_indexers_detects_name_to_prowlarr_id_mismatch(self) -> None:
        arr_indexers = [
            {
                "id": 4,
                "name": "The Pirate Bay (Prowlarr)",
                "fields": [{"name": "baseUrl", "value": "http://prowlarr:9696/1/"}],
            },
            {
                "id": 18,
                "name": "TorrentDownload (Prowlarr)",
                "fields": [{"name": "baseUrl", "value": "http://prowlarr:9696/20/"}],
            },
        ]
        current_indexers = [
            {"id": 1, "name": "1337x"},
            {"id": 20, "name": "TorrentDownload"},
        ]
        stale = g.stale_app_indexers(arr_indexers, current_indexers)
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0]["name"], "The Pirate Bay (Prowlarr)")
        self.assertEqual(stale[0]["currentProwlarrName"], "1337x")

    def test_collect_indexer_log_signals_counts_recent_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "prowlarr.txt"
            log_path.write_text(
                "\n".join(
                    [
                        "[Warn] Cardigann: [torrentdownload] Invalid category for value: 'VideoAnime'",
                        "[Warn] Cardigann: Invalid Release: 'X' from indexer: TorrentDownload. No categories provided.",
                        "[Error] NewznabController: System.NotSupportedException: Invalid torrent file contents.",
                    ]
                ),
                encoding="utf-8",
            )
            original_dirs = (
                g.PROWLARR_LOG_DIR,
                g.RADARR_LOG_DIR,
                g.SONARR_LOG_DIR,
                g.LIDARR_LOG_DIR,
            )
            try:
                g.PROWLARR_LOG_DIR = tmp
                g.RADARR_LOG_DIR = tmp
                g.SONARR_LOG_DIR = tmp
                g.LIDARR_LOG_DIR = tmp
                signals = g.collect_indexer_log_signals(
                    [{"name": "TorrentDownload", "definitionName": "torrentdownload"}]
                )
            finally:
                g.PROWLARR_LOG_DIR, g.RADARR_LOG_DIR, g.SONARR_LOG_DIR, g.LIDARR_LOG_DIR = original_dirs

        self.assertGreaterEqual(signals["TorrentDownload"]["count"], 2)
        self.assertTrue(signals["TorrentDownload"]["samples"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
