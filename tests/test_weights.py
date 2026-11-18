from unittest import TestCase

from app.weights import InvalidShares, distribute


class OfferSharesTest(TestCase):
    def test_remainder_is_assigned_in_display_order(self):
        self.assertEqual(distribute({91: None, 3: None, 5: None}), {91: 34, 3: 33, 5: 33})

    def test_pin_is_preserved_after_addition_or_removal(self):
        self.assertEqual(distribute({3: None, 5: 25}), {3: 75, 5: 25})
        self.assertEqual(distribute({3: None, 5: 25, 7: None}), {3: 38, 5: 25, 7: 37})

    def test_inconsistent_pins_are_rejected(self):
        for pins in ({3: 60, 5: 60}, {3: 25}, {3: -1, 5: None}):
            with self.subTest(pins=pins), self.assertRaises(InvalidShares):
                distribute(pins)

    def test_full_fixed_share_leaves_zero_for_an_unpinned_offer(self):
        self.assertEqual(distribute({3: 100, 5: None}), {3: 100, 5: 0})
