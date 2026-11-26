"""Every promise of booking or human attention leads to the surface that performs it.

/ and /ia answer with the generative model and register no booking, human
handover, opt-out or privacy request. Those flows exist only in /chat
(WebChat + conversation.py). Text that offers them must link to /chat.
"""
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reigel import ai_chat
from reigel.api import create_app

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
TEAM_LABEL = "Citas y equipo"
# Wording that offers an action only /chat can perform.
COMMERCIAL_PROMISE = re.compile(
    r"reserv|hablar con el equipo|atención del equipo|horarios? disponibles?|coordinaci[oó]n de citas", re.I
)


class Links(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.links = []
        self.chat_openers = []
        self._link = None
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "data-open-chat" in attrs:
            self.chat_openers.append(attrs)
        if tag == "a":
            self._link = {"href": attrs.get("href"), "attrs": attrs, "text": ""}

    def handle_data(self, data):
        if self._link is not None:
            self._link["text"] += data

    def handle_endtag(self, tag):
        if tag == "a" and self._link is not None:
            self._link["text"] = " ".join(self._link["text"].split())
            self.links.append(self._link)
            self._link = None


def paragraphs(html):
    return re.findall(r"<p\b[^>]*>.*?</p>", html, re.S)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("reigel.api.load_environment", lambda path=None: None)
    monkeypatch.setenv("REIGEL_ENV", "local")
    monkeypatch.delenv("SITE_URL", raising=False)
    return TestClient(create_app(tmp_path / "actions.sqlite3"))


@pytest.mark.parametrize("page", ["contacto", "preguntas", "proceso"])
def test_corporate_text_that_offers_booking_or_humans_links_to_chat(page):
    html = (FRONTEND / "pages" / f"{page}.html").read_text(encoding="utf-8")
    promising = [block for block in paragraphs(html) if COMMERCIAL_PROMISE.search(block)]
    assert promising, page
    for block in promising:
        parsed = Links(block)
        assert any(link["href"] == "/chat" for link in parsed.links), (page, block[:160])


def test_buttons_that_open_ia_never_promise_the_team_or_a_booking():
    shells = [FRONTEND / "landing.html", *sorted((FRONTEND / "pages").glob("*.html"))]
    openers = 0
    for path in shells:
        html = path.read_text(encoding="utf-8")
        for inner in re.findall(r"<button\b[^>]*\bdata-open-chat\b[^>]*>(.*?)</button>", html, re.S):
            openers += 1
            label = " ".join(re.sub(r"<[^>]+>", " ", inner).split())
            assert not re.search(r"equipo|cita|reserv|coordina|humano|persona", label, re.I), (path.name, label)
    assert openers  # general conversation entry points to /ia still exist


def test_contact_section_for_appointments_opens_the_booking_chat(client):
    page = client.get("/contacto").text
    section = re.search(r"<h2>Chat y coordinación de citas</h2>.*?</div>", page, re.S).group(0)
    parsed = Links(section)
    assert not parsed.chat_openers
    assert parsed.links and {link["href"] for link in parsed.links} == {"/chat"}


def test_chat_page_keeps_the_booking_and_human_actions(client):
    page = client.get("/chat").text
    assert "data-chat-book" in page and "data-chat-human" in page and 'id="chat-book-form"' in page


@pytest.mark.parametrize("path", ["/", "/ia"])
def test_ia_offers_an_explicit_route_to_booking_and_humans(client, path):
    page = client.get(path).text
    parsed = Links(page)
    team = [link for link in parsed.links if link["href"] == "/chat"]
    assert {link["text"] for link in team} >= {TEAM_LABEL}
    assert any(link["attrs"].get("role") == "menuitem" for link in team)
    assert any(link["attrs"].get("id") == "ia-team" for link in team)
    assert "no registra esas solicitudes" in page


def test_ia_never_offers_a_review_it_cannot_register():
    # The replacement used when a reply is withheld points to the real route
    # instead of offering an in-conversation review by the team.
    assert TEAM_LABEL in ai_chat.SAFE_REPLACEMENT
    assert "¿Quieres que el equipo" not in ai_chat.SAFE_REPLACEMENT
    ai_chat.validate_workspace_reply(ai_chat.SAFE_REPLACEMENT, verified=False)


def test_workspace_prompt_sends_commercial_requests_to_the_real_flow():
    prompt = ai_chat.workspace_instructions()
    assert TEAM_LABEL in prompt
    for request in ("reservar", "hablar con una persona", "dejar de recibir mensajes", "sus datos"):
        assert request in prompt
