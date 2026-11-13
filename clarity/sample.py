#!/usr/bin/env python3
"""Load a ready-made sample project so you can click through Clarity with real content.

    python3 sample.py            add "Sample: Berlin platform migration" to your data folder
    python3 sample.py --force    replace it if it is already there

The project has a filled-in brief, a mind map with evidence, source notes, and three small decks
for the Story board. Nothing is sent anywhere. Delete the project from the Projects screen when done."""
import io, sys
import store

NAME = "Sample: Berlin platform migration"
NOTES = """# Pilot results
Release time before the pilot was 9 days. Release time after was 2 days in the pilot team.
Customers say onboarding speed is the main reason they switch vendors.

# Costs
Cloud costs rose 8% last year because of unmanaged workloads. We plan to renegotiate vendor contracts in Q2 to cut spend.
The migration budget is 120k, and the old platform contract ends in June.

# Risks
Migration may delay releases by two weeks if the data team is not staffed before March.
Two services still depend on the old queue and need a rewrite before cutover.
"""


def _deck(slides):
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.util import Inches
    prs = Presentation(); prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    for kind, title, body in slides:
        if kind == "title":
            s = prs.slides.add_slide(prs.slide_layouts[0]); s.shapes.title.text = title; s.placeholders[1].text = body; continue
        s = prs.slides.add_slide(prs.slide_layouts[1]); s.shapes.title.text = title
        if kind == "chart":
            s.placeholders[1]._element.getparent().remove(s.placeholders[1]._element)
            cd = CategoryChartData(); cd.categories = list(body); cd.add_series("Value", list(body.values()))
            s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(1), Inches(1.8), Inches(8), Inches(4.5), cd)
        elif kind == "table":
            s.placeholders[1]._element.getparent().remove(s.placeholders[1]._element)
            t = s.shapes.add_table(len(body), 2, Inches(1), Inches(1.8), Inches(8), Inches(2)).table
            for i, r in enumerate(body):
                for j, c in enumerate(r): t.cell(i, j).text = c
        else:
            tf = s.placeholders[1].text_frame; tf.text = body[0]
            for b in body[1:]: tf.add_paragraph().text = b
        s.notes_slide.notes_text_frame.text = "Speaker note: " + title
    b = io.BytesIO(); prs.save(b); return b.getvalue()


DECKS = {
    "Q3 board update.pptx": [("title", "Q3 board update", "Finance team"), ("bullets", "Agenda", ["Results", "Recommendation", "Next steps"]),
        ("bullets", "Where we are", ["The old platform contract ends in June and release cycles take nine days across the Berlin team."]),
        ("chart", "Revenue grew 12% in Q3 across Europe", {"Q1": 100, "Q2": 106, "Q3": 112}),
        ("bullets", "Recommendation: move to the new platform", ["Releases ship in 2 days instead of 9 in the pilot team", "Cloud costs fall 40k a year"]),
        ("bullets", "Risks and mitigations", ["Data team staffing: hire before March", "Queue rewrite: schedule in Q1"]),
        ("bullets", "Next steps", ["Approve the budget by 30 Nov", "Name a migration owner"]), ("bullets", "Thank you", ["Questions?"])],
    "Platform overview.pptx": [("title", "Platform overview", "Product team"),
        ("bullets", "Platform", ["The platform cuts release time from nine days to two for every team that adopts it.", "Customers say onboarding speed is the main reason they stay."]),
        ("bullets", "Customer story: Acme", ["Acme moved 40 services in six weeks and cut incidents by half."]),
        ("chart", "Revenue grew 15% in Q3 across Europe", {"Q1": 100, "Q2": 110, "Q3": 115}),
        ("bullets", "Roadmap 2023", ["Q1 launch", "Q2 integrations", "Q3 analytics"]),
        ("table", "Plan comparison", [["Plan", "Price"], ["Team", "10k"], ["Enterprise", "40k"]]),
        ("bullets", "Appendix: architecture", ["Services run in three regions with automatic failover."])],
    "Executive narrative.pptx": [("title", "Executive narrative", "Strategy"), ("bullets", "Context", ["Background on the market and our position."]),
        ("bullets", "The problem", ["Releases are slow and costly, and customers notice."]), ("chart", "Results from the pilot", {"Before": 9, "After": 2}),
        ("bullets", "Our recommendation", ["Move all teams to the new platform by March."]), ("bullets", "Next steps", ["Approve the budget and name an owner."])],
}


