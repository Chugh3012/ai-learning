from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jinja2 import Environment, FileSystemLoader, select_autoescape

from prism.lib.topics import list_topics, load_pack
from prism.services.ingest import read_sources

WEB = Path(__file__).resolve().parent
TEMPLATES = WEB / "templates"
STATIC = WEB / "static"
PUBLIC = WEB / "public"
BRAND = "Chugh Vibes"

def _site(pack) -> dict:
    s = pack.settings.get("site", {}) if isinstance(pack.settings, dict) else {}
    return {
        "noun": s.get("noun", pack.name.lower()),
        "noun_title": s.get("noun_title", pack.name),
    }

def _sources(pack, limit: int = 12) -> list[str]:
    try:
        return [s["title"] for s in read_sources(pack.sources_opml)][:limit]
    except Exception:
        return []

def build() -> None:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)),
                      autoescape=select_autoescape(["html", "j2"]))
    packs = [load_pack(t) for t in (list_topics() or [])]

    PUBLIC.mkdir(parents=True, exist_ok=True)
    for child in PUBLIC.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    for f in STATIC.iterdir():
        if f.is_file():
            shutil.copy2(f, PUBLIC / f.name)

    cards = [{"id": p.id, "name": p.name, "tagline": p.tagline} for p in packs]
    (PUBLIC / "index.html").write_text(
        env.get_template("hub.html.j2").render(brand=BRAND, topics=cards), encoding="utf-8")

    topic_tmpl = env.get_template("topic.html.j2")
    for p in packs:
        site = _site(p)
        html = topic_tmpl.render(brand=BRAND, topic_id=p.id, name=p.name, tagline=p.tagline,
                                 noun=site["noun"], noun_title=site["noun_title"],
                                 sources=_sources(p))
        (PUBLIC / p.id).mkdir(parents=True, exist_ok=True)
        (PUBLIC / p.id / "index.html").write_text(html, encoding="utf-8")

    print(f"site: built hub + {len(packs)} topic pages ({', '.join(p.id for p in packs)}) -> {PUBLIC}")

if __name__ == "__main__":
    build()
