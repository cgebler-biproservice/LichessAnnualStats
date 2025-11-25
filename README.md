# LichessAnnualStats
LichessAnnualStats generates a personalized yearly recap of your Lichess activity. It fetches your games and performance data via the Lichess API and compiles clear insights, summaries, and highlights of your chess year—fully automated with Python.

## Quick start (macOS & Linux)

Requires Python 3.9+ (stdlib only).

```bash
python3 lichess_annual_stats.py --username <handle> --year 2025
# or omit --username to be prompted interactively
python3 lichess_annual_stats.py --year 2025
```

Options:
- `--username`: Lichess handle (prompts if omitted)
- `--year`: Target year (default: 2025)
- `--token`: Optional Lichess API token (enables private games and puzzle stats)

The script streams NDJSON from the public Lichess API and prints:
- Total games and speed breakdown (bullet, blitz, rapid, classical)
- Results (W/D/L) overall and by color, plus longest win/loss streaks
- Opponent rating avg per speed, rating buckets, and top-3 rated wins
- Activity heatmap counts (month, weekday) and longest inactivity gap
- Ending types (mate, resign, stalemate, timeouts, aborted, draws)
- If `--token` is provided: puzzle rating (start/end/peak) and puzzles attempted in the year (best-effort)

Authentication is not needed for public data; add `--token` to include private games and puzzles.

To create a token: visit https://lichess.org/account/oauth/token, choose a description, set an expiry if desired, and grant the `puzzle:read` scope (and any others you need). Then pass it via `--token <your_token>`. Keep it private.