def build(force=False):
    import sources
    store.init_dirs()
    for p in store.list_projects():
        if p["name"] == NAME:
            if not force: return None
            store.delete_project(p["id"])
    p = store.load_project(store.create_project(NAME)["id"])
    msg = "Move the Berlin team to the new platform by March because releases ship four times faster"
    p["brief"].update(purpose="Get approval to move the Berlin team to the new platform", who="Executive board, six people", knows="They know releases are slow but not what it costs.",
                      feels="Releases fall from 9 days to 2 in the pilot", believes="A phased move is low risk", decides="Approve the migration budget", does="Name a migration owner by Friday",
                      minutes=15, intent="decide", message=msg, mandatory="Cost and risk must appear.", constraints="No vendor names on slides.", tone="Direct and confident", outputs=["presentation", "notes"])
    p["governing"] = msg; p["framework"] = "decision_brief"
    p["answers"] = {"answer": msg, "context": "The old platform contract ends in June.", "arguments": "Releases ship in 2 days instead of 9\nCloud costs fall 40k a year\nA phased rollout keeps risk low",
                    "options": "Stay on the old platform\nBuild our own tooling", "risks": "Data team staffing: hire before March", "ask": "Approve the budget by 30 Nov"}
    p["scope"].update(mode="provided")
    sources.add_text(p, "Pilot notes", NOTES)
    for fname, slides in DECKS.items(): sources.add_deck(p, fname, _deck(slides))
    n = [0]
    def node(parent, text, kind="theme", src=(), weight=0):
        n[0] += 1; nid = f"s{n[0]}"
        p["map"]["nodes"].append({"id": nid, "parent": parent, "text": text, "kind": kind, "src": list(src), "weight": weight}); return nid
    root = node(None, msg)
    a = node(root, "Releases ship in 2 days instead of 9", "insight", weight=3); node(a, "Release time before: 9 days. After: 2 days in the pilot team.", "evidence", ["Pilot notes"])
    b = node(root, "Cloud costs fall 40k a year", "insight", weight=2); node(b, "Cloud costs rose 8% last year because of unmanaged workloads.", "evidence", ["Pilot notes"]); node(b, "We plan to renegotiate vendor contracts in Q2 to cut spend.", "action", ["Pilot notes"])
    c = node(root, "A phased rollout keeps risk low", "insight", weight=1); node(c, "Migration may delay releases by two weeks if the data team is not staffed before March.", "risk", ["Pilot notes"])
    o = node(root, "Staying put or building our own both cost more than moving"); node(o, "Stay on the old platform: the contract ends in June"); node(o, "Build our own tooling: slower and costs more")
    nx = node(root, "Two decisions are needed from the board this month", "action")
    node(nx, "Approve the migration budget (CFO), by 30 Nov", "action"); node(nx, "Name a migration owner (CTO), by Friday", "action")
    p["facilitation"]["questions"] = [{"id": "q1", "q": "What if the data team cannot be hired in time?", "a": "Cutover moves with the hire date. The two-week delay risk is already in the plan."},
                                       {"id": "q2", "q": "Why not keep the old platform one more year?", "a": "The contract ends in June, so staying means renegotiating from a weak position."}]
    p["facilitation"]["decisions"] = [{"id": "d1", "text": "Name a migration owner", "owner": "CTO", "due": "Friday", "kind": "action", "done": False}]
    p["map"] = store.sanitize_map(p["map"])
    store.save_project(p)
    return p["id"]


if __name__ == "__main__":
    pid = build("--force" in sys.argv)
    print("Sample project added. Start Clarity and open it from Projects." if pid else f'"{NAME}" is already there. Use --force to replace it.')
