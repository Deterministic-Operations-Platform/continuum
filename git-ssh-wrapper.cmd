@echo off
C:\Windows\System32\OpenSSH\ssh.exe -i ".git/codex_ssh/id_ed25519_nopass2" -o IdentitiesOnly=yes -o UserKnownHostsFile=.git/codex_ssh/known_hosts -o StrictHostKeyChecking=accept-new %*
