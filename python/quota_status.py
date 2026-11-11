"""Read Codex quota windows through the official app-server account API.

Only initialize and account/rateLimits/read are sent; no thread or model turn is
created. The caller reconciles any refreshed credentials after the query.
"""

import base64
import concurrent.futures
import datetime
import json
import math
import os
import pathlib
import queue
import re
import shutil
import signal
import subprocess
import threading
import time
from collections import deque


TIMEZONE = datetime.timezone(datetime.timedelta(hours=8))
TIMEOUT = 28


class QuotaError(Exception):
    pass


def identity(home):
    """Read only the fields needed to match a stored credential to an account."""
    try:
        value = json.loads((pathlib.Path(home) / "auth.json").read_text(encoding="utf-8-sig"))
        tokens = value.get("tokens") or {}
        payload = tokens["id_token"].split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if not tokens.get("refresh_token") or not tokens.get("account_id"):
            return None
        return {"email": claims.get("email"), "account_id": tokens["account_id"]}
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError):
        return None


def backend_command():
    """Prefer the installed extension backend, so its config schema matches."""
    home = pathlib.Path.home()
    if os.name == "nt":
        patterns = [
            ".vscode/extensions/openai.chatgpt-*/bin/windows-x86_64/codex.exe",
            ".vscode-insiders/extensions/openai.chatgpt-*/bin/windows-x86_64/codex.exe",
        ]
    else:
        # The existing launcher owns AMAX's Node PATH and SSH proxy settings.
        launcher = home / "bin/codex"
        if launcher.is_file() and os.access(str(launcher), os.X_OK):
            return [str(launcher)]
        patterns = [
            ".vscode-server/extensions/openai.chatgpt-*/bin/linux-x86_64/codex",
            ".vscode-server/extensions/openai.chatgpt-*/bin/linux-aarch64/codex",
        ]
    candidates = []
    for pattern in patterns:
        candidates.extend(p for p in home.glob(pattern) if p.is_file())
    if candidates:
        return [str(max(candidates, key=lambda p: p.stat().st_mtime))]
    if os.name == "nt":
        package = home / "AppData/Roaming/npm/node_modules/@openai/codex"
        candidates = list(package.glob("node_modules/@openai/codex-win32-*/vendor/*/codex/codex.exe"))
        if candidates:
            return [str(candidates[0])]
    executable = shutil.which("codex")
    if executable and not executable.lower().endswith((".cmd", ".ps1", ".bat")):
        return [executable]
    raise QuotaError("Codex backend not found; check the VS Code extension installation")


def child_environment(home):
    env = os.environ.copy()
    env["CODEX_HOME"] = str(home)
    # A status query must use this account's saved ChatGPT login, not another
    # authentication mode inherited from an unrelated terminal session.
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN"):
        env.pop(key, None)
    if os.name == "nt":
        import socket

        try:
            with socket.create_connection(("127.0.0.1", 7890), timeout=0.25):
                for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
                    env[key] = "http://127.0.0.1:7890"
        except OSError:
            pass
    return env


def safe_error(message):
    """Describe errors without ever echoing raw RPC responses or stderr."""
    text = str(message).lower()
    if any(word in text for word in ("401", "token_revoked", "refresh_token", "sign in", "not logged", "unauthorized")):
        return "login expired or rejected; sign in again"
    if "403" in text or "forbidden" in text:
        return "access denied (403); check account permissions/network"
    if "429" in text:
        return "quota service busy (429); retry later"
    if "timeout" in text or "timed out" in text:
        return "query timed out; check proxy/network"
    if "config" in text or "unknown variant" in text:
        return "backend configuration is incompatible; check Codex settings"
    if any(word in text for word in ("connect", "sending request", "network", "dns")):
        return "network request failed; check proxy/SSH connection"
    if "not found" in text or "no such file" in text:
        return "Codex backend not found"
    return "quota query failed; retry or check the Codex extension"


