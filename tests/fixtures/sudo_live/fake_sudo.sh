#!/bin/sh
# Fake sudo for tests/integration/test_sudo_probe_live.py (2026-10-13).
# Reproduces sudo's observable prompt behaviour without touching PAM, so the live matrix can replay the result
# shapes that os-gather/tasks/linux/try_one_sudo.yml classifies. Mode = suffix of the installed file name
# (se_fake_sudo_<mode>): reject | rc1 | hang. One line per invocation is appended to "<path>.log".
# Ansible invokes it as: <exe> -H -S -k -p "<prompt>" -u root /bin/sh -c '<command>'
# (flags from ansible_become_flags; -n is removed by the sudo become plugin when a password is set).
mode="${0##*_}"
log="$0.log"
prompt=""
while [ $# -gt 0 ]; do
  case "$1" in
    -p) prompt="$2"; shift 2 ;;
    -u) shift 2 ;;
    -*) shift ;;
    *) break ;;
  esac
done
stty -echo 2>/dev/null
# real sudo -S writes the prompt to stderr; under the pty Ansible reads both streams
printf '%s' "$prompt" >&2
got=0
if IFS= read -r _line; then got=1; fi
printf 'mode=%s got_password=%s\n' "$mode" "$got" >> "$log"
case "$mode" in
  reject)
    # wrong password: sudo prints its failure sentence and prompts again — Ansible ends the session here
    printf '\nSorry, try again.\n' >&2
    printf '%s' "$prompt" >&2
    IFS= read -r _line
    printf '\nSorry, try again.\n' >&2
    printf '%s' "$prompt" >&2
    IFS= read -r _line
    printf '\nsudo: 3 incorrect password attempts\n' >&2
    exit 1 ;;
  rc1)
    # passwd_tries=1 style: no retry sentence, the process ends with a status code
    printf '\nsudo: 1 incorrect password attempt\n' >&2
    exit 1 ;;
  hang)
    # prompt answered, then nothing — Ansible gives up after its escalation timeout
    sleep 600
    exit 1 ;;
  *)
    printf 'fake sudo: unknown mode %s\n' "$mode" >&2
    exit 2 ;;
esac
