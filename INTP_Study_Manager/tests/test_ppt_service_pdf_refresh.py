import sqlite3
import types
import unittest
from unittest.mock import patch

from services import ppt_service


class SqliteTransaction:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, exc_type, *_args):
        if exc_type:
            self.conn.rollback()
        else:
            self.conn.commit()
        return False


def _init_page_edit_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE ppt_decks (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            slide_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE ppt_slides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            deck_id INTEGER NOT NULL,
            slide_number INTEGER NOT NULL,
            title TEXT DEFAULT '',
            slide_text TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            image_path TEXT DEFAULT '',
            UNIQUE(deck_id, slide_number)
        );
        CREATE TABLE slide_explanations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            slide_id INTEGER NOT NULL,
            explanation TEXT DEFAULT ''
        );
        CREATE TABLE slide_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            slide_id INTEGER NOT NULL,
            question TEXT DEFAULT ''
        );
        CREATE TABLE ppt_slide_animation_states (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            deck_id INTEGER NOT NULL,
            slide_id INTEGER NOT NULL,
            slide_number INTEGER NOT NULL,
            state_index INTEGER NOT NULL,
            label TEXT DEFAULT '',
            image_path TEXT DEFAULT '',
            step_summary TEXT DEFAULT ''
        );
        CREATE TABLE ppt_sections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            deck_id INTEGER NOT NULL,
            section_index INTEGER NOT NULL,
            start_slide INTEGER NOT NULL,
            end_slide INTEGER NOT NULL,
            updated_at TEXT DEFAULT ''
        );
        CREATE TABLE ppt_study_asset_pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            deck_id INTEGER NOT NULL,
            slide_number INTEGER NOT NULL
        );
        """
    )
    conn.execute("INSERT INTO ppt_decks (id, user_id, slide_count) VALUES (5, 7, 3)")
    conn.executemany(
        """
        INSERT INTO ppt_slides (id, user_id, deck_id, slide_number, title, slide_text, notes, image_path)
        VALUES (?, 7, 5, ?, ?, ?, '', ?)
        """,
        [
            (101, 1, "Page 1", "old text 1", "old-1.png"),
            (102, 2, "Page 2", "old text 2", "old-2.png"),
            (103, 3, "Page 3", "old text 3", "old-3.png"),
        ],
    )
    conn.execute("INSERT INTO slide_explanations (user_id, slide_id, explanation) VALUES (7, 102, 'explain page 2')")
    conn.execute("INSERT INTO slide_questions (user_id, slide_id, question) VALUES (7, 103, 'question page 3')")
    conn.executemany(
        """
        INSERT INTO ppt_slide_animation_states (
            user_id, deck_id, slide_id, slide_number, state_index, label, image_path, step_summary
        )
        VALUES (7, 5, ?, ?, ?, ?, ?, ?)
        """,
        [
            (102, 2, 0, "page 2 start", "p2-0.png", "page 2 start"),
            (103, 3, 0, "page 3 start", "p3-0.png", "page 3 start"),
        ],
    )
    conn.execute(
        """
        INSERT INTO ppt_sections (user_id, deck_id, section_index, start_slide, end_slide)
        VALUES (7, 5, 1, 1, 3)
        """
    )
    conn.execute("INSERT INTO ppt_study_asset_pages (user_id, deck_id, slide_number) VALUES (7, 5, 3)")
    conn.commit()


class PptServicePageEditTest(unittest.TestCase):
    def test_insert_source_page_shifts_existing_rows_without_deleting_explanations_or_questions(self):
        conn = sqlite3.connect(":memory:")
        _init_page_edit_schema(conn)

        with (
            patch.object(ppt_service, "require_login", return_value=types.SimpleNamespace(id=7)),
            patch.object(ppt_service, "write_transaction", return_value=SqliteTransaction(conn)),
        ):
            result = ppt_service.apply_source_page_to_deck(
                {"id": 5},
                {
                    "slide_number": 4,
                    "title": "Inserted Page",
                    "slide_text": "new source text",
                    "notes": "source notes",
                    "image_path": "inserted.png",
                },
                target_slide_number=2,
                mode="insert",
            )

        self.assertEqual(result["inserted"], 1)
        rows = conn.execute("SELECT id, slide_number, title FROM ppt_slides ORDER BY slide_number").fetchall()
        self.assertEqual(
            rows,
            [
                (101, 1, "Page 1"),
                (104, 2, "Inserted Page"),
                (102, 3, "Page 2"),
                (103, 4, "Page 3"),
            ],
        )
        explanation = conn.execute("SELECT slide_id, explanation FROM slide_explanations").fetchone()
        question = conn.execute("SELECT slide_id, question FROM slide_questions").fetchone()
        self.assertEqual(explanation, (102, "explain page 2"))
        self.assertEqual(question, (103, "question page 3"))
        animation_rows = conn.execute(
            "SELECT slide_id, slide_number, image_path FROM ppt_slide_animation_states ORDER BY slide_id"
        ).fetchall()
        self.assertEqual(animation_rows, [(102, 3, "p2-0.png"), (103, 4, "p3-0.png")])
        self.assertEqual(conn.execute("SELECT slide_count FROM ppt_decks WHERE id = 5").fetchone()[0], 4)
        self.assertEqual(conn.execute("SELECT start_slide, end_slide FROM ppt_sections").fetchone(), (1, 4))
        self.assertEqual(conn.execute("SELECT slide_number FROM ppt_study_asset_pages").fetchone()[0], 4)

    def test_replace_source_page_updates_existing_row_without_deleting_explanations_or_questions(self):
        conn = sqlite3.connect(":memory:")
        _init_page_edit_schema(conn)

        with (
            patch.object(ppt_service, "require_login", return_value=types.SimpleNamespace(id=7)),
            patch.object(ppt_service, "write_transaction", return_value=SqliteTransaction(conn)),
        ):
            result = ppt_service.apply_source_page_to_deck(
                {"id": 5},
                {
                    "slide_number": 9,
                    "title": "Replacement Page",
                    "slide_text": "replacement text",
                    "notes": "replacement notes",
                    "image_path": "replacement.png",
                },
                target_slide_number=2,
                mode="replace",
            )

        self.assertEqual(result["replaced"], 1)
        slide = conn.execute(
            "SELECT id, slide_number, title, slide_text, notes, image_path FROM ppt_slides WHERE slide_number = 2"
        ).fetchone()
        self.assertEqual(slide, (102, 2, "Replacement Page", "replacement text", "replacement notes", "replacement.png"))
        self.assertEqual(conn.execute("SELECT slide_id, explanation FROM slide_explanations").fetchone(), (102, "explain page 2"))
        self.assertEqual(conn.execute("SELECT slide_id, question FROM slide_questions").fetchone(), (103, "question page 3"))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM ppt_slide_animation_states WHERE slide_id = 102").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM ppt_slide_animation_states WHERE slide_id = 103").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM ppt_slides").fetchone()[0], 3)
        self.assertEqual(conn.execute("SELECT slide_count FROM ppt_decks WHERE id = 5").fetchone()[0], 3)

    def test_delete_deck_page_removes_that_page_history_and_shifts_later_rows(self):
        conn = sqlite3.connect(":memory:")
        _init_page_edit_schema(conn)
        conn.execute("INSERT INTO slide_questions (user_id, slide_id, question) VALUES (7, 102, 'question page 2')")
        conn.commit()

        with (
            patch.object(ppt_service, "require_login", return_value=types.SimpleNamespace(id=7)),
            patch.object(ppt_service, "write_transaction", return_value=SqliteTransaction(conn)),
        ):
            result = ppt_service.delete_deck_page({"id": 5}, target_slide_number=2)

        self.assertEqual(result["deleted"], 1)
        rows = conn.execute("SELECT id, slide_number, title FROM ppt_slides ORDER BY slide_number").fetchall()
        self.assertEqual(rows, [(101, 1, "Page 1"), (103, 2, "Page 3")])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM slide_explanations WHERE slide_id = 102").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM slide_questions WHERE slide_id = 102").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM ppt_slide_animation_states WHERE slide_id = 102").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT slide_id, question FROM slide_questions").fetchone(), (103, "question page 3"))
        self.assertEqual(
            conn.execute("SELECT slide_id, slide_number FROM ppt_slide_animation_states WHERE slide_id = 103").fetchone(),
            (103, 2),
        )
        self.assertEqual(conn.execute("SELECT slide_count FROM ppt_decks WHERE id = 5").fetchone()[0], 2)
        self.assertEqual(conn.execute("SELECT start_slide, end_slide FROM ppt_sections").fetchone(), (1, 2))
        self.assertEqual(conn.execute("SELECT slide_number FROM ppt_study_asset_pages").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
