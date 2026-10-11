"""Official play-by-play: the game state TrackMan doesn't record (runners on base, score, RBI, earned runs).

`boxscore` reads a Sidearm box-score page into plain rows, `plays` replays those rows to get the base /
out / score state before every plate appearance, and `match` lines the plate appearances up with
TrackMan's. Definitions are in METRICS.md section 4.
"""
