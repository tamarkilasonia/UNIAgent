from database import database as db


def test_mock_students_are_loaded():
    student = db.get_student("S1002")
    assert student["name"] == "Bob Smith"
    assert student["email_status"] == "inactive"


def test_unknown_student_returns_none():
    assert db.get_student("S9999") is None


def test_new_ticket_gets_the_next_id_and_starts_open():
    ticket = db.create_ticket("S1002", "email", "My mailbox is inactive.")
    assert ticket["ticket_id"] == "T-102"
    assert ticket["status"] == "open"


def test_get_ticket_only_returns_the_owners_ticket():
    assert db.get_ticket("S1001", 100)["ticket_id"] == "T-100"
    assert db.get_ticket("S1002", 100) is None


def test_running_init_again_does_not_duplicate_mock_data():
    db.init_db()
    assert len(db.list_tickets("S1001")) == 1
