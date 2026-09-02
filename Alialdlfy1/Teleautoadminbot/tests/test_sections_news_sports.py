from core.sections import SectionRegistry, build_section_buttons

class Pipe:
    def ingest(self, **kw): return kw
    def process(self, payload): return payload

def test_news_and_sports_are_isolated():
    r=SectionRegistry(Pipe())
    assert set(r.keys())=={"news","sports"}
    n=r.get("news"); s=r.get("sports")
    assert n.config.settings_namespace=="news"
    assert s.config.settings_namespace=="sports"
    assert n.config.callbacks_namespace=="news"
    assert s.config.callbacks_namespace=="sports"
    assert n.config.key != s.config.key

def test_both_sections_have_same_controls():
    n={x.key for x in build_section_buttons("news")}
    s={x.key for x in build_section_buttons("sports")}
    assert n==s
    assert "blocked" in n and "duplicates" in n and "ai" in n and "repair" in n

def test_callbacks_are_section_specific():
    n={x.callback for x in build_section_buttons("news")}
    s={x.callback for x in build_section_buttons("sports")}
    assert "news:settings" in n and "sports:settings" in s
    assert not (n & s)
