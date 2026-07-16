#!/usr/bin/env python3
"""
Update Sonic Traces Deezer track matches for Tableau events.

What it does
------------
1. Reads the Apple Music play-history CSV.
2. Reads Track Info.xlsx to attach artist/album metadata.
3. Recreates the Tableau Event Name logic in Python.
4. Keeps all existing Deezer matches.
5. Searches Deezer only for event tracks that are still missing.
6. Writes:
   - an updated Tableau-ready preview CSV
   - a review CSV for ambiguous or unmatched tracks

Install once:
    python -m pip install pandas openpyxl requests

Run:
    python update_sonic_traces_previews.py

The default filenames match Janina's current files. You can override them
with command-line arguments; run with --help for details.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pandas as pd
import requests


# ---------------------------------------------------------------------------
# EDIT THIS SECTION WHEN THE TABLEAU EVENT CALCULATION CHANGES
# ---------------------------------------------------------------------------

MOST_PLAYED_TITLE_FRAGMENTS = [
    "The Clock",
    "Charnel Rift",
    "Raising the Pyramid of Power",
    "Incubus of Bloodstained Visions",
    "Spleen Girt With Serpent",
]

LAST_FAVORITED_TITLE_FRAGMENTS = [
    "When I'm Alone",
    "Last Fixed Position XVI",
    "Ann Illusion",
    "Shrouded In Crystals",
    "Cold Wind",
    "Everywhere",
]

DATE_EVENTS = {
    "2026-01-26": "date night",
    "2026-04-18": "slow day",
}

DATE_RANGE_EVENTS = [
    ("2026-04-02", "2026-04-03", "travel to london"),
]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEEZER_SEARCH_URL = "https://api.deezer.com/search"
REQUEST_TIMEOUT_SECONDS = 20
MAX_API_RETRIES = 3
SECONDS_BETWEEN_REQUESTS = 0.20
CONFIDENT_MATCH_THRESHOLD = 0.84
AMBIGUOUS_MATCH_THRESHOLD = 0.70


@dataclass
class Candidate:
    track_id: str
    title: str
    artist: str
    album: str
    score: float
    title_score: float
    artist_score: float
    album_score: float


def normalize_text(value: Any) -> str:
    """Normalize text for matching while preserving the original output."""
    if pd.isna(value):
        return ""

    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.casefold()

    # Remove common version information that frequently differs between catalogues.
    text = re.sub(
        r"\b(remaster(?:ed)?|remix|radio edit|single version|album version|"
        r"live|explicit|deluxe|bonus track|mono|stereo)\b",
        " ",
        text,
    )
    text = re.sub(r"[\(\[\{].*?[\)\]\}]", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def similarity(left: Any, right: Any) -> float:
    a = normalize_text(left)
    b = normalize_text(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def read_semicolon_csv(path: Path) -> pd.DataFrame:
    """Read Tableau/European semicolon CSVs with tolerant encoding handling."""
    errors: list[str] = []
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
        try:
            return pd.read_csv(
                path,
                sep=";",
                encoding=encoding,
                low_memory=False,
                dtype=str,
                keep_default_na=False,
            )
        except (UnicodeDecodeError, pd.errors.ParserError) as exc:
            errors.append(f"{encoding}: {exc}")

    raise RuntimeError(
        f"Could not read {path} as a semicolon-separated CSV.\n"
        + "\n".join(errors)
    )


def create_event_name(row: pd.Series) -> str:
    """Python equivalent of the Tableau Event Name calculated field."""
    title = str(row.get("Song Name", ""))
    date_value = row.get("event_date")

    # Tableau calc order matters: title-based events take precedence over dates.
    if any(fragment.casefold() in title.casefold()
           for fragment in MOST_PLAYED_TITLE_FRAGMENTS):
        return "most played"

    if any(fragment.casefold() in title.casefold()
           for fragment in LAST_FAVORITED_TITLE_FRAGMENTS):
        return "last favorited"

    if pd.notna(date_value):
        date_text = pd.Timestamp(date_value).strftime("%Y-%m-%d")

        if date_text in DATE_EVENTS:
            return DATE_EVENTS[date_text]

        for start_text, end_text, event_name in DATE_RANGE_EVENTS:
            if start_text <= date_text <= end_text:
                return event_name

    return ""


def attach_library_metadata(
    plays: pd.DataFrame,
    library: pd.DataFrame,
) -> pd.DataFrame:
    """
    Attach Artist/Album metadata.

    First match by normalized title + album. If that fails, use title alone only
    when the title is unique in the library, avoiding unsafe guesses.
    """
    plays = plays.copy()
    library = library.copy()

    required_play = {"Song Name", "Album Name"}
    required_library = {"Title", "Artist", "Album"}
    missing_play = required_play - set(plays.columns)
    missing_library = required_library - set(library.columns)

    if missing_play:
        raise KeyError(f"Play-history file is missing columns: {sorted(missing_play)}")
    if missing_library:
        raise KeyError(f"Track Info.xlsx is missing columns: {sorted(missing_library)}")

    plays["_title_key"] = plays["Song Name"].map(normalize_text)
    plays["_album_key"] = plays["Album Name"].map(normalize_text)
    library["_title_key"] = library["Title"].map(normalize_text)
    library["_album_key"] = library["Album"].map(normalize_text)

    library_exact = (
        library.sort_values(["_title_key", "_album_key"])
        .drop_duplicates(["_title_key", "_album_key"])
        [["_title_key", "_album_key", "Artist", "Album", "Title"]]
        .rename(columns={
            "Artist": "library_artist",
            "Album": "library_album",
            "Title": "library_title",
        })
    )

    result = plays.merge(
        library_exact,
        how="left",
        on=["_title_key", "_album_key"],
    )

    title_counts = library.groupby("_title_key").size()
    unique_title_keys = set(title_counts[title_counts == 1].index)
    library_unique_title = (
        library[library["_title_key"].isin(unique_title_keys)]
        .drop_duplicates("_title_key")
        [["_title_key", "Artist", "Album", "Title"]]
        .set_index("_title_key")
    )

    missing_artist = result["library_artist"].fillna("").eq("")
    if missing_artist.any():
        keys = result.loc[missing_artist, "_title_key"]
        result.loc[missing_artist, "library_artist"] = keys.map(
            library_unique_title["Artist"]
        )
        result.loc[missing_artist, "library_album"] = keys.map(
            library_unique_title["Album"]
        )
        result.loc[missing_artist, "library_title"] = keys.map(
            library_unique_title["Title"]
        )

    result["Artist"] = result["library_artist"].fillna("")
    result["Album"] = result["library_album"].where(
        result["library_album"].fillna("").ne(""),
        result["Album Name"],
    )
    result["Title"] = result["Song Name"]

    return result


def build_event_tracks(
    play_history_path: Path,
    track_info_path: Path,
) -> pd.DataFrame:
    plays = read_semicolon_csv(play_history_path)

    library = pd.read_excel(
        track_info_path,
        sheet_name="Apple Music Library Tracks",
        dtype=str,
    ).fillna("")

    timestamp = pd.to_datetime(
        plays["Event End Timestamp"],
        errors="coerce",
        utc=True,
    )
    plays["event_date"] = timestamp.dt.tz_convert(None).dt.normalize()
    plays["Event"] = plays.apply(create_event_name, axis=1)

    event_plays = plays[plays["Event"].ne("")].copy()
    event_plays = attach_library_metadata(event_plays, library)

    # One output row per track and event.
    tracks = (
        event_plays[["Artist", "Album", "Title", "Event"]]
        .drop_duplicates()
        .sort_values(["Event", "Artist", "Title"], kind="stable")
        .reset_index(drop=True)
    )

    tracks["_artist_key"] = tracks["Artist"].map(normalize_text)
    tracks["_title_key"] = tracks["Title"].map(normalize_text)
    tracks["_event_key"] = tracks["Event"].map(normalize_text)

    return tracks


def existing_match_lookup(existing: pd.DataFrame) -> dict[tuple[str, str, str], dict[str, str]]:
    """Index existing matches, preferring artist+title+event."""
    renamed = existing.rename(columns={
        "deezerTrackId": "deezer_track_id",
        "Deezer Track Id": "deezer_track_id",
    }).copy()

    expected = {
        "Artist", "Album", "Title", "Event",
        "deezer_preview_available", "deezer_track_id", "deezer_match_status",
    }
    for column in expected:
        if column not in renamed.columns:
            renamed[column] = ""

    lookup: dict[tuple[str, str, str], dict[str, str]] = {}
    for _, row in renamed.iterrows():
        key = (
            normalize_text(row["Artist"]),
            normalize_text(row["Title"]),
            normalize_text(row["Event"]),
        )
        lookup[key] = {
            "deezer_preview_available": str(row["deezer_preview_available"]),
            "deezer_track_id": str(row["deezer_track_id"]),
            "deezer_match_status": str(row["deezer_match_status"]),
        }
    return lookup


def deezer_query_variants(artist: str, title: str) -> list[str]:
    variants = [
        f'artist:"{artist}" track:"{title}"' if artist else f'track:"{title}"',
        f"{artist} {title}".strip(),
        title,
    ]
    # Preserve order while removing duplicates.
    return list(dict.fromkeys(query for query in variants if query))


def score_candidate(
    wanted_artist: str,
    wanted_title: str,
    wanted_album: str,
    item: dict[str, Any],
) -> Candidate:
    found_title = str(item.get("title", ""))
    found_artist = str((item.get("artist") or {}).get("name", ""))
    found_album = str((item.get("album") or {}).get("title", ""))

    title_score = similarity(wanted_title, found_title)
    artist_score = similarity(wanted_artist, found_artist)
    album_score = similarity(wanted_album, found_album)

    # Title is most important. Artist strongly protects against wrong songs.
    if wanted_artist:
        total = (0.60 * title_score) + (0.32 * artist_score) + (0.08 * album_score)
    else:
        total = (0.85 * title_score) + (0.15 * album_score)

    # Reward exact normalized matches.
    if normalize_text(wanted_title) == normalize_text(found_title):
        total += 0.05
    if wanted_artist and normalize_text(wanted_artist) == normalize_text(found_artist):
        total += 0.04

    return Candidate(
        track_id=str(item.get("id", "")),
        title=found_title,
        artist=found_artist,
        album=found_album,
        score=min(total, 1.0),
        title_score=title_score,
        artist_score=artist_score,
        album_score=album_score,
    )


def search_deezer(
    session: requests.Session,
    artist: str,
    title: str,
    album: str,
) -> tuple[Candidate | None, str]:
    best: Candidate | None = None
    error_message = ""

    for query in deezer_query_variants(artist, title):
        for attempt in range(1, MAX_API_RETRIES + 1):
            try:
                response = session.get(
                    DEEZER_SEARCH_URL,
                    params={"q": query, "limit": 25},
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                payload = response.json()
                items = payload.get("data", [])

                for item in items:
                    candidate = score_candidate(artist, title, album, item)
                    if best is None or candidate.score > best.score:
                        best = candidate
                break

            except (requests.RequestException, ValueError) as exc:
                error_message = str(exc)
                if attempt == MAX_API_RETRIES:
                    break
                time.sleep(attempt)

        if best and best.score >= CONFIDENT_MATCH_THRESHOLD:
            break

        time.sleep(SECONDS_BETWEEN_REQUESTS)

    return best, error_message


def boolean_text(value: bool) -> str:
    return "True" if value else "False"


def update_matches(
    event_tracks: pd.DataFrame,
    existing: pd.DataFrame,
    use_api: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    lookup = existing_match_lookup(existing)
    session = requests.Session()
    session.headers.update({
        "User-Agent": "SonicTracesPreviewMatcher/1.0"
    })

    output_rows: list[dict[str, str]] = []
    review_rows: list[dict[str, str]] = []
    missing_count = 0

    total = len(event_tracks)

    for index, row in event_tracks.iterrows():
        artist = str(row["Artist"])
        album = str(row["Album"])
        title = str(row["Title"])
        event = str(row["Event"])

        key = (
            normalize_text(artist),
            normalize_text(title),
            normalize_text(event),
        )
        old = lookup.get(key)

        if old and old.get("deezer_track_id", "").strip():
            output_rows.append({
                "Artist": artist,
                "Album": album,
                "Title": title,
                "Event": event,
                **old,
            })
            continue

        missing_count += 1
        print(f"[{index + 1}/{total}] Missing: {artist} | {title} | {event}")

        if not use_api:
            review_rows.append({
                "Artist": artist,
                "Album": album,
                "Title": title,
                "Event": event,
                "status": "not searched (--no-api)",
                "candidate_artist": "",
                "candidate_title": "",
                "candidate_album": "",
                "candidate_track_id": "",
                "score": "",
            })
            continue

        candidate, request_error = search_deezer(
            session=session,
            artist=artist,
            title=title,
            album=album,
        )

        if candidate and candidate.score >= CONFIDENT_MATCH_THRESHOLD:
            match_status = (
                "exact"
                if candidate.title_score == 1.0 and
                   (not artist or candidate.artist_score == 1.0)
                else "fuzzy_confident"
            )
            output_rows.append({
                "Artist": artist,
                "Album": album,
                "Title": title,
                "Event": event,
                "deezer_preview_available": "True",
                "deezer_track_id": candidate.track_id,
                "deezer_match_status": match_status,
            })
            print(
                f"  -> matched {candidate.artist} | {candidate.title} "
                f"(score {candidate.score:.3f})"
            )
        else:
            status = "unmatched"
            if candidate and candidate.score >= AMBIGUOUS_MATCH_THRESHOLD:
                status = "ambiguous"

            output_rows.append({
                "Artist": artist,
                "Album": album,
                "Title": title,
                "Event": event,
                "deezer_preview_available": "False",
                "deezer_track_id": "",
                "deezer_match_status": status,
            })
            review_rows.append({
                "Artist": artist,
                "Album": album,
                "Title": title,
                "Event": event,
                "status": status if not request_error else f"request error: {request_error}",
                "candidate_artist": candidate.artist if candidate else "",
                "candidate_title": candidate.title if candidate else "",
                "candidate_album": candidate.album if candidate else "",
                "candidate_track_id": candidate.track_id if candidate else "",
                "score": f"{candidate.score:.3f}" if candidate else "",
            })
            print(f"  -> {status}")

        time.sleep(SECONDS_BETWEEN_REQUESTS)

    result = pd.DataFrame(output_rows)
    review = pd.DataFrame(review_rows)

    print(f"\nEvent tracks: {total}")
    print(f"Tracks requiring a lookup: {missing_count}")
    print(f"Final matched track IDs: "
          f"{result['deezer_track_id'].fillna('').astype(str).str.strip().ne('').sum()}")

    return result, review


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Add missing Deezer Track IDs for Sonic Traces events."
    )
    parser.add_argument(
        "--plays",
        type=Path,
        default=Path("Apple Music Play Activity - Janina V3.csv"),
        help="Apple Music play-history CSV.",
    )
    parser.add_argument(
        "--track-info",
        type=Path,
        default=Path("Track Info.xlsx"),
        help="Excel workbook containing the 'Apple Music Library Tracks' sheet.",
    )
    parser.add_argument(
        "--existing",
        type=Path,
        default=Path("sonic_traces_with_deezer_previews(1).csv"),
        help="Current semicolon-separated preview/match CSV.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("sonic_traces_with_deezer_previews_updated.csv"),
        help="Updated output CSV.",
    )
    parser.add_argument(
        "--review-output",
        type=Path,
        default=Path("deezer_matches_to_review.csv"),
        help="Ambiguous/unmatched candidates for manual review.",
    )
    parser.add_argument(
        "--no-api",
        action="store_true",
        help="Prepare the missing-track review list without calling Deezer.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    for path, label in (
        (args.plays, "play-history CSV"),
        (args.track_info, "Track Info workbook"),
        (args.existing, "existing preview CSV"),
    ):
        if not path.exists():
            print(f"ERROR: Could not find {label}: {path}", file=sys.stderr)
            return 1

    try:
        event_tracks = build_event_tracks(args.plays, args.track_info)
        existing = read_semicolon_csv(args.existing)
        updated, review = update_matches(
            event_tracks=event_tracks,
            existing=existing,
            use_api=not args.no_api,
        )

        updated.to_csv(
            args.output,
            sep=";",
            index=False,
            encoding="utf-8-sig",
            quoting=csv.QUOTE_MINIMAL,
        )
        review.to_csv(
            args.review_output,
            sep=";",
            index=False,
            encoding="utf-8-sig",
            quoting=csv.QUOTE_MINIMAL,
        )

        print(f"\nSaved updated file: {args.output.resolve()}")
        print(f"Saved review file:  {args.review_output.resolve()}")
        return 0

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
