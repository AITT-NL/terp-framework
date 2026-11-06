def run(engine):
    with Session(engine) as s:
        return s
