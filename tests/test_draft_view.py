from unittest import TestCase

from app.main import draft_view
from app.storage import StreamDraft


class DraftConflictTest(TestCase):
    stream = {"id": 11, "campaign_id": 22, "name": "Offers"}

    def setUp(self):
        self.baseline = [{"offer_id": 31, "share": 100, "state": "active"}]
        self.pending = [
            {"offer_id": 31, "share": 25, "state": "active"},
            {"offer_id": 32, "share": 75, "state": "active"},
        ]
        self.draft = StreamDraft(
            stream_id=11, revision=1, baseline=self.baseline, pending=self.pending,
            pins={}, pending_pins={"31": 25},
        )

    def test_view_marks_external_edit_as_conflict(self):
        live = [{"offer_id": 99, "share": 100, "state": "active"}]
        self.assertTrue(draft_view(self.stream, live, self.draft)["changed_upstream"])

    def test_push_can_be_retried_after_tracker_applied_it(self):
        view = draft_view(self.stream, list(reversed(self.pending)), self.draft)
        self.assertTrue(view["pending"])
        self.assertFalse(view["changed_upstream"])
        self.assertTrue(view["offers"][0]["pinned"])
