import subprocess


def login_with_token(token):
    """Log in to Codex with an access token. Returns (success, message)."""
    try:
        result = subprocess.run(
            ["codex", "login", "--with-access-token"],
            input=token,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return True, "Logged in successfully"
        else:
            msg = result.stderr.strip() or result.stdout.strip() or "Unknown error"
            return False, msg
    except FileNotFoundError:
        return False, "codex CLI not found in PATH"
    except subprocess.TimeoutExpired:
        return False, "Login command timed out"


def logout():
    """Log out of Codex. Returns (success, message)."""
    try:
        result = subprocess.run(
            ["codex", "logout"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            return True, "Logged out"
        else:
            msg = result.stderr.strip() or result.stdout.strip() or "Unknown error"
            return False, msg
    except FileNotFoundError:
        return False, "codex CLI not found in PATH"
    except subprocess.TimeoutExpired:
        return False, "Logout command timed out"


def get_status():
    """Check Codex login status. Returns (logged_in: bool, info: str)."""
    try:
        result = subprocess.run(
            ["codex", "login", "status"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        output = result.stdout.strip() + "\n" + result.stderr.strip()
        logged_in = result.returncode == 0 and "not logged" not in output.lower()
        return logged_in, output.strip()
    except FileNotFoundError:
        return False, "codex CLI not found"
    except subprocess.TimeoutExpired:
        return False, "Status check timed out"
