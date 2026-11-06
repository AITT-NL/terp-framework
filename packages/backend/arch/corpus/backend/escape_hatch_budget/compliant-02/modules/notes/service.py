def render_help():
    # Marker-shaped text inside a string is not counted by the budget ratchet:
    # with an empty budget this app is exactly in balance.
    return "suppress with '# arch-allow-no-dynamic-sql: <reason>' after review"
