import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["CLARITY_DATA"] = tempfile.mkdtemp(); os.environ["CLARITY_PROVIDER"] = "offline"
import store, sample, sources, decks, deck, review, export


class Sample(unittest.TestCase):
    def test_sample_loads_and_runs_end_to_end(self):
        pid = sample.build(); self.assertTrue(pid); self.assertIsNone(sample.build())            # second call refuses without --force
        self.assertTrue(sample.build(force=True)); self.assertEqual(len(store.list_projects()), 1)
        p = store.load_project(store.list_projects()[0]["id"])
        self.assertEqual(sum(s["kind"] == "deck" for s in p["sources"]), 3)
        lib = decks.library(p); self.assertEqual(len(lib["decks"]), 3); self.assertTrue(lib["conflicts"])
        chunks, _, _ = sources.resolve(p)
        slides, story = deck.build(p, chunks)
        self.assertEqual(slides[1]["kind"], "summary"); self.assertGreaterEqual(len(slides), 6)
        p["slides"] = slides; p["storyline"].update(story)
        r = review.review(p); self.assertIn("issues", r)
        self.assertEqual([i for i in r["issues"] if i["severity"] in ("blocker", "major") and i["check"] in ("Relevance", "Evidence")], [], "the sample should show a healthy flow")
        self.assertTrue(export.build_pptx(p, None)[0].startswith(b"PK"))


if __name__ == "__main__": unittest.main()
