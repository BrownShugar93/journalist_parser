import sys
from datetime import datetime, timedelta, timezone

from auth import generate_salt, hash_password
from db import init_db, create_user, get_user_by_email, set_access_until


def usage():
    print("Usage:")
    print("  python3 manage_users.py create <email> <password>")
    print("  python3 manage_users.py grant <email> [days]")


def main():
    init_db()
    if len(sys.argv) < 2:
        usage()
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "create":
        if len(sys.argv) != 4:
            usage()
            sys.exit(1)
        email = sys.argv[2]
        password = sys.argv[3]
        salt = generate_salt()
        password_hash = hash_password(password, salt)
        try:
            user_id = create_user(email, password_hash, salt)
        except Exception:
            print("User already exists")
            sys.exit(1)
        print(f"Created user id={user_id} email={email}")
        return

    if cmd == "grant":
        if len(sys.argv) not in (3, 4):
            usage()
            sys.exit(1)
        email = sys.argv[2]
        days = int(sys.argv[3]) if len(sys.argv) == 4 else 1
        user = get_user_by_email(email)
        if not user:
            print("User not found")
            sys.exit(1)
        access_until = datetime.now(timezone.utc) + timedelta(days=days)
        set_access_until(int(user["id"]), access_until)
        print(f"Granted access until {access_until.isoformat()} to {email}")
        return

    usage()
    sys.exit(1)


if __name__ == "__main__":
    main()
