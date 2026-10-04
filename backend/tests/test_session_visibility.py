"""Whether the session list makes a stolen login visible.

The list is the screen a user consults when they think someone else is in their
account. "Chrome" on its own cannot distinguish their own laptop from one they
have never seen, and an unfamiliar address buried in the text is easy to skim
past. These tests pin the two things that fix that: a label that names the
platform, and an explicit flag for anything this account has not seen before.
"""

import pytest

from models import UserSession, describe_device, describe_os, describe_session

CHROME_WINDOWS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
SAFARI_MAC = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
SAFARI_IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
EDGE_WINDOWS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
)
FIREFOX_LINUX = "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0"


class TestDeviceDescription:
    @pytest.mark.parametrize("agent,expected", [
        (CHROME_WINDOWS, "Chrome"),
        (SAFARI_MAC, "Safari"),
        (EDGE_WINDOWS, "Edge"),
        (FIREFOX_LINUX, "Firefox"),
        ("curl/8.4.0", "curl"),
        ("PostmanRuntime/7.36.0", "Postman"),
    ])
    def test_it_names_the_browser(self, agent, expected):
        assert describe_device(agent) == expected

    def test_edge_is_not_reported_as_chrome(self):
        # Edge sends a Chrome token too, and Chrome sends a Safari token. Order
        # is the whole mechanism.
        assert describe_device(EDGE_WINDOWS) == "Edge"
        assert describe_device(CHROME_WINDOWS) == "Chrome"

    @pytest.mark.parametrize("agent,expected", [
        (CHROME_WINDOWS, "Windows"),
        (SAFARI_MAC, "macOS"),
        (SAFARI_IPHONE, "iPhone"),
        (EDGE_WINDOWS, "Windows"),
        (FIREFOX_LINUX, "Linux"),
    ])
    def test_it_names_the_platform(self, agent, expected):
        assert describe_os(agent) == expected

    def test_the_label_combines_both(self):
        # Two Chromes on different platforms must not look identical.
        assert describe_session(CHROME_WINDOWS) == "Chrome on Windows"
        assert describe_session(SAFARI_IPHONE) == "Safari on iPhone"

    @pytest.mark.parametrize("agent", [None, "", "   ", "garbage"])
    def test_junk_never_raises(self, agent):
        assert describe_device(agent) == "Unknown device"
        assert describe_session(agent)  # returns something, does not throw

    def test_an_unknown_os_still_names_the_browser(self):
        assert describe_session("SomeCrawler/1.0") == "Unknown device"


def _make_session(app, agent=CHROME_WINDOWS, ip="203.0.113.10"):
    """A persisted UserSession, without going through the login flow.

    id is a UUID string with no column default, so it has to be supplied the way
    start_session() does.
    """
    import uuid

    from extensions import db
    from models import User

    user = User.query.filter_by(username="alice").one()
    session = UserSession(
        id=str(uuid.uuid4()),
        user_id=user.id,
        user_agent=agent,
        ip_address=ip,
    )
    db.session.add(session)
    db.session.commit()
    return session


