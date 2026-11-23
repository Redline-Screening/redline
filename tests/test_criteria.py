import pytest

from redline import criteria as cr
from redline.constants import TEMPLATES


def edit(c, **changes):
    return {**c, "keywords": ", ".join(c["keywords"]), **changes}


def test_templates_are_complete():
    assert len(TEMPLATES) == 15
    assert len({t["key"] for t in TEMPLATES}) == 15


def test_template_is_added_once():
    first = cr.from_templates(["military", "tobacco"], [])
    assert [c["sort"] for c in first] == [1, 2]
    assert [c["key"] for c in cr.from_templates(["military", "gambling"], first)] == ["gambling"]


def test_custom_validation():
    c = cr.custom("both", " Fur ", "", 0, "high", 50, "Fur, mink; FUR", [])
    assert (c["label"], c["key"], c["keywords"], c["description"]) == ("Fur", "fur", ["fur", "mink"], None)
    for args in [("", "", 0, "high", 50, ""), ("x", "", 101, "high", 50, ""), ("!!", "", 0, "high", 50, "")]:
        with pytest.raises(cr.CriterionProblem):
            cr.custom("both", *args, [])
    with pytest.raises(cr.CriterionProblem):
        cr.custom("both", "FUR", "", 0, "high", 50, "", [c])


def test_edits():
    a, b = cr.from_templates(["military", "tobacco"], [])
    assert cr.diff_edits([a, b], [edit(a, threshold=0.0), edit(b)]) == ([], [])
    changed, removed = cr.diff_edits([a, b], [edit(a, threshold=5.0, active=False), edit(b, remove=True)])
    assert (changed[0]["threshold"], changed[0]["active"], changed[0]["key"]) == (5.0, False, "military")
    assert removed == [b["id"]]
    for bad in (edit(a, threshold=None), edit(a, label=""), edit(a, label="tobacco")):
        with pytest.raises(cr.CriterionProblem):
            cr.diff_edits([a, b], [bad, edit(b)])


def test_page(make_app):
    app = make_app().switch_page("views/criteria.py").run()
    app.multiselect[0].select("military").run()
    next(b for b in app.button if b.label == "Add criteria").click().run()
    assert not app.exception
    assert app.success[0].value == "Criteria added: 1."
    app.text_input[0].input("Fur")
    next(b for b in app.button if b.label == "Add criterion").click().run()
    assert not app.exception
    rows = app.session_state["_supabase"].tables["criteria"]
    assert [r["label"] for r in rows] == ["Military & defence revenue", "Fur"]
    app.text_input[0].input("fur")
    next(b for b in app.button if b.label == "Add criterion").click().run()
    assert app.error[0].value == "A criterion with this name already exists."


def test_types_set_limits():
    for t in TEMPLATES:
        assert (t["threshold"] is None) == (t["type"] == "conduct")
        assert t["controversy_limit"] == {"revenue": "severe", "both": "high"}.get(t["type"], t["controversy_limit"])
    c = cr.custom("conduct", "Bullying", "", 5, "medium", 50, "", [])
    assert (c["threshold"], c["controversy_limit"]) == (None, "medium")
    assert cr.custom("revenue", "Fur", "", 5, "medium", 50, "", [])["controversy_limit"] == "severe"
    with pytest.raises(cr.CriterionProblem):
        cr.custom("conduct", "x", "", None, "low", 50, "", [])


def test_changing_type():
    coal, child = cr.from_templates(["thermal-coal", "child-labour"], [])
    changed, _ = cr.diff_edits([coal], [edit(coal, type="conduct", controversy_limit="medium")])
    assert (changed[0]["threshold"], changed[0]["controversy_limit"]) == (None, "medium")
    changed, _ = cr.diff_edits([child], [edit(child, type="both", threshold=3.0)])
    assert (changed[0]["threshold"], changed[0]["controversy_limit"]) == (3.0, "high")
    with pytest.raises(cr.CriterionProblem):
        cr.diff_edits([child], [edit(child, type="both")])
    with pytest.raises(cr.CriterionProblem):
        cr.diff_edits([coal], [edit(coal, controversy_limit="medium")])
    assert cr.diff_edits([child], [edit(child)]) == ([], [])


def test_conduct_form_has_no_revenue_limit(make_app):
    app = make_app().switch_page("views/criteria.py").run()
    assert [n.label for n in app.number_input] == ["Revenue limit %", "Watch level"]
    app.radio[0].set_value("conduct").run()
    assert [n.label for n in app.number_input] == ["Watch level"]
    app.text_input[0].input("Bullying")
    next(b for b in app.button if b.label == "Add criterion").click().run()
    assert not app.exception
    row = app.session_state["_supabase"].tables["criteria"][0]
    assert (row["type"], row["threshold"]) == ("conduct", None)
