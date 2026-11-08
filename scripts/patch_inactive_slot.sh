#!/system/bin/sh
# patch_inactive_slot.sh - 给「非当前槽位」的 init_boot 打 KernelSU/SukiSU 补丁
#
# 用途：系统 OTA 已写入 inactive slot、等待重启时，在重启前把新槽的 init_boot
#       打上补丁，这样切换槽位后 root 依然存在（本仓库 README 第三部分）。
#
# 用法（在设备上，root shell 执行）：
#   su -c 'sh /data/local/tmp/patch_inactive_slot.sh'
#   su -c 'sh /data/local/tmp/patch_inactive_slot.sh --block-vr'
#
# 之后在电脑上：
#   adb reboot bootloader
#   fastboot flash init_boot_<目标槽> /path/to/kernelsu_patched_*.img
#
# 依赖：已 root 的当前系统、/data/adb/ksud 可用、目标槽的 init_boot 存在。

set -u

KMI="${KMI:-android13-5.15}"
OUTDIR=/sdcard/Download
BLOCK_VR=0
for a in "$@"; do
	case "$a" in
		--block-vr) BLOCK_VR=1 ;;
		--kmi=*)    KMI="${a#--kmi=}" ;;
		-h|--help)
			echo "usage: $0 [--block-vr] [--kmi=android13-5.15]"
			exit 0
			;;
	esac
done

KSUD=/data/adb/ksud
[ -x "$KSUD" ] || { echo "error: $KSUD not found (root manager not installed?)"; exit 1; }

CUR=$(getprop ro.boot.slot_suffix)
[ -n "$CUR" ] || { echo "error: cannot read ro.boot.slot_suffix"; exit 1; }
case "$CUR" in
	_a) TGT=_b ;;
	_b) TGT=_a ;;
	*)   echo "error: unexpected slot suffix '$CUR'"; exit 1 ;;
esac

SRC=/dev/block/by-name/init_boot$TGT
[ -e "$SRC" ] || { echo "error: $SRC not found"; exit 1; }

IMG="$OUTDIR/init_boot$TGT.img"
echo "[*] current slot : $CUR"
echo "[*] target slot  : $TGT"
echo "[*] dump $SRC -> $IMG"
dd if="$SRC" of="$IMG" bs=4096 || exit 1

ARGS="boot-patch -b $IMG --kmi $KMI --partition init_boot -o $OUTDIR"
[ "$BLOCK_VR" = "1" ] && ARGS="$ARGS --block-module vr"

echo "[*] $KSUD $ARGS"
"$KSUD" $ARGS || exit 1

echo
echo "[*] 完成。把输出目录里最新的 kernelsu_patched_*.img 刷到目标槽："
echo "    adb reboot bootloader"
echo "    fastboot flash init_boot$TGT kernelsu_patched_*.img"
echo "    fastboot reboot"
echo "[*] 回滚：fastboot set_active ${CUR#_} && fastboot reboot"