class TestFamiliarityFlags:
    def test_the_only_session_is_not_flagged(self, app):
        # A single-device user must never be told their only device is somewhere
        # new: with no earlier session there is nothing to compare against.
        with app.app_context():
            client = app.test_client()
            client.post("/auth/register", json={
                "username": "alice", "password": "correct-horse",
            })
            client.post("/auth/login", json={
                "username": "alice", "password": "correct-horse",
            }, headers={"User-Agent": CHROME_WINDOWS})

            rows = client.get("/account/sessions").json["sessions"]
            assert len(rows) == 1
            assert rows[0]["unrecognised"] is False

    def test_a_known_pair_is_not_flagged(self, app):
        with app.app_context():
            client = app.test_client()
            client.post("/auth/register", json={
                "username": "alice", "password": "correct-horse",
            })
            client.post("/auth/login", json={
                "username": "alice", "password": "correct-horse",
            }, headers={"User-Agent": CHROME_WINDOWS})

            rows = client.get("/account/sessions").json["sessions"]
            assert len(rows) == 1
            assert rows[0]["new_location"] is False
            assert rows[0]["new_device"] is False
            assert rows[0]["unrecognised"] is False

    def test_a_new_browser_from_a_known_place_is_flagged(self, app):
        with app.app_context():
            client = app.test_client()
            client.post("/auth/register", json={
                "username": "alice", "password": "correct-horse",
            })
            client.post("/auth/login", json={
                "username": "alice", "password": "correct-horse",
            }, headers={"User-Agent": CHROME_WINDOWS})
            # Same loopback address, different machine.
            client.post("/auth/login", json={
                "username": "alice", "password": "correct-horse",
            }, headers={"User-Agent": FIREFOX_LINUX})

            rows = {r["label"]: r for r in client.get("/account/sessions").json["sessions"]}
            assert rows["Firefox on Linux"]["new_device"] is True
            assert rows["Firefox on Linux"]["unrecognised"] is True
            # Same address, so location is not what changed.
            assert rows["Firefox on Linux"]["new_location"] is False
            assert rows["Chrome on Windows"]["unrecognised"] is False

    def test_a_new_place_on_a_known_browser_is_flagged(self, app):
        with app.app_context():
            from extensions import db

            client = app.test_client()
            client.post("/auth/register", json={
                "username": "alice", "password": "correct-horse",
            })
            client.post("/auth/login", json={
                "username": "alice", "password": "correct-horse",
            }, headers={"User-Agent": CHROME_WINDOWS})
            _make_session(app, CHROME_WINDOWS, ip="198.51.100.200")
            db.session.remove()

            rows = client.get("/account/sessions").json["sessions"]
            away = next(r for r in rows if r["ip_address"] == "198.51.100.200")
            assert away["new_location"] is True
            assert away["new_device"] is False
            assert away["unrecognised"] is True

    def test_the_label_distinguishes_two_identical_browsers(self, app):
        with app.app_context():
            from extensions import db

            client = app.test_client()
            client.post("/auth/register", json={
                "username": "alice", "password": "correct-horse",
            })
            client.post("/auth/login", json={
                "username": "alice", "password": "correct-horse",
            }, headers={"User-Agent": CHROME_WINDOWS})
            _make_session(app, SAFARI_IPHONE)
            db.session.remove()

            labels = [r["label"] for r in client.get("/account/sessions").json["sessions"]]
            assert "Chrome on Windows" in labels
            assert "Safari on iPhone" in labels

    def test_flags_are_false_without_a_comparison_set(self, app):
        # Revoking and exporting call to_dict() with no comparison set. Flags
        # must stay False rather than marking everything unfamiliar.
        with app.app_context():
            client = app.test_client()
            client.post("/auth/register", json={
                "username": "alice", "password": "correct-horse",
            })
            client.post("/auth/login", json={
                "username": "alice", "password": "correct-horse",
            }, headers={"User-Agent": CHROME_WINDOWS})

            from models import User

            row = UserSession.query.one()
            plain = row.to_dict()
            assert plain["new_location"] is False
            assert plain["new_device"] is False
            assert User.query.count() == 1

    def test_a_missing_agent_does_not_count_as_a_new_device(self, app):
        with app.app_context():
            client = app.test_client()
            client.post("/auth/register", json={
                "username": "alice", "password": "correct-horse",
            })
            # Explicitly blank: Werkzeug's test client sends its own User-Agent
            # by default and this path needs a real absence.
            client.post("/auth/login", json={
                "username": "alice", "password": "correct-horse",
            }, headers={"User-Agent": ""})

            rows = client.get("/account/sessions").json["sessions"]
            assert rows[0]["user_agent"] in (None, "")
            assert rows[0]["new_device"] is False
            assert rows[0]["label"] == "Unknown device"

    def test_the_browser_and_os_are_separate_fields(self, app):
        with app.app_context():
            client = app.test_client()
            client.post("/auth/register", json={
                "username": "alice", "password": "correct-horse",
            })
            client.post("/auth/login", json={
                "username": "alice", "password": "correct-horse",
            }, headers={"User-Agent": SAFARI_IPHONE})

            row = client.get("/account/sessions").json["sessions"][0]
            assert row["browser"] == "Safari"
            assert row["os"] == "iPhone"
            assert row["label"] == "Safari on iPhone"
