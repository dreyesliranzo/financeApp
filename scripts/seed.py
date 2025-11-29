import random
from datetime import date, timedelta

from finance_app import create_app, db, bcrypt
from finance_app.models import User, Transaction, Budget


def seed():
    app = create_app()
    with app.app_context():
        username = "demo"
        password = "demo123"
        user = User.query.filter_by(username=username).first()
        if not user:
            user = User(username=username, password_hash=bcrypt.generate_password_hash(password).decode("utf-8"))
            db.session.add(user)
            db.session.commit()
            print("Created demo user with password 'demo123'")
        else:
            print("Demo user already exists")

        Transaction.query.filter_by(user_id=user.id).delete()
        Budget.query.filter_by(user_id=user.id).delete()
        db.session.commit()

        categories = ["Food", "Housing", "Transportation", "Entertainment", "Utilities", "Travel"]
        start_date = date.today() - timedelta(days=90)
        for i in range(60):
            t_date = start_date + timedelta(days=i)
            if random.random() < 0.25:
                t_type = "income"
                category = "Income"
                amount = random.randint(500, 2000)
            else:
                t_type = "expense"
                category = random.choice(categories)
                amount = random.randint(10, 200)
            tx = Transaction(
                user_id=user.id,
                date=t_date,
                type=t_type,
                category=category,
                amount=round(amount, 2),
                description=f"Sample {category}",
            )
            db.session.add(tx)

        # Budgets for current month and category
        today = date.today()
        month_start = today.replace(day=1)
        next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        month_end = next_month - timedelta(days=1)

        budgets = [
            Budget(user_id=user.id, period_start=month_start, period_end=month_end, category=None, amount=1500),
            Budget(user_id=user.id, period_start=month_start, period_end=month_end, category="Food", amount=400),
        ]
        db.session.add_all(budgets)
        db.session.commit()
        print("Seeded transactions and budgets.")


if __name__ == "__main__":
    seed()
