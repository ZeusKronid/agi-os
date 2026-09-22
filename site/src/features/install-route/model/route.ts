export type OsId = 'linux' | 'mac' | 'win'
export type TargetId = 'usb' | 'vm'
export type StepId = 'download' | 'verify' | 'find' | 'write' | 'vm' | 'boot'

export interface Choice<Id extends string> {
  id: Id
  name: string
  note: string
  tag?: string
}

export const osChoices: readonly Choice<OsId>[] = [
  { id: 'linux', name: 'Linux', note: 'Any distribution' },
  { id: 'mac', name: 'macOS', note: 'Intel or Apple silicon' },
  { id: 'win', name: 'Windows', note: '10 or 11' },
]

export const targetChoices: readonly Choice<TargetId>[] = [
  { id: 'usb', name: 'USB stick', note: 'Boot a PC from it' },
  // Тестовый стенд проекта — QEMU/KVM с UEFI (scripts/run-live-web-vm.sh).
  { id: 'vm', name: 'Virtual machine', note: 'QEMU/KVM with UEFI — how it’s tested', tag: 'safest' },
]

export const stepTitles: Record<StepId, string> = {
  download: 'Download the image',
  verify: 'Check the fingerprint',
  find: 'Find your stick',
  write: 'Write the image',
  vm: 'Create the virtual machine',
  boot: 'Boot the ISO',
}

/** Шаги маршрута: общие «скачать» и «сверить», дальше — под выбранную систему и носитель. */
export function routeSteps(os: OsId, target: TargetId): StepId[] {
  if (target === 'vm') return ['download', 'verify', 'vm', 'boot']
  // Rufus сам показывает список носителей, отдельный шаг «найти флешку» не нужен.
  if (os === 'win') return ['download', 'verify', 'write', 'boot']
  return ['download', 'verify', 'find', 'write', 'boot']
}

export function verifyCommand(os: OsId, file: string): string {
  if (os === 'win') return `Get-FileHash .\\Downloads\\${file} -Algorithm SHA256`
  if (os === 'mac') return `shasum -a 256 ~/Downloads/${file}`
  return `sha256sum ~/Downloads/${file}`
}

export function findCommand(os: Exclude<OsId, 'win'>): string {
  return os === 'mac' ? 'diskutil list external' : 'lsblk -d -o NAME,SIZE,MODEL'
}

export function writeCommands(os: Exclude<OsId, 'win'>, file: string): string[] {
  if (os === 'mac') {
    return ['diskutil unmountDisk /dev/diskN', `sudo dd if=~/Downloads/${file} of=/dev/rdiskN bs=4m`]
  }
  return [`sudo dd if=~/Downloads/${file} of=/dev/sdX bs=4M status=progress oflag=sync`]
}

/** Конфигурация тестового стенда: UEFI, 10 ГБ памяти, 6 vCPU, диск 20 ГБ, CPU хоста (превью запускает свою VM). */
export function vmCommands(file: string): string[] {
  return [
    'qemu-img create -f qcow2 agios.qcow2 20G',
    `qemu-system-x86_64 -machine q35 -accel kvm -cpu host -m 10G -smp 6 -drive if=pflash,format=raw,readonly=on,file=/usr/share/edk2/x64/OVMF_CODE.4m.fd -cdrom ${file} -drive file=agios.qcow2,if=virtio`,
  ]
}
