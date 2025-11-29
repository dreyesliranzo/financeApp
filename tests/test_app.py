import pytest

from finance_app import create_app, db
from finance_app.models import User, Transaction


@pytest.fixture
def app():
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SECRET_KEY": "test-secret",
        }
    )
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def register_and_login(client):
    client.post("/register", data={"username": "alice", "password": "password123"}, follow_redirects=True)
    resp = client.post("/login", data={"username": "alice", "password": "password123"}, follow_redirects=True)
    assert resp.status_code == 200


def test_register_creates_user(app, client):
    register_and_login(client)
    with app.app_context():
        user = User.query.filter_by(username="alice").first()
        assert user is not None
        assert user.password_hash != "password123"


def test_add_transaction_flow(app, client):
    register_and_login(client)
    resp = client.post(
        "/transactions/add",
        data={
            "date": "2024-01-01",
            "type": "expense",
            "category": "Food",
            "amount": "25.50",
            "description": "Lunch",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        tx = Transaction.query.first()
        assert tx is not None
        assert tx.amount == 25.50
        assert tx.category == "Food"
