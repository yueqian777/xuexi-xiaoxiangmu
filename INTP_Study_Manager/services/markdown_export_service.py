from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from db import DATA_DIR, fetch_all
from repositories.ppt_repository import get_slide_question_tree
from services.export_path_service import ensure_clean_dir, safe_filename


def export_obsidian_vault(user_id: int, *, subject: str | None = None, mode: str = "incremental") -> dict[str, Any]:
    user_id_int = int(user_id)
    export_time = datetime.now().isoformat(timespec="seconds")
    root = DATA_DIR / "obsidian_export" / f"user_{user_id_int}"
    if mode == "overwrite":
        ensure_clean_dir(root)
    else:
        root.mkdir(parents=True, exist_ok=True)

    data = _collect_private_data(user_id_int, subject=subject)
    card_links = _card_wikilinks(data["knowledge_cards"])
    stats = {"files_written": 0, "root": str(root)}

    _write_file(root / "_Home.md", _global_home(data, export_time, user_id_int), mode, stats)
    _write_file(root / "_All_Knowledge_Index.md", _knowledge_index(data["knowledge_cards"], card_links, export_time, user_id_int), mode, stats)
    _write_file(root / "_All_Mistakes.md", _mistake_index(data["mistakes"], export_time, user_id_int), mode, stats)
    _write_file(root / "_All_Reviews.md", _review_index(data["review_tasks"], card_links, export_time, user_id_int), mode, stats)

    subjects = sorted(data["subjects"])
    for subject_name in subjects:
        subject_root = root / safe_filename(subject_name, "Uncategorized")
        for child in [
            "00_Daily",
            "10_Knowledge",
            "20_Mistakes",
            "30_Sessions",
            "40_PPT",
            "50_Review",
            "60_Parking_Lot",
            "_attachments",
        ]:
            (subject_root / child).mkdir(parents=True, exist_ok=True)
        _write_file(
            subject_root / "_Subject_Home.md",
            _subject_home(subject_name, data, card_links, export_time, user_id_int),
            mode,
            stats,
        )

    for card in data["knowledge_cards"]:
        subject_root = _subject_root(root, card["subject"])
        path = subject_root / "10_Knowledge" / f"{card_links[int(card['id'])]}.md"
        _write_file(path, _knowledge_card_markdown(card, data["knowledge_links"], card_links, export_time), mode, stats)

    for mistake in data["mistakes"]:
        subject_root = _subject_root(root, mistake["subject"])
        filename = f"mistake-{mistake['id']}-{safe_filename(mistake.get('topic'), 'mistake')}.md"
        _write_file(subject_root / "20_Mistakes" / filename, _mistake_markdown(mistake, card_links, export_time), mode, stats)

    for session in data["study_sessions"]:
        subject_root = _subject_root(root, session["subject"])
        filename = f"session-{session['id']}-{safe_filename(session.get('date'), 'date')}-{safe_filename(session.get('title'), 'session')}.md"
        _write_file(subject_root / "30_Sessions" / filename, _session_markdown(session, export_time), mode, stats)

    for parking in data["parking_lot"]:
        subject_root = _subject_root(root, parking.get("subject") or "Uncategorized")
        filename = f"parking-{parking['id']}-{safe_filename(parking.get('question'), 'question')}.md"
        _write_file(subject_root / "60_Parking_Lot" / filename, _parking_markdown(parking, export_time), mode, stats)

    for subject_name in subjects:
        subject_root = _subject_root(root, subject_name)
        reviews = [item for item in data["review_tasks"] if item["subject"] == subject_name]
        _write_file(subject_root / "50_Review" / "review-tasks.md", _review_index(reviews, card_links, export_time, user_id_int), mode, stats)

    _write_ppt_slides(root, data, card_links, export_time, mode, stats)
    return stats


