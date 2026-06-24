import unittest

from prism.domain.edition import Edition


class TestEdition(unittest.TestCase):
    def test_footer_round_trips(self):
        e = Edition("usr_x:prf_y", [12, 7, 30])
        self.assertEqual(e.footer(), "<!-- items: 12,7,30 -->")
        back = Edition.from_markdown("usr_x:prf_y", f"# digest\n\n{e.footer()}\n")
        self.assertEqual(back.ids, [12, 7, 30])     # rank order preserved
        self.assertEqual(back.lens, "usr_x:prf_y")

    def test_from_markdown_tolerates_spaces_and_missing_footer(self):
        self.assertEqual(Edition.from_markdown("l", "x <!-- items: 5, 9 , 2 --> y").ids, [5, 9, 2])
        self.assertEqual(Edition.from_markdown("l", "no footer here").ids, [])
        self.assertEqual(Edition.from_markdown("l", "").ids, [])


if __name__ == "__main__":
    unittest.main()