def fetch_limits(home, expected_id, command=None, timeout=TIMEOUT):
    command = list(command or backend_command())
    command += [
        "-c", 'model_provider="openai"',
        "-c", 'cli_auth_credentials_store="file"',
        "-c", 'chatgpt_base_url="https://chatgpt.com/backend-api/"',
        "-c", "features.apps=false",
        "-c", "features.plugins=false",
        "-c", "features.remote_plugin=false",
        "-c", "features.daemon_auto_start=false",
        "-c", "analytics.enabled=false",
        "app-server",
    ]
    options = {}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        options["start_new_session"] = True
    proc = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
        env=child_environment(home), cwd=str(home), **options
    )
    incoming = queue.Queue()
    errors = deque(maxlen=12)
    deadline = time.monotonic() + timeout

    def read_stdout():
        try:
            for line in proc.stdout:
                try:
                    message = json.loads(line)
                    if isinstance(message, dict):
                        incoming.put(message)
                except ValueError:
                    continue
        finally:
            incoming.put(None)

    def read_stderr():
        for line in proc.stderr:
            errors.append(line[:2000])

    readers = [threading.Thread(target=read_stdout, daemon=True), threading.Thread(target=read_stderr, daemon=True)]
    for reader in readers:
        reader.start()

    def send(message):
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()

    def receive(request_id):
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise QuotaError("query timed out; check proxy/network")
            try:
                message = incoming.get(timeout=remaining)
            except queue.Empty:
                raise QuotaError("query timed out; check proxy/network")
            if message is None:
                raise QuotaError(safe_error(" ".join(errors)))
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise QuotaError(safe_error(str(message["error"])))
            result = message.get("result")
            if not isinstance(result, dict):
                raise QuotaError("quota service returned an invalid response")
            return result

    try:
        send({"id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "cx_quota_status", "version": "1.0.0"}
        }})
        receive(1)
        send({"method": "initialized"})
        send({"id": 2, "method": "account/rateLimits/read"})
        result = receive(2)
        if result.get("accountId") and result["accountId"] != expected_id:
            raise QuotaError("quota response belongs to a different account; not displayed")
        return normalize_limits(result)
    except (BrokenPipeError, OSError):
        raise QuotaError(safe_error(" ".join(errors)))
    finally:
        if os.name != "nt":
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        elif proc.poll() is None:
            proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                proc.kill()
            else:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            proc.wait(timeout=2)
        for reader in readers:
            reader.join(timeout=1)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            stream.close()


def normalize_limits(result):
    buckets = result.get("rateLimitsByLimitId") or {}
    bucket = buckets.get("codex")
    if not isinstance(bucket, dict):
        bucket = result.get("rateLimits")
    if not isinstance(bucket, dict) or bucket.get("limitId") not in (None, "codex"):
        raise QuotaError("Codex quota bucket was not provided")
    output = {"five_hour": None, "weekly": None, "plan": bucket.get("planType")}
    for field in ("primary", "secondary"):
        window = bucket.get(field)
        if not isinstance(window, dict):
            continue
        duration = window.get("windowDurationMins")
        key = {300: "five_hour", 10080: "weekly"}.get(duration)
        used = window.get("usedPercent")
        if key is None or isinstance(used, bool) or not isinstance(used, (float, int)) or not math.isfinite(used):
            continue
        resets = window.get("resetsAt")
        output[key] = {
            "remaining": max(0, min(100, 100 - used)),
            "resets_at": resets if isinstance(resets, (int, float)) and not isinstance(resets, bool) and math.isfinite(resets) else None,
        }
    return output


def reset_text(window):
    if window is None or window.get("resets_at") is None:
        return "not reported"
    try:
        return datetime.datetime.fromtimestamp(window["resets_at"], TIMEZONE).strftime("%m-%d %H:%M")
    except (ValueError, OverflowError, OSError):
        return "not reported"


def remaining_text(window):
    return "N/A" if window is None else "{:g}%".format(round(window["remaining"], 1))


def display_status(root, active_number, default_home, emails):
    """Print all accounts without changing which plugin account is selected."""
    root, default_home = pathlib.Path(root), pathlib.Path(default_home)
    try:
        command = backend_command()
    except (QuotaError, OSError) as exc:
        print("Quota unavailable: " + str(exc))
        return
    requests = []
    results = {}
    for number, address in emails.items():
        home = default_home if str(number) == str(active_number) else root / str(number)
        auth = identity(home)
        if auth is None:
            results[number] = {"error": "not signed in locally"}
        elif (auth.get("email") or "").lower() != address.lower():
            results[number] = {"error": "stored login email mismatch; not queried"}
        else:
            requests.append((number, home, auth["account_id"]))
    print("Reading live 5-hour and weekly quotas...", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(fetch_limits, home, account_id, command): number
            for number, home, account_id in requests
        }
        for future in concurrent.futures.as_completed(futures):
            number = futures[future]
            try:
                results[number] = future.result()
            except QuotaError as exc:
                results[number] = {"error": str(exc)}
            except Exception as exc:
                results[number] = {"error": safe_error(str(exc))}
    print()
    print("   {:<38} {:>9} {:>11}".format("Account", "5h left", "Weekly left"))
    print("-" * 65)
    for number, address in emails.items():
        result = results[number]
        marker = "*" if str(number) == str(active_number) else " "
        if "error" in result:
            print("{}{} {:<38} {:>9} {:>11}".format(marker, number, address, "--", "--"))
            print("   " + result["error"])
        else:
            print("{}{} {:<38} {:>9} {:>11}".format(
                marker, number, address, remaining_text(result["five_hour"]), remaining_text(result["weekly"])))
            print("   Resets: 5h {} | Weekly {} (UTC+8)".format(
                reset_text(result["five_hour"]), reset_text(result["weekly"])))
    print()
    print("* selected plugin account | N/A = window not reported | -- = query failed")
    print("Remaining = 100% - reported usage; not a message/token count.")
    print("Updated: " + datetime.datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S UTC+8"))
