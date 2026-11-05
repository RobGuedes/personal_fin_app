from finance.config import Settings


def test_item_ids_split_from_comma_string():
    s = Settings(pluggy_client_id="x", pluggy_client_secret="y", pluggy_item_ids=" a, b ,,c ")
    assert s.pluggy_item_ids == ["a", "b", "c"]


def test_secret_not_exposed_in_repr():
    s = Settings(pluggy_client_id="x", pluggy_client_secret="super-secret")
    assert "super-secret" not in repr(s)


def test_every_category_has_pt_label_and_icon():
    from finance.classify import load_taxonomy
    from finance.config import CONFIG_DIR

    missing = [
        cid for cid, attrs in load_taxonomy(CONFIG_DIR / "categories.example.yaml").categories.items()
        if not str(attrs.get("label_pt") or "").strip() or not str(attrs.get("icon") or "").strip()
    ]
    assert missing == []
