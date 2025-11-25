#!/usr/bin/env python3
"""
Fetch a simple yearly Lichess recap: total games played for a user in a given year,
including a breakdown by speed (bullet, blitz, rapid, classical).

Example:
    python lichess_annual_stats.py --username <handle> --year 2025
    python lichess_annual_stats.py --year 2025  # prompts for username
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional


LICHESS_API_BASE = "https://lichess.org/api/games/user"
LICHESS_USER_BASE = "https://lichess.org/api/user"


def _year_bounds_ms(year: int) -> tuple[int, int]:
    """Return (since_ms, until_ms) for the start and end of the given year in UTC."""
    start = dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc)
    end = dt.datetime(year + 1, 1, 1, tzinfo=dt.timezone.utc)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def fetch_game_stats(username: str, year: int, token: Optional[str] = None) -> dict:
    """Stream all games for the user in the given year and return aggregate counts."""
    since_ms, until_ms = _year_bounds_ms(year)
    query = {
        "since": since_ms,
        "until": until_ms,
        "max": 300000,  # high cap to avoid accidental truncation
        "moves": "false",
        "pgnInJson": "false",
        "clocks": "false",
        "evals": "false",
        "opening": "false",
    }
    url = f"{LICHESS_API_BASE}/{urllib.parse.quote(username)}?{urllib.parse.urlencode(query)}"

    request = urllib.request.Request(url)
    request.add_header("Accept", "application/x-ndjson")
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    stats: dict[str, object] = {
        "total": 0,
        "speed_counts": {"bullet": 0, "blitz": 0, "rapid": 0, "classical": 0},
        "other_speeds": 0,
        "results": {"win": 0, "loss": 0, "draw": 0},
        "color_results": {
            "white": {"win": 0, "loss": 0, "draw": 0},
            "black": {"win": 0, "loss": 0, "draw": 0},
        },
        "endings": {
            "mate": 0,
            "resign": 0,
            "stalemate": 0,
            "timeout": 0,
            "outoftime": 0,
            "aborted": 0,
            "draw": 0,
            "other": 0,
        },
        "timeout_wins": 0,
        "timeout_losses": 0,
        "opponent_rating_sum": 0,
        "opponent_rating_count": 0,
        "opponent_by_speed": {
            "bullet": {"sum": 0, "count": 0},
            "blitz": {"sum": 0, "count": 0},
            "rapid": {"sum": 0, "count": 0},
            "classical": {"sum": 0, "count": 0},
        },
        "opponent_hist": {},
        "top_wins": [],  # list of tuples (rating, name, game_id)
        "month_counts": [0] * 12,
        "wday_counts": [0] * 7,
        "hour_counts": [0] * 24,
        "longest_win_streak": 0,
        "longest_loss_streak": 0,
        "longest_gap_ms": 0,
    }

    timeline: list[tuple[int, str]] = []
    timestamps: list[int] = []
    username_lower = username.lower()
    try:
        with urllib.request.urlopen(request) as response:
            for raw_line in response:
                if not raw_line.strip():
                    continue
                stats["total"] = int(stats["total"]) + 1
                try:
                    game = json.loads(raw_line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue  # skip malformed lines while keeping total count

                ts = game.get("createdAt") or game.get("lastMoveAt")
                if isinstance(ts, int):
                    timestamps.append(ts)
                    dt_obj = dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc)
                    stats["month_counts"][dt_obj.month - 1] += 1
                    stats["wday_counts"][dt_obj.weekday()] += 1
                    stats["hour_counts"][dt_obj.hour] += 1

                speed = game.get("speed")
                if speed in stats["speed_counts"]:
                    stats["speed_counts"][speed] += 1
                else:
                    stats["other_speeds"] = int(stats["other_speeds"]) + 1

                players = game.get("players", {})
                white = players.get("white", {})
                black = players.get("black", {})
                user_color = None
                opp_color = None
                white_id = (white.get("user") or {}).get("id", "").lower()
                black_id = (black.get("user") or {}).get("id", "").lower()
                if white_id == username_lower:
                    user_color = "white"
                    opp_color = "black"
                elif black_id == username_lower:
                    user_color = "black"
                    opp_color = "white"

                status = str(game.get("status", "")).lower()
                winner = game.get("winner")

                is_draw_status = status in {
                    "draw",
                    "stalemate",
                    "repetition",
                    "50move",
                    "timevsinsufficientmaterial",
                    "insufficientmaterial",
                    "agreed",
                }

                outcome = None
                if user_color:
                    if winner == user_color:
                        outcome = "win"
                    elif winner in ("white", "black"):
                        outcome = "loss"
                    elif is_draw_status or winner is None:
                        outcome = "draw"
                    else:
                        outcome = "draw"

                    stats["results"][outcome] += 1
                    stats["color_results"][user_color][outcome] += 1

                    timeline.append((ts or 0, outcome))

                if status:
                    key = status if status in stats["endings"] else "other"
                    stats["endings"][key] = int(stats["endings"][key]) + 1
                    if status in ("timeout", "outoftime"):
                        if outcome == "win":
                            stats["timeout_wins"] += 1
                        elif outcome == "loss":
                            stats["timeout_losses"] += 1

                if user_color and opp_color:
                    opp_player = black if opp_color == "black" else white
                    opp_rating = opp_player.get("rating")
                    if isinstance(opp_rating, int):
                        stats["opponent_rating_sum"] += opp_rating
                        stats["opponent_rating_count"] += 1
                        if speed in stats["opponent_by_speed"]:
                            stats["opponent_by_speed"][speed]["sum"] += opp_rating
                            stats["opponent_by_speed"][speed]["count"] += 1
                        bucket = (opp_rating // 100) * 100
                        hist = stats["opponent_hist"]
                        hist[bucket] = hist.get(bucket, 0) + 1
                        if outcome == "win":
                            opp_name = (opp_player.get("user") or {}).get("name") or "?"
                            stats["top_wins"].append((opp_rating, opp_name, game.get("id")))
                            stats["top_wins"].sort(key=lambda t: t[0], reverse=True)
                            if len(stats["top_wins"]) > 3:
                                stats["top_wins"].pop()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Lichess API returned HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Request to Lichess failed: {exc.reason}") from exc

    if timeline:
        timeline.sort(key=lambda x: x[0])
        longest_win = longest_loss = 0
        current_win = current_loss = 0
        for _, outcome in timeline:
            if outcome == "win":
                current_win += 1
                current_loss = 0
            elif outcome == "loss":
                current_loss += 1
                current_win = 0
            else:
                current_win = 0
                current_loss = 0
            longest_win = max(longest_win, current_win)
            longest_loss = max(longest_loss, current_loss)
        stats["longest_win_streak"] = longest_win
        stats["longest_loss_streak"] = longest_loss

    if len(timestamps) > 1:
        timestamps.sort()
        gaps = [timestamps[i] - timestamps[i - 1] for i in range(1, len(timestamps))]
        stats["longest_gap_ms"] = max(gaps)

    return stats


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lichess yearly game counter")
    parser.add_argument(
        "--username",
        help="Lichess username (will prompt if omitted)",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=2025,
        help="Year to summarize (default: 2025)",
    )
    parser.add_argument(
        "--token",
        help="Optional Lichess API token (enables private games and puzzle stats)",
    )
    return parser.parse_args(argv)


def fetch_puzzle_stats(username: str, year: int, token: Optional[str]) -> Optional[dict]:
    """Fetch puzzle rating history and yearly puzzle attempts (requires token)."""
    if not token:
        return None

    result: dict[str, object] = {}
    # Rating history summary (start/end/peak)
    rating_url = f"{LICHESS_USER_BASE}/{urllib.parse.quote(username)}/rating-history"
    rating_req = urllib.request.Request(rating_url)
    rating_req.add_header("Accept", "application/json")
    rating_req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(rating_req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        puzzle_block = next((b for b in data if b.get("name") == "Puzzle"), None)
        points = (puzzle_block or {}).get("points") or []
        ratings = [p[3] for p in points if len(p) >= 4]
        if ratings:
            result["rating"] = {
                "start": ratings[0],
                "end": ratings[-1],
                "peak": max(ratings),
                "points": len(ratings),
            }
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
        pass

    # Puzzle attempts in the year (best-effort)
    since_ms, until_ms = _year_bounds_ms(year)
    activity_url = f"https://lichess.org/api/puzzle/activity?since={since_ms}&until={until_ms}"
    activity_req = urllib.request.Request(activity_url)
    activity_req.add_header("Accept", "application/x-ndjson")
    activity_req.add_header("Authorization", f"Bearer {token}")
    attempts = 0
    try:
        with urllib.request.urlopen(activity_req) as resp:
            for raw in resp:
                if not raw.strip():
                    continue
                try:
                    json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                attempts += 1
        result["attempts"] = attempts
    except urllib.error.HTTPError:
        if result:
            result.setdefault("attempts", None)
    except urllib.error.URLError:
        if result:
            result.setdefault("attempts", None)

    return result if result else None


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    username = args.username or input("Enter Lichess username: ").strip()
    if not username:
        print("Error: a Lichess username is required.", file=sys.stderr)
        return 1

    try:
        stats = fetch_game_stats(username, args.year, args.token)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    total = stats["total"]
    speed_counts = stats["speed_counts"]
    print(f"{username} played {total} games in {args.year}.")
    print("Breakdown by speed:")
    print(f"  Bullet:     {speed_counts['bullet']}")
    print(f"  Blitz:      {speed_counts['blitz']}")
    print(f"  Rapid:      {speed_counts['rapid']}")
    print(f"  Classical:  {speed_counts['classical']}")
    if stats["other_speeds"]:
        print(f"  Other:      {stats['other_speeds']}")

    wins = stats["results"]["win"]
    draws = stats["results"]["draw"]
    losses = stats["results"]["loss"]
    print("\nResults:")
    print(f"  Wins/Draws/Losses: {wins}/{draws}/{losses}")
    cr_white = stats["color_results"]["white"]
    cr_black = stats["color_results"]["black"]
    print(
        f"  As White (W/D/L): {cr_white['win']}/{cr_white['draw']}/{cr_white['loss']}   "
        f"As Black (W/D/L): {cr_black['win']}/{cr_black['draw']}/{cr_black['loss']}"
    )
    print(
        f"  Longest streaks - Win: {stats['longest_win_streak']} | "
        f"Loss: {stats['longest_loss_streak']}"
    )

    print("\nOpponent strength:")
    per_speed_lines = []
    for spd in ("bullet", "blitz", "rapid", "classical"):
        s = stats["opponent_by_speed"][spd]
        if s["count"]:
            per_speed_lines.append(f"{spd} {s['sum']/s['count']:.1f} ({s['count']})")
    if per_speed_lines:
        print(f"  By speed: {', '.join(per_speed_lines)}")
    else:
        print("  No rating data available")
    hist_items = sorted(stats["opponent_hist"].items())
    if hist_items:
        buckets = ", ".join([f"{b}s:{c}" for b, c in hist_items])
        print(f"  Rating buckets (per 100): {buckets}")
    top_wins = stats["top_wins"]
    if top_wins:
        print("  Top-3 highest rated wins:")
        for rating, name, gid in top_wins:
            print(f"    {rating} vs {name} (game {gid})")

    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    months_line = " ".join([f"{m}:{c}" for m, c in zip(months, stats["month_counts"])])
    wdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    wday_line = " ".join([f"{wd}:{c}" for wd, c in zip(wdays, stats["wday_counts"])])
    print("\nActivity:")
    print(f"  Games per month: {months_line}")
    print(f"  Games per weekday: {wday_line}")
    if stats["longest_gap_ms"]:
        gap_days = stats["longest_gap_ms"] / (1000 * 60 * 60 * 24)
        print(f"  Longest inactivity: {gap_days:.2f} days")

    endings = stats["endings"]
    print("\nEndings (tactics-ish):")
    print(
        f"  Mate: {endings['mate']} | Resign: {endings['resign']} | "
        f"Stalemate: {endings['stalemate']} | Time out: {endings['timeout']} | "
        f"Out of time: {endings['outoftime']} | Draw: {endings['draw']} | "
        f"Aborted: {endings['aborted']}"
    )
    if endings.get("other"):
        print(f"  Other endings: {endings['other']}")
    if stats["timeout_wins"] or stats["timeout_losses"]:
        print(
            f"  Flag wins: {stats['timeout_wins']} | Flag losses: {stats['timeout_losses']}"
        )

    print("\nFair play-ish:")
    print(f"  Aborted/expired games: {endings.get('aborted', 0)}")

    if args.token:
        puzzle = fetch_puzzle_stats(username, args.year, args.token)
        print("\nPuzzles (needs token):")
        if puzzle:
            rating = puzzle.get("rating")
            attempts = puzzle.get("attempts")
            if rating:
                print(
                    f"  Rating start/end/peak: {rating['start']} / {rating['end']} / {rating['peak']} "
                    f"(data points: {rating['points']})"
                )
            if attempts is not None:
                print(f"  Puzzles attempted in {args.year}: {attempts}")
            else:
                print(f"  Puzzles attempted in {args.year}: not available")
        else:
            print("  No puzzle data available (check token or activity).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