def _collect_private_data(user_id: int, *, subject: str | None) -> dict[str, Any]:
    subject_filter = "AND subject = ?" if subject else ""
    subject_params: tuple[Any, ...] = (subject,) if subject else ()
    cards = fetch_all(f"SELECT * FROM knowledge_cards WHERE user_id = ? {subject_filter} ORDER BY created_at DESC, id DESC", (user_id, *subject_params))
    sessions = fetch_all(f"SELECT * FROM study_sessions WHERE user_id = ? {subject_filter} ORDER BY date DESC, id DESC", (user_id, *subject_params))
    mistakes = fetch_all(f"SELECT * FROM mistakes WHERE user_id = ? {subject_filter} ORDER BY created_at DESC, id DESC", (user_id, *subject_params))
    parking = fetch_all(f"SELECT * FROM parking_lot WHERE user_id = ? {subject_filter} ORDER BY created_at DESC, id DESC", (user_id, *subject_params))
    decks = fetch_all(f"SELECT * FROM ppt_decks WHERE user_id = ? {subject_filter} ORDER BY created_at DESC, id DESC", (user_id, *subject_params))
    deck_ids = [int(deck["id"]) for deck in decks]
    slides = _slides_for_decks(user_id, deck_ids)
    links = fetch_all(
        """
        SELECT kl.*, source.subject AS source_subject, source.topic AS source_topic, target.subject AS target_subject, target.topic AS target_topic
        FROM knowledge_links kl
        JOIN knowledge_cards source ON source.id = kl.source_knowledge_id AND source.user_id = kl.user_id
        JOIN knowledge_cards target ON target.id = kl.target_knowledge_id AND target.user_id = kl.user_id
        WHERE kl.user_id = ?
        ORDER BY kl.created_at DESC, kl.id DESC
        """,
        (user_id,),
    )
    reviews = fetch_all(
        """
        SELECT rt.*, kc.subject, kc.topic
        FROM review_tasks rt
        JOIN knowledge_cards kc ON kc.id = rt.knowledge_id AND kc.user_id = rt.user_id
        WHERE rt.user_id = ?
        ORDER BY rt.review_date ASC, rt.id ASC
        """,
        (user_id,),
    )
    explanations = fetch_all(
        """
        SELECT se.*
        FROM slide_explanations se
        JOIN ppt_slides ps ON ps.id = se.slide_id AND ps.user_id = se.user_id
        WHERE se.user_id = ?
        ORDER BY se.created_at DESC, se.id DESC
        """,
        (user_id,),
    )
    subjects = {item["subject"] or "Uncategorized" for item in cards + sessions + mistakes + decks}
    subjects.update(item.get("subject") or "Uncategorized" for item in parking)
    return {
        "subjects": subjects or {"Uncategorized"},
        "knowledge_cards": cards,
        "knowledge_links": links,
        "mistakes": mistakes,
        "study_sessions": sessions,
        "review_tasks": reviews,
        "parking_lot": parking,
        "ppt_decks": decks,
        "ppt_slides": slides,
        "slide_explanations": explanations,
        "user_id": user_id,
    }


def _slides_for_decks(user_id: int, deck_ids: list[int]) -> list[dict[str, Any]]:
    if not deck_ids:
        return []
    placeholders = ",".join("?" for _ in deck_ids)
    return fetch_all(
        f"SELECT * FROM ppt_slides WHERE user_id = ? AND deck_id IN ({placeholders}) ORDER BY deck_id ASC, slide_number ASC",
        (user_id, *tuple(deck_ids)),
    )


def _write_ppt_slides(root: Path, data: Mapping[str, Any], card_links: dict[int, str], export_time: str, mode: str, stats: dict[str, Any]) -> None:
    latest_by_slide: dict[int, dict[str, Any]] = {}
    for explanation in data["slide_explanations"]:
        latest_by_slide.setdefault(int(explanation["slide_id"]), explanation)
    slides_by_deck: dict[int, list[dict[str, Any]]] = {}
    for slide in data["ppt_slides"]:
        slides_by_deck.setdefault(int(slide["deck_id"]), []).append(slide)
    for deck in data["ppt_decks"]:
        subject_root = _subject_root(root, deck["subject"] or "Uncategorized")
        deck_dir = subject_root / "40_PPT" / f"deck-{deck['id']}-{safe_filename(deck.get('title'), 'deck')}"
        deck_dir.mkdir(parents=True, exist_ok=True)
        for slide in slides_by_deck.get(int(deck["id"]), []):
            explanation = latest_by_slide.get(int(slide["id"]), {})
            tree = get_slide_question_tree(int(slide["id"]), int(data["user_id"]))
            filename = f"slide-{int(slide['slide_number']):03d}.md"
            _write_file(deck_dir / filename, _slide_markdown(deck, slide, explanation, tree, card_links, export_time), mode, stats)


def _card_wikilinks(cards: list[Mapping[str, Any]]) -> dict[int, str]:
    return {
        int(card["id"]): f"knowledge-{card['id']}-{safe_filename(card.get('topic'), 'knowledge')}"
        for card in cards
    }


def _subject_root(root: Path, subject: str) -> Path:
    return root / safe_filename(subject or "Uncategorized", "Uncategorized")


