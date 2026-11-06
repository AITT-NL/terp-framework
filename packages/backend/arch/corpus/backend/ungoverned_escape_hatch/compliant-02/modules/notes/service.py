def render_help():
    # Marker-shaped text inside a string is not an opt-out marker: it is neither
    # honoured nor counted, so this file carries no ungoverned marker.
    return "suppress with '# arch-allow-no-dynamic-sql: <reason>' after review"
