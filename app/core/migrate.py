from app.core.migrations import run_sql_migrations


def main() -> None:
    applied = run_sql_migrations()
    if applied:
        print(f"Applied migrations: {', '.join(applied)}")
    else:
        print("No pending migrations")


if __name__ == "__main__":
    main()
