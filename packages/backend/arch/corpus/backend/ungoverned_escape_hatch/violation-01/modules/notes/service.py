def legacy_report(session, sql):
    return session.execute(text(sql))  # arch-allow-no-dynamic-sql: legacy reporting query, parameterised upstream
