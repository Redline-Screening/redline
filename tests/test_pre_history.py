"""Pre-investment history, decisions, notes and export."""
import io

from openpyxl import load_workbook
from test_runner import C1
from test_screening import stored

from redline import preinvest, summary, ui

C2 = {**C1, "id": "c2", "key": "child-labour", "label": "Child labour", "type": "conduct", "threshold": None}
SAAB = {"id": "x1", "name": "Saab", "isin": "SE0021921269", "weight": 0, "type": "candidate", "pre_investment": True, "decision": "review"}
ACME = {"id": "x2", "name": "Acme", "isin": None, "weight": 0, "type": "prospect", "pre_investment": True, "decision": "prospect"}
HELD = {"id": "h1", "name": "Palantir", "weight": 9, "type": "holding"}
F = stored(holding_id="x1", criterion_id="c1", severity="high")


def score(h, c, level, checked, **k):
    return {"holding_id": h, "criterion_id": c, "controversy": {"level": level, "checked": checked}, **k}


def scores():
    s1 = score("x1", "c1", "high", "2026-11-26", summary="Breach because of high-severity incidents. Saab supplies weapons.")
    s1["summary_key"] = summary.state_key(s1, [F], C1)
    return {("x1", "c1"): s1, ("x1", "c2"): score("x1", "c2", "none", "2026-11-26"),
            ("x2", "c1"): score("x2", "c1", "none", "2026-11-20"), ("h1", "c1"): score("h1", "c1", "high", "2026-11-27")}


NOTES = [{"id": "n1", "holding_id": "x1", "text": "Older note", "created_at": "2026-11-25T10:00:00"},
         {"id": "n2", "holding_id": "x1", "text": "Rejected because of litigation", "created_at": "2026-11-26T10:00:00"}]


def test_history():
    rows = preinvest.history([SAAB, ACME, HELD], [C1, C2], scores(), [F], NOTES)
    assert [r["company"] for r in rows] == ["Saab", "Acme"]              # holdings never appear; newest first
    saab = rows[0]
    assert (saab["date"], saab["result"], saab["criteria"]) == ("2026-11-26", "breach", "Child labour, Military")
    assert saab["summary"] == "Breach because of high-severity incidents."
    assert (saab["note"], saab["note_date"], saab["decision"], saab["in_universe"]) == ("Rejected because of litigation", "2026-11-26", "review", False)
    assert (rows[1]["result"], rows[1]["in_universe"], rows[1]["summary"]) == ("clear", True, "")


def test_decisions():
    assert preinvest.decision_change(SAAB, "prospect")["type"] == "prospect"
    assert preinvest.decision_change(ACME, "rejected")["type"] == "candidate"
    assert preinvest.decision_change(SAAB, "rejected")["decision"] == "rejected"


def test_export():
    ws = load_workbook(io.BytesIO(preinvest.to_xlsx(preinvest.history([SAAB, ACME], [C1, C2], scores(), [F], NOTES)))).active
    assert [c.value for c in ws[1]] == preinvest.COLUMNS and ws["A1"].font.bold
    assert [ws["B2"].value, ws["E2"].value, ws["G2"].value, ws["H2"].value] == ["Saab", "Breach", "Under review", "Rejected because of litigation"]


def tables():
    return dict(holdings=[dict(HELD), dict(SAAB), dict(ACME)], criteria=[dict(C1), dict(C2)], findings=[dict(F)],
                scores=list(scores().values()), company_notes=[dict(n) for n in NOTES], workspaces=[{"user_id": "u1", "mode": "ai"}])


def test_list_on_the_page(make_app):
    app = make_app(**tables())
    app.session_state["screening-section"] = "pre"
    app.switch_page("views/screening.py").run()
    assert not app.exception
    assert "Previous Pre-investment Screenings" in [s.value for s in app.subheader]
    table = app.get("arrow_data_frame")[0] if app.get("arrow_data_frame") else None
    assert any(d.proto.label == "Download history" for d in app.get("download_button"))