def _write_file(path: Path, content: str, mode: str, stats: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode == "incremental" and path.exists():
        old_hash = _frontmatter_value(path.read_text(encoding="utf-8"), "sync_hash")
        new_hash = _frontmatter_value(content, "sync_hash")
        if old_hash and old_hash == new_hash:
            return
    path.write_text(content, encoding="utf-8")
    stats["files_written"] += 1


def _frontmatter(table: str, db_id: int | str, item_type: str, subject: str, title: str, export_time: str, *, user_id: int = 0, mastery: int | None = None, body: str = "") -> str:
    sync_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    fields: dict[str, Any] = {
        "id": f"{table}-{db_id}",
        "user_id": user_id,
        "db_table": table,
        "db_id": db_id,
        "type": item_type,
        "subject": subject or "Uncategorized",
        "title": title or "",
        "created_at": "",
        "export_time": export_time,
        "sync_hash": sync_hash,
    }
    if mastery is not None:
        fields["mastery"] = mastery
    lines = ["---"]
    for key, value in fields.items():
        lines.append(f"{key}: {_yaml_value(value)}")
    lines.append("---")
    return "\n".join(lines)


def _knowledge_card_markdown(card: Mapping[str, Any], links: list[Mapping[str, Any]], card_links: dict[int, str], export_time: str) -> str:
    card_id = int(card["id"])
    outgoing = [link for link in links if int(link["source_knowledge_id"]) == card_id and int(link["target_knowledge_id"]) in card_links]
    incoming = [link for link in links if int(link["target_knowledge_id"]) == card_id and int(link["source_knowledge_id"]) in card_links]
    link_lines = [f"- [[{card_links[int(link['target_knowledge_id'])]}]] - {link.get('relation_type') or 'related'}" for link in outgoing]
    link_lines += [f"- Backlink from [[{card_links[int(link['source_knowledge_id'])]}]] - {link.get('relation_type') or 'related'}" for link in incoming]
    body = "\n\n".join(
        [
            f"# {card.get('topic')}",
            "## Core Question\n\n" + _text(card.get("core_question")),
            "## One Sentence\n\n" + _text(card.get("one_sentence")),
            "## Logic Or Formula\n\n" + _text(card.get("logic_or_formula")),
            "## Application\n\n" + _text(card.get("application")),
            "## Knowledge Links\n\n" + ("\n".join(link_lines) if link_lines else "No links."),
        ]
    )
    return _frontmatter("knowledge_cards", card_id, "knowledge", card.get("subject"), card.get("topic"), export_time, user_id=int(card.get("user_id") or 0), mastery=int(card.get("mastery") or 0), body=body) + "\n\n" + body


def _mistake_markdown(mistake: Mapping[str, Any], card_links: dict[int, str], export_time: str) -> str:
    link = ""
    if mistake.get("knowledge_id") and int(mistake["knowledge_id"]) in card_links:
        link = f"\n\nKnowledge: [[{card_links[int(mistake['knowledge_id'])]}]]"
    body = f"# {mistake.get('topic')}\n\n## Original Question\n\n{_text(mistake.get('original_question'))}\n\n## Correct Idea\n\n{_text(mistake.get('correct_idea'))}{link}"
    return _frontmatter("mistakes", mistake["id"], "mistake", mistake.get("subject"), mistake.get("topic"), export_time, user_id=int(mistake.get("user_id") or 0), body=body) + "\n\n" + body


def _session_markdown(session: Mapping[str, Any], export_time: str) -> str:
    body = f"# {session.get('title')}\n\n## Main Question\n\n{_text(session.get('main_question'))}\n\n## Summary\n\n{_text(session.get('summary'))}"
    return _frontmatter("study_sessions", session["id"], "study_session", session.get("subject"), session.get("title"), export_time, user_id=int(session.get("user_id") or 0), mastery=int(session.get("mastery") or 0), body=body) + "\n\n" + body


def _parking_markdown(parking: Mapping[str, Any], export_time: str) -> str:
    body = f"# Parking Question {parking.get('id')}\n\n{_text(parking.get('question'))}\n\nSource: {_text(parking.get('source'))}"
    return _frontmatter("parking_lot", parking["id"], "parking_lot", parking.get("subject") or "Uncategorized", parking.get("question"), export_time, user_id=int(parking.get("user_id") or 0), body=body) + "\n\n" + body


def _slide_markdown(deck: Mapping[str, Any], slide: Mapping[str, Any], explanation: Mapping[str, Any], tree: list[dict], card_links: dict[int, str], export_time: str) -> str:
    title = slide.get("title") or f"Slide {slide.get('slide_number')}"
    body = "\n\n".join(
        [
            f"# Slide {int(slide['slide_number']):03d}: {title}",
            "## Slide Text\n\n" + _text(slide.get("slide_text")),
            "## AI Explanation\n\n" + _text(explanation.get("explanation")),
            "## Question Tree\n\n" + (_render_question_tree(tree, card_links) if tree else "No questions."),
        ]
    )
    return _frontmatter("ppt_slides", slide["id"], "ppt_slide", deck.get("subject"), title, export_time, user_id=int(slide.get("user_id") or 0), body=body) + "\n\n" + body


def _render_question_tree(tree: list[dict], card_links: dict[int, str]) -> str:
    lines: list[str] = []

    def visit(node: Mapping[str, Any], prefix: str, depth: int) -> None:
        heading = "#" * min(6, 3 + depth)
        lines.append(f"{heading} Q{prefix} {_text(node.get('question'))}")
        lines.append("")
        lines.append(_text(node.get("answer")))
        knowledge_id = node.get("knowledge_id")
        if knowledge_id and int(knowledge_id) in card_links:
            lines.append("")
            lines.append(f"Linked knowledge card: [[{card_links[int(knowledge_id)]}]]")
        lines.append("")
        for index, child in enumerate(node.get("children") or [], start=1):
            visit(child, f"{prefix}.{index}", depth + 1)

    for index, node in enumerate(tree, start=1):
        visit(node, str(index), 0)
    return "\n".join(lines).strip()


def _global_home(data: Mapping[str, Any], export_time: str, user_id: int) -> str:
    subject_lines = "\n".join(f"- [[{safe_filename(subject, 'Uncategorized')}/_Subject_Home|{subject}]]" for subject in sorted(data["subjects"]))
    body = f"# Home\n\n## Subjects\n\n{subject_lines}\n\n## Export\n\n{export_time}"
    return _frontmatter("obsidian_export", "home", "home", "All", "Home", export_time, user_id=user_id, body=body) + "\n\n" + body


def _subject_home(subject: str, data: Mapping[str, Any], card_links: dict[int, str], export_time: str, user_id: int) -> str:
    cards = [card for card in data["knowledge_cards"] if card["subject"] == subject]
    low = [card for card in cards if int(card.get("mastery") or 0) < 70]
    reviews = [task for task in data["review_tasks"] if task["subject"] == subject]
    questions = sum(1 for deck in data["ppt_decks"] if deck["subject"] == subject)
    card_lines = "\n".join(f"- [[{card_links[int(card['id'])]}]]" for card in cards[:20])
    body = f"# {subject}\n\nKnowledge count: {len(cards)}\n\nLow mastery count: {len(low)}\n\nPending review count: {len(reviews)}\n\nPPT deck count: {questions}\n\n## Knowledge\n\n{card_lines}"
    return _frontmatter("subject_home", safe_filename(subject), "subject_home", subject, subject, export_time, user_id=user_id, body=body) + "\n\n" + body


def _knowledge_index(cards: list[Mapping[str, Any]], card_links: dict[int, str], export_time: str, user_id: int) -> str:
    body = "# All Knowledge\n\n" + "\n".join(f"- [[{card_links[int(card['id'])]}]]" for card in cards)
    return _frontmatter("knowledge_cards", "index", "index", "All", "All Knowledge", export_time, user_id=user_id, body=body) + "\n\n" + body


def _mistake_index(mistakes: list[Mapping[str, Any]], export_time: str, user_id: int) -> str:
    body = "# All Mistakes\n\n" + "\n".join(f"- {item.get('subject')} / {item.get('topic')}: {item.get('summary') or item.get('original_question')}" for item in mistakes)
    return _frontmatter("mistakes", "index", "index", "All", "All Mistakes", export_time, user_id=user_id, body=body) + "\n\n" + body


def _review_index(reviews: list[Mapping[str, Any]], card_links: dict[int, str], export_time: str, user_id: int) -> str:
    lines = []
    for review in reviews:
        card_id = int(review.get("knowledge_id") or 0)
        target = f"[[{card_links[card_id]}]]" if card_id in card_links else review.get("topic", "")
        lines.append(f"- {review.get('review_date')} {review.get('review_stage')}: {target} ({review.get('status')})")
    body = "# Reviews\n\n" + ("\n".join(lines) if lines else "No reviews.")
    return _frontmatter("review_tasks", "index", "review_index", "All", "Reviews", export_time, user_id=user_id, body=body) + "\n\n" + body


def _frontmatter_value(content: str, key: str) -> str:
    if not content.startswith("---"):
        return ""
    for line in content.splitlines()[1:]:
        if line.strip() == "---":
            return ""
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip().strip('"')
    return ""


def _yaml_value(value: Any) -> str:
    if isinstance(value, int):
        return str(value)
    text = str(value or "")
    if not text:
        return '""'
    if any(char in text for char in [":", "#", "\n", "\r"]) or text.strip() != text:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def _text(value: Any) -> str:
    return str(value or "").strip()
