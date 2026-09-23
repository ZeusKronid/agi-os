# Minimal console installation

Status: **PASS on 2026-09-14**, using a real model through the private host bridge.
The HTML report and screenshots are delivered separately and are not committed.
Clean R3 passed installation, independent boot and a second boot with persisted data;
browser OAuth is a separate, untested path in this run.

## Environment

- Scenario: `e2e-minimal-20260914-r3`.
- ISO: `out/agi-os-desktop-2026.09.14.3-x86_64.iso` (includes the E2E fixes).
- QEMU/KVM, UEFI, 4 CPUs, 6 GiB RAM, separate blank 64 GiB QCOW2, standard VGA, NAT.
- This run used `gpt-6-astra` through `--dev-bridge`. For a separate authentication test, connect a real provider in the installer. Enter account credentials/API keys and
  the new system's password only in their private controls, not in the conversation.

## Request to paste into the installer

```text
Установи минимальную консольную систему без графического окружения и без SSH.
Мне нужен Python для запуска простых скриптов, остальные дополнительные приложения не нужны.
Имя компьютера agi-min, обычный пользователь tester с sudo по паролю.
Язык системы en_US.UTF-8, раскладка us, часовой пояс Europe/Moscow.
Используй весь пустой виртуальный диск 64 ГБ, ext4, без шифрования и без swap.
Загрузка UEFI через systemd-boot, сеть через NetworkManager.
Перед записью покажи выбранный диск и полную конфигурацию и дождись моего подтверждения.
После установки система должна загружаться с диска без ISO, позволять войти под
tester, запускать Python и сохранять мои файлы после перезагрузки.
```

## Expected flow

1. Sign in/connect the chosen provider and select a model.
2. Submit the request. The assistant can clarify missing choices, but should retain
   the supplied requirements. The final configuration must not add a desktop or SSH.
3. Review the actual destination disk (expected `/dev/vda`, 64 GiB), whole-disk
   erasure, ext4, separate EFI boot partition, systemd-boot, account and packages.
   If the disk or proposal differs, return to the conversation before accepting.
4. Enter a test account password privately and confirm the reviewed changes.
5. Observe installation and configuration. Save the exact visible error if a stage
   fails; do not mark a manually repaired attempt as a clean pass.
6. Use the installer's shutdown action. Wait for QEMU to exit, then start the same
   machine from its disk alone, on the host:

   ```sh
   cd /home/miniboss/Work/agi-os
   ./scripts/run-vm.sh --name e2e-minimal-20260914-r3 --mode disk
   ```

7. Expect a console login. Log in as `tester` using the password entered during
   installation. Run the following checks inside the installed guest:

   ```sh
   whoami
   hostname
   findmnt -n -o SOURCE,FSTYPE /
   systemctl get-default
   systemctl is-active NetworkManager
   timedatectl show -p Timezone --value
   cat /etc/locale.conf
   cat /etc/vconsole.conf
   getent hosts archlinux.org
   sudo -v
   python -c 'from pathlib import Path; p = Path.home() / "agi-install-test.txt"; p.write_text("AGI OS OK\n"); print(p.read_text(), end="")'
   ```

   Expected: `tester`, `agi-min`, an installed root partition with `ext4`,
   `multi-user.target`, active NetworkManager, `Europe/Moscow`, `en_US.UTF-8`,
   `KEYMAP=us` and `FONT=eurlatgr`, successful DNS lookup and password-protected sudo, `AGI OS OK`.

8. After verifying the agreed requirements, run `agi-os-verify --confirm`.
   On this first installed boot its persistence check should still be incomplete
   (exit status 1); the tool records a marker for the next boot. Any other failed
   check needs investigation.
9. Run `sudo reboot` inside the guest. Log in again, then run:

   ```sh
   cat ~/agi-install-test.txt
   agi-os-verify
   ```

   Expected: `AGI OS OK`, every check true, `complete: true`, verifier exit status 0.

## Pass criteria

All eight installation stages are observed: real provider connection, requirements,
storage choice, consent, installation, configuration, boot without ISO, first use.
The second disk boot retains the test file and settings. No unexpected manual repair
or silent requirement change is needed. A successful package install alone is not a pass.

Record the provider/model, final proposal, any errors, and actual boot/check outcomes
locally in ignored `docs/test-results/`; never commit reports, screenshots, credentials or private authentication details.