def test_profile_decision_and_notes(make_app):
    app = make_app(**tables())
    app.session_state[ui.COMPANY_KEY] = "x1"
    app.switch_page("views/company.py").run()
    assert not app.exception and "Investment Notes" in [s.value for s in app.subheader]
    assert app.selectbox(key="decision-x1").value == "Under review"
    shown = [t.value for t in app.text]
    assert shown.index("Rejected because of litigation") < shown.index("Older note")     # newest first
    app.text_area(key="note-x1").input("Revisit in Q1").run()
    next(b for b in app.button if b.label == "Save note").click().run()
    notes = app.session_state["_supabase"].tables["company_notes"]
    assert notes[-1]["text"] == "Revisit in Q1" and notes[-1]["holding_id"] == "x1"
    app.selectbox(key="decision-x1").set_value("Added as prospect").run()
    saab = next(h for h in app.session_state["_supabase"].tables["holdings"] if h["id"] == "x1")
    assert (saab["decision"], saab["type"]) == ("prospect", "prospect")


def test_plain_holding_has_no_notes(make_app):
    app = make_app(**tables())
    app.session_state[ui.COMPANY_KEY] = "h1"
    app.switch_page("views/company.py").run()
    assert "Investment Notes" not in [s.value for s in app.subheader]


def test_unmarked_prospect_and_candidate_are_listed():
    """Companies added before migration 014 have no marker; prospects with results still appear."""
    jj = {"id": "j1", "name": "Johnson & Johnson", "isin": None, "weight": 0, "type": "prospect"}
    cand = {"id": "j2", "name": "Unmarked", "isin": None, "weight": 0, "type": "candidate"}
    s = {("j1", "c1"): score("j1", "c1", "none", "2026-11-26"), ("j2", "c1"): score("j2", "c1", "none", "2026-11-25")}
    rows = preinvest.history([jj, cand, HELD], [C1], {**s, ("h1", "c1"): score("h1", "c1", "high", "2026-11-27")}, [], [])
    assert [(r["company"], r["decision"], r["in_universe"]) for r in rows] == [("Johnson & Johnson", "prospect", True),
                                                                             ("Unmarked", "review", False)]


def test_prospect_without_results_is_not_listed():
    assert preinvest.history([dict(ACME, pre_investment=False)], [C1], {}, [], []) == []


def test_page_lists_unmarked_prospect(make_app):
    jj = {"id": "j1", "name": "Johnson & Johnson", "isin": None, "weight": 0, "type": "prospect"}
    app = make_app(holdings=[dict(HELD), jj], criteria=[dict(C1)], scores=[score("j1", "c1", "none", "2026-11-26")],
                   workspaces=[{"user_id": "u1", "mode": "ai"}])
    app.session_state["screening-section"] = "pre"
    app.switch_page("views/screening.py").run()
    assert not app.exception and "Previous Pre-investment Screenings" in [s.value for s in app.subheader]


def open_profile(make_app):
    app = make_app(**tables())
    app.session_state[ui.COMPANY_KEY] = "x1"
    return app.switch_page("views/company.py").run()


def test_edit_note(make_app):
    app = open_profile(make_app)
    app.button(key="note-e-n1").click().run()
    app.text_area(key="note-edit-n1").input("Older note, revised").run()
    app.button(key="note-save-n1").click().run()
    assert not app.exception
    note = next(n for n in app.session_state["_supabase"].tables["company_notes"] if n["id"] == "n1")
    assert note["text"] == "Older note, revised" and note["updated_at"]
    assert any("edited" in c.value for c in app.caption)


def test_delete_note_needs_confirmation(make_app):
    app = open_profile(make_app)
    app.button(key="note-d-n1").click().run()
    assert len(app.session_state["_supabase"].tables["company_notes"]) == 2
    assert app.button(key="note-d-n1").label == "Confirm delete"
    app.button(key="note-d-n1").click().run()
    assert [n["id"] for n in app.session_state["_supabase"].tables["company_notes"]] == ["n2"]


def test_empty_edit_is_refused(make_app):
    app = open_profile(make_app)
    app.button(key="note-e-n2").click().run()
    app.text_area(key="note-edit-n2").input("").run()
    app.button(key="note-save-n2").click().run()
    assert app.error[0].value == "A note cannot be empty."
