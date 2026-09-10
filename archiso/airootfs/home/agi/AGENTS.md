# AGI OS live support session

The primary installer is our application, launched with `agi-installer`. It owns
provider connection, the conversation, review, disk consent, execution and progress.
Read `/usr/local/share/agi-os/installation-flow.md` for the shared lifecycle.

Do not start a second installation in parallel with the application. When asked
to diagnose a failure, inspect the current state and help recover without assuming
that a new disk wipe is needed. Confirm any additional destructive scope with the
user. Never put credentials in chat, command arguments or logs. Do not silently
change the requested environment or applications. The live desktop does not
prescribe the installed system. Distinguish completed disk writes from verified
first boot and acceptance of the user's requirements.
