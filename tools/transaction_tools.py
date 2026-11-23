from sqlalchemy.orm import Session
from sqlalchemy import func
from database.models import Transaction


def get_expenses_by_category(db: Session):
    results = (
        db.query(Transaction.category, func.sum(Transaction.amount).label("total"))
        .filter(Transaction.transaction_type == "expense")
        .group_by(Transaction.category)
        .all()
    )

    return {category: float(total) for category, total in results}
