import os
from db_manager import DatabaseManager


def run_table_visualization():
    os.makedirs("../images/table_viz", exist_ok=True)

    db = DatabaseManager()
    db.create_database("school_db")
    db.create_table(
        db_name="school_db",
        table_name="students",
        schema={
            "student_id": int,
            "name": str,
            "age": int,
            "grade": float,
        },
        order=4,
        search_key="student_id"
    )

    table, _ = db.get_table("school_db", "students")

    records = [
        {"student_id": 10, "name": "Alice",   "age": 20, "grade": 88.5},
        {"student_id": 5,  "name": "Bob",     "age": 22, "grade": 76.0},
        {"student_id": 20, "name": "Charlie", "age": 19, "grade": 91.0},
        {"student_id": 3,  "name": "Diana",   "age": 21, "grade": 83.5},
        {"student_id": 7,  "name": "Eve",     "age": 23, "grade": 95.0},
        {"student_id": 15, "name": "Frank",   "age": 20, "grade": 70.0},
        {"student_id": 12, "name": "Grace",   "age": 22, "grade": 88.0},
        {"student_id": 25, "name": "Hank",    "age": 19, "grade": 60.5},
        {"student_id": 6,  "name": "Ivy",     "age": 21, "grade": 77.5},
        {"student_id": 17, "name": "Jack",    "age": 20, "grade": 85.0},
        {"student_id": 30, "name": "Karen",   "age": 22, "grade": 92.0},
    ]

    for i, record in enumerate(records):
        table.insert(record)
        sid = record["student_id"]
        print(f"Inserted student_id={sid} ({record['name']})")

        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "images", "table_viz", f"stage_{i+1}_insert_{sid}")
        table.data.visualize_tree(path)
        print(f"Saved: {path}.png")

    final_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "images", "table_viz", "final_table")
    table.data.visualize_tree(final_path)
    print(f"\nFinal tree saved: {final_path}.png")

    delete_ids = [5, 20]  # Bob (5), Charlie (20)

    for i, sid in enumerate(delete_ids):
        success, msg = table.delete(sid)
        if success:
            print(f"\nDeleted student_id={sid}")
        else:
            print(f"\nFailed to delete student_id={sid}: {msg}")

        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "images", "table_viz", f"delete_step_{i+1}_id_{sid}")
        table.data.visualize_tree(path)
        print(f"Saved: {path}.png")

    print("\nRemaining records (sorted by student_id):")
    print(f"{'ID':<6} {'Name':<10} {'Age':<5} {'Grade'}")
    print("-" * 35)
    for _, record in table.get_all():
        print(f"{record['student_id']:<6} {record['name']:<10} {record['age']:<5} {record['grade']}")


if __name__ == "__main__":
    run_table_visualization()